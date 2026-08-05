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
import fetch_reports  # noqa: E402
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
    """Ruling 4: the built frame is gap-free.

    Since the month-boundary split a week may legitimately appear TWICE, so
    the gap test runs over DISTINCT weeks.
    """
    log = _Log()
    weekly, _ = build_series.build(CFG, log, probe=False)
    if not weekly:
        pytest.skip("ledger is empty")
    ends = sorted({r["week_ending_sun"] for r in weekly})
    gaps = [(b - a).days for a, b in zip(ends, ends[1:])]
    assert set(gaps) <= {7}, f"weekly frame has gaps: {sorted(set(gaps))}"


# --------------------------------------------------------------------------
# 2026-08-05 — weekly rows close on month end, and reconcile to Monthly
# --------------------------------------------------------------------------
def test_every_weekly_row_lies_inside_one_calendar_month():
    weekly, _ = _weekly_monthly()
    bad = [r for r in weekly
           if (r["period_start"].year, r["period_start"].month)
           != (r["period_end"].year, r["period_end"].month)]
    assert not bad, f"weekly rows straddling a month: {[str(r['date']) for r in bad[:5]]}"


def test_last_weekly_row_of_each_month_is_the_monthly_report():
    """The guarantee the reconciliation rests on."""
    weekly, monthly = _weekly_monthly()
    monthly_date = {(m["date"].year, m["date"].month): m["date"] for m in monthly}
    last_weekly: dict = {}
    for r in weekly:
        if not r["no_report"]:
            last_weekly[(r["date"].year, r["date"].month)] = r["date"]
    for k, d in last_weekly.items():
        assert d == monthly_date[k], \
            f"{k}: last weekly row ends {d}, Monthly row ends {monthly_date[k]}"


def test_month_end_flag_marks_exactly_the_month_closing_rows():
    weekly, monthly = _weekly_monthly()
    flagged = {r["date"] for r in weekly if r["month_end"]}
    assert flagged == {m["date"] for m in monthly}
    assert not any(r["month_end"] for r in weekly if r["no_report"]), \
        "a no-report row cannot close a month - there is no report"


def test_weekly_reconciles_to_monthly_for_every_month():
    """THE acceptance test for the split: to the peso and to the share."""
    log = _Log()
    weekly, monthly = build_series.build(CFG, log, probe=False)
    if not monthly:
        pytest.skip("ledger is empty")
    rec = build_series.reconcile_weekly_to_monthly(weekly, monthly, log)
    assert rec, "no months reconciled"
    broken = [f"{r['month']}: weekly {r['weekly_mxn']:,} vs monthly {r['monthly_mxn']:,}, "
              f"shares {r['weekly_shares']:,} vs {r['monthly_shares']:,}"
              for r in rec if not r["ok"]]
    assert not broken, "weekly does not reconcile to monthly:\n" + "\n".join(broken)
    assert sum(r["weekly_mxn"] for r in rec) == sum(r["monthly_mxn"] for r in rec)
    assert sum(r["weekly_shares"] for r in rec) == sum(r["monthly_shares"] for r in rec)


def test_a_straddling_week_is_actually_split():
    """Guard against the split silently stopping: a real series must contain
    at least one ISO week appearing twice."""
    weekly, _ = _weekly_monthly()
    real = [r for r in weekly if not r["no_report"]]
    seen: dict = {}
    for r in real:
        seen[r["iso_week"]] = seen.get(r["iso_week"], 0) + 1
    split = {k: v for k, v in seen.items() if v > 1}
    assert split, "no week was split at a month boundary - is the rule still on?"
    for k, v in split.items():
        assert v == 2, f"ISO week {k} produced {v} rows; a month boundary splits it in 2"


def test_current_year_weekly_series_is_complete():
    """Every ISO week from the year's first report to the latest has a row."""
    weekly, _ = _weekly_monthly()
    year = max(r["date"].year for r in weekly)
    rows = [r for r in weekly if r["date"].year == year]
    if len(rows) < 2:
        pytest.skip("not enough rows in the current year")
    ends = sorted({r["week_ending_sun"] for r in rows})
    gaps = [(b - a).days for a, b in zip(ends, ends[1:])]
    assert set(gaps) <= {7}, f"{year} weekly series has a gap: {sorted(set(gaps))}"


def _weekly_monthly():
    log = _Log()
    weekly, monthly = build_series.build(CFG, log, probe=False)
    if not weekly:
        pytest.skip("ledger is empty")
    return weekly, monthly


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
    # ruling 3 (2026-08-05) replaced the previous-run comparison with a ratchet
    assert g["alert_if_fewer_rows_than_high_water"] is True
    assert g["row_count_high_water_file"]
    assert g["revisit_cap_at_rows"] == 5000
    assert "alert_if_fewer_rows_than_previous" not in g, \
        "the superseded previous-run guard is still configured"


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


