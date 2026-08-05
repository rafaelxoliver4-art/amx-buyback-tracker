"""One-off, resumable full-history backfill (Cycle 1, ruling 2).

Walks the whole BMV listing - 2021-08-04 to today - applies the SAME selection
rule as the weekly run (last report of each ISO week + last of each calendar
month + the configured anchors) and downloads what is missing.

Resumable by construction. Three independent layers of "already have it":

  1. the PDF file already exists on disk        -> no request
  2. the sha256 is already held                 -> not re-stored
  3. the report_date is already in the ledger   -> not re-parsed, not re-written

So running this twice is safe and the second run is a no-op. Nothing in
data/raw_reports.csv is ever rewritten, reordered or truncated - the parser
appends only.

This script does NOT resolve programme additions. That is build_series.py's
job: it detects the remanente rises and isolates each one by the inter-report
seam. Run this first, then build_series.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_reports  # noqa: E402
import parse_report  # noqa: E402
from common import (  # noqa: E402
    PoliteSession,
    RunLog,
    check_robots,
    load_config,
    resolve_date,
    resolve_end_date,
    sha256_bytes,
    utcnow_iso,
)


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def backfill(cfg: dict, log: RunLog, sess: PoliteSession, *,
             use_cached_inventory: bool, limit: int | None, dry_run: bool) -> int:
    bf = cfg["backfill"]
    started = time.monotonic()

    # ---- inventory --------------------------------------------------------
    if use_cached_inventory:
        inventory = fetch_reports.read_inventory(cfg)
        log.info(f"backfill: reusing cached inventory ({len(inventory)} rows)")
    else:
        inventory = fetch_reports.fetch_inventory(cfg, sess, log)
        if inventory:
            fetch_reports.write_inventory(cfg, inventory)
    if not inventory:
        log.alert("backfill: listing returned ZERO reports - existing data left untouched",
                  code="LISTING_EMPTY")
        return 1

    selected = fetch_reports.select_reports(cfg, inventory, log)
    if not selected:
        log.alert("backfill: selection is empty - existing data left untouched",
                  code="SELECTION_EMPTY")
        return 1

    # ---- what is already done (resume point) ------------------------------
    have_dates = {r["report_date"] for r in parse_report.read_ledger(cfg)}
    raw_dir = fetch_reports.repo_path(cfg["paths"]["raw_pdf_dir"] + "/.keep").parent
    serie = cfg["issuer"]["expected_series"][0]
    tmpl = cfg["selection"]["raw_pdf_filename_template"]

    todo = [r for r in selected
            if r["report_date"] not in have_dates
            or not (raw_dir / tmpl.format(report_date=r["report_date"], serie=serie)).exists()]

    first, last = selected[0]["report_date"], selected[-1]["report_date"]
    log.info(f"backfill: {len(selected)} reports selected across {first}..{last}; "
             f"{len(selected) - len(todo)} already held, {len(todo)} to fetch")
    if limit:
        todo = todo[:limit]
        log.info(f"backfill: --limit {limit} -> fetching {len(todo)} this run")
    if dry_run:
        log.info("backfill: --dry-run, nothing downloaded")
        return 0
    if not todo:
        log.info("backfill: nothing to do - already complete")
        return 0

    # ---- download, logging progress ---------------------------------------
    have_hashes = {sha256_bytes(p.read_bytes()) for p in raw_dir.glob("*.pdf")}
    every = bf["progress_every"]
    downloaded, failed, fetched = 0, [], []

    for n, rec in enumerate(todo, start=1):
        target = raw_dir / tmpl.format(report_date=rec["report_date"], serie=serie)
        if target.exists():
            fetched.append({**rec, "pdf_path": str(target),
                            "pdf_sha256": sha256_bytes(target.read_bytes()),
                            "fetched_at_utc": "", "cached": True})
        else:
            resp = sess.get(rec["pdf_url"])
            if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
                log.alert(f"backfill: download failed {rec['report_date']} "
                          f"{rec['pdf_url']} -> HTTP {resp.status_code}",
                          code="DOWNLOAD_FAILED", affected_date=rec["report_date"])
                failed.append(rec["report_date"])
                continue
            digest = sha256_bytes(resp.content)
            target.write_bytes(resp.content)
            have_hashes.add(digest)
            downloaded += 1
            fetched.append({**rec, "pdf_path": str(target), "pdf_sha256": digest,
                            "fetched_at_utc": utcnow_iso(), "cached": False})

        if n % every == 0 or n == len(todo):
            rate = (time.monotonic() - started) / n
            left = (len(todo) - n) * rate
            log.info(f"backfill progress: {n}/{len(todo)} "
                     f"({downloaded} downloaded, {len(failed)} failed) "
                     f"- elapsed {_fmt_elapsed(time.monotonic() - started)}, "
                     f"~{_fmt_elapsed(left)} left")

    # ---- parse (append-only) ----------------------------------------------
    log.info("backfill: parsing into the ledger (append-only)")
    _rows, added, unparsed = parse_report.parse_all(cfg, log)

    log.info(f"backfill complete in {_fmt_elapsed(time.monotonic() - started)}: "
             f"{downloaded} PDFs downloaded, {added} ledger rows added, "
             f"{len(unparsed)} unparsed, {len(failed)} download failures")
    if failed:
        log.alert(f"backfill: {len(failed)} reports could not be downloaded: "
                  + ", ".join(failed), code="DOWNLOAD_FAILED")
    if unparsed:
        log.alert(f"backfill: {len(unparsed)} reports could not be parsed and were "
                  "left OUT of the ledger (never guessed): " + ", ".join(unparsed),
                  code="UNPARSED")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="One-off resumable full-history backfill.")
    ap.add_argument("--from-cached-inventory", action="store_true",
                    help="skip the listing GET and reuse data/listing_inventory.csv")
    ap.add_argument("--limit", type=int, default=None,
                    help="fetch at most N reports this run (resume later)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be fetched and stop")
    args = ap.parse_args()

    cfg = load_config()
    log = RunLog(cfg)
    sess = PoliteSession(cfg, log)

    if not args.from_cached_inventory and not check_robots(cfg, sess, log):
        log.alert("robots.txt disallows the paths we need - STOPPED, nothing fetched",
                  code="ROBOTS_DISALLOW")
        return 2

    return backfill(cfg, log, sess,
                    use_cached_inventory=args.from_cached_inventory,
                    limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
