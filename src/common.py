"""Shared plumbing: config loading, paths, polite HTTP, run log.

Every URL, selector, delay, retry count and date rule comes from
config/*.yaml. Nothing of the sort is hardcoded here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import random
import sys
import time
import unicodedata
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
def load_config(name: str = "sources.yaml") -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def repo_path(rel: str) -> Path:
    p = REPO_ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def listing_url(cfg: dict) -> str:
    return cfg["listing"]["url_template"].format(
        base_url=cfg["http"]["base_url"],
        clave=cfg["issuer"]["clave"],
        id_emisora=cfg["issuer"]["id_emisora"],
        tipo_mercado=cfg["issuer"]["tipo_mercado"],
    )


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------
def fold(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace - for label matching."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def parse_number(text: str):
    """'59,993,000,000' -> 59993000000. Returns None if not a clean integer."""
    t = (text or "").strip().replace("$", "").replace(" ", "")
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    t = t.replace(",", "")
    if not t or not t.isdigit():
        return None
    v = int(t)
    return -v if neg else v


# --------------------------------------------------------------------------
# run log
# --------------------------------------------------------------------------
class RunLog:
    def __init__(self, cfg: dict):
        self.path = repo_path(cfg["paths"]["run_log"])
        self.alerts: list[str] = []

    def _write(self, level: str, msg: str) -> None:
        line = f"[{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}] {level}: {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def info(self, msg: str) -> None:
        self._write("INFO", msg)

    def warn(self, msg: str) -> None:
        self._write("WARN", msg)

    def alert(self, msg: str) -> None:
        self.alerts.append(msg)
        self._write("ALERT", msg)


# --------------------------------------------------------------------------
# polite HTTP
# --------------------------------------------------------------------------
class PoliteSession:
    """>= delay_seconds between requests, exponential backoff on 429/5xx."""

    def __init__(self, cfg: dict, log: RunLog | None = None):
        h = cfg["http"]
        self.cfg = h
        self.log = log
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": h["user_agent"],
                "Accept-Language": h["accept_language"],
            }
        )

    def _throttle(self) -> None:
        wait = self.cfg["delay_seconds"] - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, **kw) -> requests.Response:
        retry_on = set(self.cfg["retry_on_status"])
        attempt = 0
        while True:
            self._throttle()
            try:
                resp = self.session.get(url, timeout=self.cfg["timeout_seconds"], **kw)
                self._last_request_at = time.monotonic()
            except requests.RequestException as exc:
                resp = None
                err = f"{type(exc).__name__}: {exc}"
                self._last_request_at = time.monotonic()
            else:
                if resp.status_code not in retry_on:
                    return resp
                err = f"HTTP {resp.status_code}"

            attempt += 1
            if attempt > self.cfg["max_retries"]:
                if resp is not None:
                    return resp
                raise RuntimeError(f"GET {url} failed after retries: {err}")

            delay = min(
                self.cfg["backoff_base_seconds"] * (2 ** (attempt - 1)),
                self.cfg["backoff_max_seconds"],
            ) + random.uniform(0, 1)
            if self.log:
                self.log.warn(f"{err} on {url} - retry {attempt}/{self.cfg['max_retries']} in {delay:.1f}s")
            time.sleep(delay)


def check_robots(cfg: dict, sess: PoliteSession, log: RunLog) -> bool:
    """Returns True if we may proceed. Never works around a Disallow."""
    r = sess.get(cfg["robots"]["url"])
    if r.status_code == 404:
        log.info("robots.txt: 404 - no robots.txt published, nothing disallowed")
        return True
    if r.status_code != 200:
        log.warn(f"robots.txt: HTTP {r.status_code} - treating as absent")
        return True

    text = r.text
    log.info(f"robots.txt: 200, {len(text)} bytes")
    if not cfg["robots"].get("honour_disallow", True):
        return True

    # Coarse but conservative: any Disallow covering our two paths stops us.
    ours = ["/es/emisoras/", cfg["listing"]["link_href_prefix"]]
    ua_applies = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        k = key.lower()
        if k == "user-agent":
            ua_applies = val in ("*",)
        elif k == "disallow" and ua_applies and val:
            for path in ours:
                if path.startswith(val) or val == "/":
                    log.alert(f"robots.txt Disallow: {val} covers {path} - STOPPING")
                    return False
    return True


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def resolve_end_date(value) -> dt.date:
    if value in (None, "today"):
        return dt.date.today()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def resolve_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))