# --------------------------------------------------------------------------
# 2026-08-05 ruling 1 - the display window is a VIEW, never a deletion
# --------------------------------------------------------------------------
def test_display_filter_trims_the_view():
    frame = _synthetic([dt.date(2025, 12, 31), dt.date(2026, 1, 30), dt.date(2026, 2, 27)])
    cfg = {**CFG, "display": {"start_year": 2026}}
    out = build_series.apply_display_filter(cfg, frame)
    assert [r["date"].year for r in out] == [2026, 2026]


def test_display_filter_is_a_no_op_when_unset():
    frame = _synthetic([dt.date(2025, 12, 31), dt.date(2026, 1, 30)])
    for cfg in ({**CFG, "display": {"start_year": None}}, {k: v for k, v in CFG.items() if k != "display"}):
        assert build_series.apply_display_filter(cfg, frame) == frame


def test_display_filter_never_touches_the_ledger():
    """The whole point of ruling 1: it is a view. Setting start_year must not
    change data/raw_reports.csv by a single row."""
    import parse_report
    path = REPO_ROOT / CFG["paths"]["ledger_csv"]
    before_rows = len(parse_report.read_ledger(CFG))
    before_bytes = path.read_bytes()

    cfg = {**CFG, "display": {"start_year": 2026}}
    log = _Log()
    weekly, monthly = build_series.build(cfg, log, probe=False)
    build_series.apply_display_filter(cfg, weekly)
    build_series.apply_display_filter(cfg, monthly)

    assert len(parse_report.read_ledger(CFG)) == before_rows
    assert path.read_bytes() == before_bytes, "ledger changed under a display filter"


def test_display_filter_does_not_reach_the_acceptance_fixtures():
    """A view must not be able to move a reported figure."""
    log = _Log()
    _w, full = build_series.build(CFG, log, probe=False)
    if not full:
        pytest.skip("ledger is empty")
    cfg = {**CFG, "display": {"start_year": 2026}}
    view = build_series.apply_display_filter(cfg, full)
    by_date = {r["date"]: r for r in full}
    for r in view:
        assert r["buyback_mxn"] == by_date[r["date"]]["buyback_mxn"]
        assert r["shares_bought"] == by_date[r["date"]]["shares_bought"]


# --------------------------------------------------------------------------
# 2026-08-05 ruling 3 - the row-count ratchet
# --------------------------------------------------------------------------
def test_row_count_ratchet_alerts_below_the_high_water_mark(tmp_path):
    cfg = _ratchet_cfg(tmp_path)
    log = _Log()
    fetch_reports.check_row_count_ratchet(cfg, 1255, log)      # sets the mark
    assert not log.alerts
    fetch_reports.check_row_count_ratchet(cfg, 1200, log)      # a shrink
    assert len(log.alerts) == 1
    assert "FEWER" in log.alerts[0]
    # the mark must NOT have been lowered by the shrink
    assert fetch_reports.read_high_water(cfg) == 1255


def test_row_count_ratchet_raises_on_a_new_high(tmp_path):
    cfg = _ratchet_cfg(tmp_path)
    log = _Log()
    fetch_reports.check_row_count_ratchet(cfg, 1255, log)
    fetch_reports.check_row_count_ratchet(cfg, 1300, log)
    assert fetch_reports.read_high_water(cfg) == 1300
    assert not log.alerts


def test_row_count_ratchet_survives_a_shrink_then_alerts_again(tmp_path):
    """The weakness of the previous-run version: one shrink used to become the
    new baseline and the alarm went quiet. It must not."""
    cfg = _ratchet_cfg(tmp_path)
    log = _Log()
    fetch_reports.check_row_count_ratchet(cfg, 1255, log)
    fetch_reports.check_row_count_ratchet(cfg, 1200, log)
    fetch_reports.check_row_count_ratchet(cfg, 1200, log)      # still below
    assert len(log.alerts) == 2, "the ratchet went quiet after one shrink"


def _ratchet_cfg(tmp_path):
    """An absolute path under pytest's tmp_path, so the real
    data/listing_rowcount_highwater.json is never touched and no artefact is
    left in the repo. repo_path() passes an absolute `rel` straight through."""
    p = tmp_path / "hw_test.json"
    return {**CFG, "listing": {**CFG["listing"], "guards": {
        **CFG["listing"]["guards"], "row_count_high_water_file": str(p)}}}


