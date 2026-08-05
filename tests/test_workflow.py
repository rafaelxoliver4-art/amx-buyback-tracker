"""The unattended run: the workflow, the schedule, and credential hygiene.

Two things these tests exist to prevent:

  1. The cron drifting. GitHub Actions cannot read config/schedule.yaml, so
     the schedule is duplicated as a literal in the workflow. Duplicated
     values rot; this pins them together.
  2. A credential reaching a log. The password is read from the environment
     and must never be printable, loggable or catchable in an exception
     message.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import send_email  # noqa: E402
from common import load_config  # noqa: E402

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "weekly.yml"
CFG = load_config()
ECFG = load_config("email.yaml")
SCFG = load_config("schedule.yaml")


def _workflow() -> dict:
    if not WORKFLOW.exists():
        pytest.skip("workflow not present")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# the cron must never drift from the config
# --------------------------------------------------------------------------
def test_workflow_cron_matches_schedule_config():
    wf = _workflow()
    # PyYAML parses a bare `on:` key as the boolean True
    triggers = wf.get("on") or wf.get(True)
    crons = [s["cron"] for s in triggers["schedule"]]
    assert crons == [SCFG["cron"]], (
        f"workflow cron {crons} != config/schedule.yaml cron {SCFG['cron']!r} - "
        "these are duplicated by necessity and must be kept in step")


def test_schedule_is_friday_2200_sao_paulo():
    """01:00 UTC Saturday IS 22:00 Friday in Sao Paulo (UTC-3, no DST)."""
    minute, hour, dom, month, dow = SCFG["cron"].split()
    assert (minute, hour) == ("0", "1")
    assert dow == "6" and dom == "*" and month == "*"
    run_utc = dt.datetime(2026, 8, 8, int(hour), int(minute), tzinfo=dt.timezone.utc)
    assert run_utc.weekday() == 5, "cron day 6 must be Saturday in UTC"
    sao = run_utc - dt.timedelta(hours=3)
    assert (sao.weekday(), sao.hour) == (4, 22), \
        f"expected Friday 22:00 Sao Paulo, got {sao:%A %H:%M}"
    # and comfortably after the latest observed BMV filing, 17:59 Mexico City
    latest_filing_utc = dt.datetime(2026, 8, 7, 23, 59, tzinfo=dt.timezone.utc)
    assert run_utc > latest_filing_utc


def test_schedule_is_enabled():
    assert SCFG["enabled"] is True


def test_only_schedule_and_manual_triggers():
    """No push trigger, no pull_request trigger, no second schedule."""
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True)
    assert set(triggers) == {"schedule", "workflow_dispatch"}, \
        f"unexpected triggers: {set(triggers)}"
    assert len(triggers["schedule"]) == 1, "more than one schedule"


def test_workflow_has_write_permission_and_concurrency():
    wf = _workflow()
    assert wf["permissions"]["contents"] == "write"
    assert wf["concurrency"]["group"]
    assert wf["concurrency"]["cancel-in-progress"] is False, \
        "a cancelled run could abandon a half-written ledger commit"


def test_the_gate_is_not_continue_on_error():
    """The acceptance test must be able to fail the job. If it were
    continue-on-error, a wrong number could reach the inbox."""
    steps = _workflow()["jobs"]["run"]["steps"]
    gate = [s for s in steps if "verify_backfill" in str(s.get("run", ""))]
    assert gate, "no verify_backfill step in the workflow"
    for s in gate:
        assert not s.get("continue-on-error"), "the acceptance gate is continue-on-error"


def test_commit_and_email_come_after_the_gate():
    steps = _workflow()["jobs"]["run"]["steps"]
    def idx(pred):
        return next(i for i, s in enumerate(steps) if pred(s))
    gate = idx(lambda s: "verify_backfill" in str(s.get("run", "")))
    commit = idx(lambda s: "git push" in str(s.get("run", "")))
    email = idx(lambda s: "send_email" in str(s.get("run", "")))
    assert gate < commit, "the commit runs before the acceptance gate"
    assert gate < email, "the email runs before the acceptance gate"


def test_workflow_references_secrets_by_name_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "${{ secrets." + ECFG["password_env"] + " }}" in text
    assert "${{ vars." + ECFG["from_env"] + " }}" in text
    # no literal address or password anywhere in the workflow
    assert "@gmail.com" not in text.replace("smtp.gmail.com", "")


# --------------------------------------------------------------------------
# credential hygiene
# --------------------------------------------------------------------------
def test_no_address_password_or_smtp_host_literal_in_python():
    """Config or env, always - never a literal in Python."""
    offenders = []
    for py in (REPO_ROOT / "src").glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pat in (r"smtp\.[a-z0-9.-]+\.[a-z]{2,}", r"[\w.+-]+@[\w-]+\.[a-z]{2,}"):
            for m in re.findall(pat, text):
                if m.endswith("users.noreply.github.com") or "noreply@" in m:
                    continue
                offenders.append(f"{py.name}: {m}")
    assert not offenders, f"literal address/host in Python: {offenders}"


def test_credentials_are_read_from_the_environment_only(monkeypatch):
    monkeypatch.delenv(ECFG["from_env"], raising=False)
    monkeypatch.delenv(ECFG["password_env"], raising=False)
    assert send_email.read_credentials(ECFG) == (None, None)
    assert not send_email.credentials_present(ECFG)

    monkeypatch.setenv(ECFG["from_env"], "someone@example.com")
    monkeypatch.setenv(ECFG["password_env"], "unit-test-secret-value")
    sender, password = send_email.read_credentials(ECFG)
    assert sender == "someone@example.com"
    assert password == "unit-test-secret-value"


def test_the_password_can_never_reach_a_log_stream(monkeypatch, tmp_path):
    """THE test this module exists for.

    Drive a send() failure and assert the secret appears in NO output
    stream - not stdout, not stderr, and not the run log on disk.
    """
    SECRET = "sup3r-s3cret-app-password-xyz"
    log_path = tmp_path / "run_log.txt"

    class _Log:
        def __init__(self):
            self.path = log_path
            self.alerts, self.notices = [], []

        def _write(self, level, msg):
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(f"{level}: {msg}\n")
            print(f"{level}: {msg}")

        def info(self, m):
            self._write("INFO", m)

        def alert(self, m, code="ALERT", affected_date=None):
            self.alerts.append(m)
            self._write("ALERT", m)

    # an SMTP server that rejects the login and echoes the credential back,
    # exactly as a real one can
    class _Boom:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            raise RuntimeError(f"535 auth failed for {user} using {password}")

        def send_message(self, msg):
            pass

    monkeypatch.setattr(send_email.smtplib, "SMTP", _Boom)

    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = "someone@example.com"
    msg["To"] = "someone@example.com"
    msg.set_content("x")

    log = _Log()
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        ok = send_email.send({"email": {**ECFG}}, msg, SECRET, log)

    assert ok is False
    disk = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    for name, stream in (("stdout", out.getvalue()), ("stderr", err.getvalue()),
                         ("run log", disk), ("alerts", " ".join(log.alerts))):
        assert SECRET not in stream, f"THE PASSWORD LEAKED INTO {name}"
    # and the failure is still reported, by exception CLASS
    assert "RuntimeError" in disk


def test_dry_run_needs_no_credentials(monkeypatch):
    monkeypatch.delenv(ECFG["from_env"], raising=False)
    monkeypatch.delenv(ECFG["password_env"], raising=False)
    assert not send_email.credentials_present(ECFG)
    # the preview from the local dry run must exist and carry no secret name
    preview = REPO_ROOT / "output" / "email_preview.html"
    if preview.exists():
        text = preview.read_text(encoding="utf-8")
        assert ECFG["password_env"] not in text
        assert "password" not in text.lower()


# --------------------------------------------------------------------------
# email config shape
# --------------------------------------------------------------------------
def test_email_config_holds_no_credential_values():
    text = (REPO_ROOT / "config" / "email.yaml").read_text(encoding="utf-8")
    assert "password:" not in text.lower().replace("password_env:", "")
    assert ECFG["from_env"] == "FROM_EMAIL"
    assert ECFG["password_env"] == "EMAIL_APP_PASSWORD"
    assert ECFG["enabled"] is True
    assert ECFG["to"] == "rafaelxoliver4@gmail.com"


def test_email_leads_with_the_two_primary_source_figures():
    """The email must show the INPUTS (remanente, shares outstanding) and the
    report they come from, above the derived headline."""
    preview = REPO_ROOT / "output" / "email_preview.html"
    if not preview.exists():
        pytest.skip("no preview; run send_email.py --dry-run")
    h = preview.read_text(encoding="utf-8")
    order = [h.find(s) for s in ("as reported in the", "Remaining resources",
                                 "Shares outstanding", "AMX bought back",
                                 "<img", "YTD (", "routine notice")]
    assert all(i >= 0 for i in order), f"a section is missing: {order}"
    assert order == sorted(order), "email sections are out of order"
    assert "docs-pub/recompra/" in h, "no link to the source PDF"


def test_ytd_header_keeps_its_own_style():
    """Regression: a local variable in the balances block once shadowed the
    YTD table's header style and silently un-bolded it."""
    preview = REPO_ROOT / "output" / "email_preview.html"
    if not preview.exists():
        pytest.skip("no preview")
    h = preview.read_text(encoding="utf-8")
    month_th = re.search(r'<th style="([^"]*)">Month</th>', h)
    assert month_th, "no YTD header row"
    style = month_th.group(1)
    assert "font-weight:bold" in style, "YTD header lost its bold"
    assert "border-bottom" in style, "YTD header lost its rule"


def test_chart_is_embedded_by_cid_not_linked():
    """A linked image will not render in Gmail from a private repo."""
    assert ECFG["body"]["chart_cid"]
    src = (REPO_ROOT / "src" / "send_email.py").read_text(encoding="utf-8")
    assert 'src="cid:' in src
    assert "add_related" in src
