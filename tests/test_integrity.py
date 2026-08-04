"""Integrity tests across stored reports.

Every recompras PDF carries the PRIOR report's values under "al ultimo
reporte". That is a free check on the previously stored row: wherever two
stored reports are CONSECUTIVE TRADING DAYS, report N's "al ultimo" must
equal report N-1's "al presente".
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import build_series  # noqa: E402
import fetch_reports  # noqa: E402
from common import load_config  # noqa: E402

CFG = load_config()


def _rows():
    rows = build_series.ledger_rows(CFG)
    if not rows:
        pytest.skip("ledger is empty")
    return rows


def _consecutive_trading_pairs(rows):
    """Pairs (a, b) that are adjacent in the BMV listing itself - i.e. no
    published report exists between them."""
    inventory = sorted({r["report_date"] for r in fetch_reports.read_inventory(CFG)})
    order = {d: i for i, d in enumerate(inventory)}
    out = []
    for a, b in zip(rows, rows[1:]):
        ia, ib = order.get(a["report_date"].isoformat()), order.get(b["report_date"].isoformat())
        if ia is not None and ib is not None and ib == ia + 1:
            out.append((a, b))
    return out


def test_there_are_consecutive_pairs_to_check():
    assert _consecutive_trading_pairs(_rows()), "no consecutive-day pairs stored"


def test_shares_outstanding_ultimo_matches_prior_presente():
    mismatches = []
    for a, b in _consecutive_trading_pairs(_rows()):
        if b["shares_outstanding_ultimo"] != a["shares_outstanding"]:
            mismatches.append(
                f"{b['report_date']} al-ultimo={b['shares_outstanding_ultimo']:,} != "
                f"{a['report_date']} al-presente={a['shares_outstanding']:,}")
    assert not mismatches, "shares outstanding chain broken:\n" + "\n".join(mismatches)


def test_remanente_ultimo_matches_prior_presente():
    """Same check on the remanente. A genuine programme top-up lands in this
    seam by design, so a declared addition is an allowed explanation; anything
    else is a real inconsistency."""
    additions = {a["date"]: a["amount_mxn"] for a in build_series.load_additions()}
    known = {
        (dt.date.fromisoformat(str(k["report_date"])), k["diff_mxn"])
        for k in (CFG.get("integrity", {}).get("known_source_discrepancies") or [])
        if k["field"] == "remanente"
    }
    mismatches = []
    for a, b in _consecutive_trading_pairs(_rows()):
        diff = b["remanente_ultimo"] - a["remanente"]
        if diff == 0:
            continue
        if diff == additions.get(b["report_date"]):
            continue          # explained by a declared programme addition
        if (b["report_date"], diff) in known:
            continue          # a BMV defect recorded in config/sources.yaml
        mismatches.append(
            f"{b['report_date']} al-ultimo={b['remanente_ultimo']:,} != "
            f"{a['report_date']} al-presente={a['remanente']:,} (diff {diff:+,} MXN)")
    assert not mismatches, "remanente chain broken:\n" + "\n".join(mismatches)


def test_ledger_has_no_duplicate_report_dates():
    rows = _rows()
    dates = [r["report_date"] for r in rows]
    assert len(dates) == len(set(dates)), "duplicate report_date in the ledger"


def test_ledger_is_only_expected_series():
    import parse_report
    expected = set(CFG["issuer"]["expected_series"])
    seen = {r["serie"] for r in parse_report.read_ledger(CFG)}
    assert seen <= expected, f"unexpected series in ledger: {seen - expected}"


def test_shares_outstanding_is_monotonically_non_increasing():
    """Buybacks only remove shares from circulation. An increase would mean an
    issuance or a data error - either way it must be looked at, not averaged."""
    rises = []
    for a, b in zip(_rows(), _rows()[1:]):
        if b["shares_outstanding"] > a["shares_outstanding"]:
            rises.append(f"{a['report_date']} {a['shares_outstanding']:,} -> "
                         f"{b['report_date']} {b['shares_outstanding']:,}")
    assert not rises, "shares outstanding rose:\n" + "\n".join(rises)


def test_every_ledger_row_has_provenance():
    import parse_report
    bad = [r["report_date"] for r in parse_report.read_ledger(CFG)
           if not r["pdf_url"] or not r["pdf_sha256"]]
    assert not bad, f"ledger rows missing pdf_url/sha256: {bad}"
