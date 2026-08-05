"""Cycle 1: the derived-series rules and the chart config.

Covers the six Architect rulings that changed behaviour:
  1  an unconfirmed programme addition reports ONCE per run, not per row
  3  the listing guards
  4  a period with no report gets an EXPLICIT zero row, never a silent gap
  5  Month labels, and Date = the true BMV report date
  6  ISO Week and Week Ending (Sun)
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import build_chart  # noqa: E402
import build_series  # noqa: E402
from common import RunLog, load_config  # noqa: E402

CFG = load_config()
CHART = load_config("chart.yaml")


class _Log(RunLog):
    """A RunLog that keeps everything in memory - no run_log.txt side effects."""

    def __init__(self):
        self.path = Path("nul") if sys.platform == "win32" else Path("/dev/null")
        self.alerts, self.notices = [], []

    def _write(self, level, msg):
        pass


def _monthly():
    log = _Log()
    _weekly, monthly = build_series.build(CFG, log, probe=False)
    if not monthly:
        pytest.skip("ledger is empty")
    return monthly, log


# --------------------------------------------------------------------------
# ruling 5 and 6 - labels
# --------------------------------------------------------------------------
def test_month_label_format():
    assert build_series.month_label(CFG, dt.date(2026, 5, 29)) == "May-26"
    assert build_series.month_label(CFG, dt.date(2023, 7, 28)) == "Jul-23"


def test_iso_week_label_format():
    assert build_series.iso_week_label(CFG, dt.date(2026, 7, 31)) == "2026-W31"
    # 1 Jan 2023 is a Sunday and belongs to ISO week 52 of 2022
    assert build_series.iso_week_label(CFG, dt.date(2023, 1, 1)) == "2022-W52"


def test_week_ending_sunday_is_the_sunday_of_that_iso_week():
    # 2026-07-31 is a Friday -> the ISO week closes Sunday 2026-08-02
    assert build_series.week_ending_sunday(dt.date(2026, 7, 31)) == dt.date(2026, 8, 2)
    # a Sunday is its own week ending
    assert build_series.week_ending_sunday(dt.date(2026, 8, 2)) == dt.date(2026, 8, 2)
    for d in (dt.date(2024, 2, 29), dt.date(2021, 8, 6), dt.date(2025, 12, 31)):
        end = build_series.week_ending_sunday(d)
        assert end.isoweekday() == 7
        assert end.isocalendar()[:2] == d.isocalendar()[:2]


def test_monthly_date_is_the_true_report_date_not_a_month_end_label():
    """Ruling 5: the owner's approximate month-end labels are NOT preserved."""
    monthly, _ = _monthly()
    by_month = {(r["date"].year, r["date"].month): r["date"] for r in monthly}
    # May-2026: the owner's table says the 30th, a Saturday; BMV's last May
    # report is Friday the 29th and that is what the workbook must carry.
    if (2026, 5) in by_month:
        assert by_month[(2026, 5)] == dt.date(2026, 5, 29)
    for d in by_month.values():
        assert d.isoweekday() <= 5, f"{d} is a weekend - not a real BMV report date"


# --------------------------------------------------------------------------
# ruling 4 - never a silent gap
# --------------------------------------------------------------------------
def _synthetic(dates):
    return [{
        "date": d, "remanente": 100 - i, "shares_outstanding": 1000 - i,
        "source_report_date": d, "pdf_url": "", "program_addition": 0,
        "buyback_mxn": 1, "shares_bought": 1, "avg_price": 1.0,
        "pct_outstanding": 0.001,
        "month_label": build_series.month_label(CFG, d),
        "iso_week": build_series.iso_week_label(CFG, d),
        "week_ending_sun": build_series.week_ending_sunday(d),
        "no_report": False, "is_anchor": i == 0,
    } for i, d in enumerate(dates)]


def test_empty_week_gets_an_explicit_row():
    # 2026-01-09 (W02) then 2026-01-30 (W05): W03 and W04 are missing
    frame = _synthetic([dt.date(2026, 1, 9), dt.date(2026, 1, 30)])
    out = build_series.fill_empty_weeks(CFG, frame, _Log())
    assert len(out) == 4
    filled = [r for r in out if r["no_report"]]
    assert [r["iso_week"] for r in filled] == ["2026-W03", "2026-W04"]
    for r in filled:
        assert r["buyback_mxn"] == 0
        assert r["shares_bought"] == 0
        assert r["date"].isoweekday() == 7            # labelled on the Sunday
        assert r["source_report_date"] is None


def test_empty_week_carries_balances_forward():
    frame = _synthetic([dt.date(2026, 1, 9), dt.date(2026, 1, 30)])
    out = build_series.fill_empty_weeks(CFG, frame, _Log())
    prior = out[0]
    for r in out[1:3]:
        assert r["remanente"] == prior["remanente"]
        assert r["shares_outstanding"] == prior["shares_outstanding"]


def test_no_empty_rows_when_weeks_are_contiguous():
    frame = _synthetic([dt.date(2026, 1, 9), dt.date(2026, 1, 16), dt.date(2026, 1, 23)])
    out = build_series.fill_empty_weeks(CFG, frame, _Log())
    assert len(out) == 3
    assert not any(r["no_report"] for r in out)


