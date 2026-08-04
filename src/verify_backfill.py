"""Acceptance test: reproduce the owner's known-correct 2026 table from the
scraped PDFs.

remanente, shares_outstanding, shares_bought and buyback_mxn must match to the
peso / to the share; avg_price to 2dp.

A DATE difference between the owner's table and the actual BMV report date is
reported, not a failure (e.g. 30-May-2026 is a Saturday). A VALUE difference
IS a failure: it is reported with both figures and never papered over.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_series  # noqa: E402
from common import REPO_ROOT, RunLog, load_config, resolve_date  # noqa: E402

EXPECTED = REPO_ROOT / "tests" / "expected_backfill_2026.yaml"


def _fmt(v, price=False):
    if v is None:
        return "-"
    return f"{v:,.2f}" if price else f"{v:,}"


def _match(expected_date: dt.date, monthly: list[dict]):
    """Owner's date -> the actual month-end report row for that month."""
    same = [r for r in monthly if (r["date"].year, r["date"].month) == (expected_date.year, expected_date.month)]
    return same[-1] if same else None


def verify(cfg: dict, log: RunLog) -> int:
    spec = yaml.safe_load(EXPECTED.read_text(encoding="utf-8"))
    tol = spec["tolerance"]
    _, monthly = build_series.build(cfg, log, probe=False)
    if not monthly:
        print("FAIL: no monthly frame built")
        return 1

    failures, date_notes = [], []

    # ---- anchor -----------------------------------------------------------
    a = spec["anchor"]
    a_date = resolve_date(a["date"])
    a_row = _match(a_date, monthly)
    print("=" * 118)
    print("AMX BUYBACK BACKFILL - ACCEPTANCE TEST (scraped BMV PDFs vs owner's table)")
    print("=" * 118)
    hdr = (f"{'expected date':<14}{'report date':<13}{'remanente (MXN)':>20}"
           f"{'buyback (MXN)':>17}{'shares out':>17}{'shares bought':>15}{'avg px':>9}  res")
    print(hdr)
    print("-" * 118)

    def check(label, got, want, tolerance, price=False):
        ok = got is not None and abs(got - want) <= tolerance
        if not ok:
            failures.append((label, got, want))
        return ok

    if a_row is None:
        failures.append(("anchor row missing", None, a["remanente_presente"]))
    else:
        ok_r = check("2025-12 remanente", a_row["remanente"], a["remanente_presente"], tol["remanente_mxn"])
        ok_s = check("2025-12 shares_outstanding", a_row["shares_outstanding"],
                     a["shares_outstanding"], tol["shares_outstanding"])
        if a_row["date"] != a_date:
            date_notes.append((a_date, a_row["date"]))
        print(f"{a_date.isoformat():<14}{a_row['date'].isoformat():<13}"
              f"{_fmt(a_row['remanente']):>20}{'(anchor)':>17}{_fmt(a_row['shares_outstanding']):>17}"
              f"{'(anchor)':>15}{'(anchor)':>9}  {'PASS' if ok_r and ok_s else 'FAIL'}")

    # ---- monthly rows -----------------------------------------------------
    for exp in spec["rows"]:
        d = resolve_date(exp["date"])
        row = _match(d, monthly)
        if row is None:
            failures.append((f"{d} row missing", None, exp["remanente_presente"]))
            print(f"{d.isoformat():<14}{'MISSING':<13}{'':>20}{'':>17}{'':>17}{'':>15}{'':>9}  FAIL")
            continue
        if row["date"] != d:
            date_notes.append((d, row["date"]))

        oks = [
            check(f"{d} remanente", row["remanente"], exp["remanente_presente"], tol["remanente_mxn"]),
            check(f"{d} buyback_mxn", row["buyback_mxn"], exp["buyback_mxn"], tol["buyback_mxn"]),
            check(f"{d} shares_outstanding", row["shares_outstanding"], exp["shares_outstanding"],
                  tol["shares_outstanding"]),
            check(f"{d} shares_bought", row["shares_bought"], exp["shares_bought"], tol["shares_bought"]),
            check(f"{d} avg_price", row["avg_price"], exp["avg_price"], tol["avg_price"]),
        ]
        print(f"{d.isoformat():<14}{row['date'].isoformat():<13}"
              f"{_fmt(row['remanente']):>20}{_fmt(row['buyback_mxn']):>17}"
              f"{_fmt(row['shares_outstanding']):>17}{_fmt(row['shares_bought']):>15}"
              f"{_fmt(row['avg_price'], True):>9}  {'PASS' if all(oks) else 'FAIL'}")

    # ---- YTD --------------------------------------------------------------
    y = spec["ytd_total"]
    year = max(r["date"].year for r in monthly)
    ytd = [r for r in monthly if r["date"].year == year and not r["is_anchor"]]
    tot_mxn = sum(r["buyback_mxn"] for r in ytd)
    tot_sh = sum(r["shares_bought"] for r in ytd)
    avg = tot_mxn / tot_sh if tot_sh else None
    ok = [
        check("YTD buyback_mxn", tot_mxn, y["buyback_mxn"], tol["buyback_mxn"]),
        check("YTD shares_bought", tot_sh, y["shares_bought"], tol["shares_bought"]),
        check("YTD avg_price", avg, y["avg_price"], tol["ytd_avg_price"]),
    ]
    print("-" * 118)
    print(f"{'YTD TOTAL':<27}{'':>20}{_fmt(tot_mxn):>17}{'':>17}{_fmt(tot_sh):>15}"
          f"{avg:>9.3f}  {'PASS' if all(ok) else 'FAIL'}")
    print(f"{'YTD expected':<27}{'':>20}{_fmt(y['buyback_mxn']):>17}{'':>17}"
          f"{_fmt(y['shares_bought']):>15}{y['avg_price']:>9.3f}")
    print("=" * 118)

    if date_notes:
        print("\nDATE DIFFERENCES (reported, not failures):")
        for want, got in date_notes:
            print(f"  owner's table says {want} -> actual BMV report date {got} "
                  f"({got.strftime('%A')}); {want.strftime('%A')} has no report")

    if failures:
        print(f"\nVALUE FAILURES ({len(failures)}):")
        for label, got, want in failures:
            print(f"  {label}: scraped={_fmt(got)} expected={_fmt(want)} diff={_fmt((got - want) if got is not None else None)}")
        print("\nRESULT: FAIL")
        return 1

    print("\nRESULT: PASS - every value reproduced from the scraped BMV PDFs")
    return 0


if __name__ == "__main__":
    cfg = load_config()
    raise SystemExit(verify(cfg, RunLog(cfg)))