# --------------------------------------------------------------------------
# 2026-08-05 ruling 8 - the programme-reduction guard
# --------------------------------------------------------------------------
def _priced(dates_prices):
    rows = []
    for i, (d, px) in enumerate(dates_prices):
        rows.append({"date": d, "avg_price": px, "buyback_mxn": int((px or 0) * 1_000_000),
                     "shares_bought": 1_000_000 if px else 0, "is_anchor": False})
    return rows


def test_reduction_guard_is_quiet_on_the_real_series():
    """It must not cry wolf on three years of genuine data."""
    log = _Log()
    weekly, monthly = build_series.build(CFG, log, probe=False)
    if not monthly:
        pytest.skip("ledger is empty")
    codes = [n["code"] for n in log.notices
             if n["code"].startswith("IMPLIED_PRICE")]
    assert not codes, f"the price band fires on real data: {codes}"


def test_reduction_guard_catches_a_synthetic_cancellation():
    """A cancellation drains the remanente without retiring shares, so the
    implied price explodes."""
    base = [(dt.date(2026, 1, 5 + i), 16.0) for i in range(10)]
    rows = _priced(base + [(dt.date(2026, 3, 2), 950.0)])   # a 950 MXN "price"
    log = _Log()
    build_series.check_implied_price_band(CFG, rows, "weekly", log)
    assert log.alerts, "a programme reduction went undetected"
    assert any(n["code"] == "IMPLIED_PRICE_BAND" for n in log.notices)


def test_reduction_guard_catches_a_deviation_inside_the_absolute_band():
    """A smaller cancellation stays under max_mxn but still doubles the
    trailing median - the ratio test is the sharp instrument."""
    base = [(dt.date(2026, 1, 5 + i), 16.0) for i in range(10)]
    rows = _priced(base + [(dt.date(2026, 3, 2), 45.0)])
    band = CFG["integrity"]["implied_price_band"]
    assert band["min_mxn"] < 45.0 < band["max_mxn"], "fixture must sit inside the band"
    log = _Log()
    build_series.check_implied_price_band(CFG, rows, "weekly", log)
    assert any(n["code"] == "IMPLIED_PRICE_DEVIATION" for n in log.notices)


def test_reduction_guard_catches_cash_out_with_zero_shares():
    """avg_price is None when no shares move, so the band alone would miss it."""
    rows = [{"date": dt.date(2026, 3, 2), "avg_price": None,
             "buyback_mxn": 5_000_000_000, "shares_bought": 0, "is_anchor": False}]
    log = _Log()
    build_series.check_implied_price_band(CFG, rows, "monthly", log)
    assert any(n["code"] == "IMPLIED_PRICE_NO_SHARES" for n in log.notices)


def test_price_band_is_calibrated_wider_than_everything_observed():
    log = _Log()
    weekly, monthly = build_series.build(CFG, log, probe=False)
    if not monthly:
        pytest.skip("ledger is empty")
    band = CFG["integrity"]["implied_price_band"]
    px = [r["avg_price"] for r in weekly + monthly if r.get("avg_price")]
    assert band["min_mxn"] < min(px), "floor is inside the observed range"
    assert band["max_mxn"] > max(px), "ceiling is inside the observed range"


# --------------------------------------------------------------------------
# 2026-08-05 ruling 9 - chart label density
# --------------------------------------------------------------------------
def test_label_stride_thins_a_long_series_but_keeps_the_extremes():
    dl = CHART["line"]["data_labels"]
    vals = [0.10] + [0.05] * 38 + [0.30, 0.02]        # 41 points, max at 39
    keep = build_chart.label_indices(dl, vals)
    assert len(keep) < len(vals), "a 41-point series was not thinned"
    assert 0 in keep and len(vals) - 1 in keep, "first/last dropped"
    assert vals.index(max(vals)) in keep, "max dropped"
    assert vals.index(min(vals)) in keep, "min dropped"


def test_label_stride_keeps_every_point_on_a_short_series():
    dl = CHART["line"]["data_labels"]
    vals = [0.05 + i / 1000 for i in range(20)]       # under auto_threshold
    assert build_chart.label_indices(dl, vals) == set(range(20))


def test_label_density_config_is_present():
    dl = CHART["line"]["data_labels"]
    assert dl["label_every_n"] == "auto"
    assert dl["auto_threshold"] == 24
    assert set(dl["always_label"]) == {"first", "last", "min", "max"}


def test_cycle0_fixture_is_untouched():
    """Guardrail: the 2026 fixture must not be edited to make anything pass."""
    spec = yaml.safe_load((REPO_ROOT / "tests" / "expected_backfill_2026.yaml")
                          .read_text(encoding="utf-8"))
    assert spec["ytd_total"]["buyback_mxn"] == 5949980905
    assert spec["ytd_total"]["shares_bought"] == 270500000
    assert spec["anchor"]["remanente_presente"] == 12990090502
    assert len(spec["rows"]) == 7