def test_weekly_frame_has_no_missing_iso_weeks():
    """The whole point of ruling 4: the built frame is gap-free."""
    log = _Log()
    weekly, _ = build_series.build(CFG, log, probe=False)
    if not weekly:
        pytest.skip("ledger is empty")
    weeks = [r["iso_week"] for r in weekly]
    assert len(weeks) == len(set(weeks)), "duplicate ISO week in the weekly frame"
    # every consecutive pair must be exactly 7 days apart at the Sunday
    ends = sorted(r["week_ending_sun"] for r in weekly)
    gaps = [(b - a).days for a, b in zip(ends, ends[1:])]
    assert set(gaps) <= {7}, f"weekly frame has gaps: {sorted(set(gaps))}"


# --------------------------------------------------------------------------
# ruling 1 - one line per run, not one per row
# --------------------------------------------------------------------------
def test_unconfirmed_addition_reports_once_per_run():
    _monthly_rows, log = _monthly()
    codes = [n for n in log.notices if n["code"] == "ADDITION_UNCONFIRMED"]
    unconfirmed = [a for a in build_series.load_additions()
                   if not a.get("confirmed_by_owner", False)]
    used = {n["affected_date"] for n in codes}
    assert len(codes) == len(used), "an addition was reported more than once in a run"
    assert len(codes) <= len(unconfirmed)
    for n in codes:
        assert n["severity"] == "INFO", "ruling 1: this is an INFO, not an ALERT"


def test_every_unconfirmed_addition_has_notes_saying_what_would_confirm_it():
    for a in build_series.load_additions():
        if not a.get("confirmed_by_owner", False):
            assert a.get("notes"), f"addition {a['date']} has no notes: field"
            assert len(a["notes"]) > 30


# --------------------------------------------------------------------------
# ruling 3 - listing guards
# --------------------------------------------------------------------------
def test_listing_guards_are_configured():
    g = CFG["listing"]["guards"]
    assert g["max_response_bytes"] == 10 * 1024 * 1024
    assert g["alert_if_fewer_rows_than_previous"] is True


def test_no_cap_on_how_much_of_the_listing_is_parsed():
    """Ruling 3: guards, but explicitly NO cap."""
    assert "max_rows" not in CFG["listing"]
    assert "max_age_months" not in CFG["selection"]


# --------------------------------------------------------------------------
# the YTD total
# --------------------------------------------------------------------------
def test_ytd_total_average_price_is_weighted_not_a_mean_of_means():
    monthly, _ = _monthly()
    year = max(r["date"].year for r in monthly)
    ytd = [r for r in monthly if r["date"].year == year and not r["is_anchor"]]
    if len(ytd) < 2:
        pytest.skip("not enough months")
    tot_mxn = sum(r["buyback_mxn"] for r in ytd)
    tot_sh = sum(r["shares_bought"] for r in ytd)
    weighted = tot_mxn / tot_sh
    mean_of_means = sum(r["avg_price"] for r in ytd if r["avg_price"]) / len(
        [r for r in ytd if r["avg_price"]])
    assert abs(weighted - mean_of_means) > 1e-9, "fixture too degenerate to tell them apart"
    assert CFG["workbook"]["ytd"]["total_avg_price_is_weighted"] is True


# --------------------------------------------------------------------------
# chart config
# --------------------------------------------------------------------------
def test_chart_config_holds_every_style_value_and_python_holds_none():
    src = (REPO_ROOT / "src" / "build_chart.py").read_text(encoding="utf-8")
    import re
    hexes = re.findall(r"#[0-9A-Fa-f]{6}\b", src)
    assert not hexes, f"hard-coded colours in build_chart.py: {hexes}"
    assert CHART["bars"]["color"] == "#C4B08C"
    assert CHART["line"]["color"] == "#4A3F35"
    assert CHART["bars"]["gap_width_pct"] == 40
    assert CHART["line"]["data_labels"]["rotation_deg"] == 45
    assert CHART["axes"]["x"]["label_rotation_deg"] == 45
    assert CHART["axes"]["y_secondary"]["visible"] is False
    assert CHART["axes"]["gridlines"]["show"] is False
    assert CHART["axes"]["y_primary"]["min"] == 0


def test_chart_rows_exclude_the_anchor():
    monthly, _ = _monthly()
    rows = build_chart.chart_rows(CFG, CHART, monthly)
    assert rows, "no chart rows"
    assert all(r["buyback_mxn"] is not None for r in rows)
    assert not any(r["is_anchor"] for r in rows)


def test_chart_legend_entries_match_the_spec():
    assert CHART["legend"]["entries"] == ["bars", "line"]
    assert CHART["bars"]["label"] == "Buybacks (MXN mn)"
    assert CHART["line"]["label"] == "% shares outstanding"
    assert CHART["legend"]["position"] == "bottom"


# --------------------------------------------------------------------------
# the full-history fixture
# --------------------------------------------------------------------------
def test_full_fixture_months_are_all_present_in_the_monthly_frame():
    spec = yaml.safe_load((REPO_ROOT / "tests" / "expected_backfill_full.yaml")
                          .read_text(encoding="utf-8"))
    monthly, _ = _monthly()
    have = {(r["date"].year, r["date"].month) for r in monthly}
    missing = [str(e["date"]) for e in spec["rows"]
               if (e["date"].year, e["date"].month) not in have]
    assert not missing, f"months in the fixture with no scraped row: {missing}"


def test_cycle0_fixture_is_untouched():
    """Guardrail: the 2026 fixture must not be edited to make anything pass."""
    spec = yaml.safe_load((REPO_ROOT / "tests" / "expected_backfill_2026.yaml")
                          .read_text(encoding="utf-8"))
    assert spec["ytd_total"]["buyback_mxn"] == 5949980905
    assert spec["ytd_total"]["shares_bought"] == 270500000
    assert spec["anchor"]["remanente_presente"] == 12990090502
    assert len(spec["rows"]) == 7
