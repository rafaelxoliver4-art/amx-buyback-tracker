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
EXPECTED_FULL = REPO_ROOT / "tests" / "expected_backfill_full.yaml"


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
    # Scope the YTD to the months the fixture covers. This is an acceptance
    # test against a fixed known-correct table, so it must stay reproducible
    # as new months arrive; months beyond the fixture are reported, not summed.
    y = spec["ytd_total"]
    want_months = {(resolve_date(e["date"]).year, resolve_date(e["date"]).month) for e in spec["rows"]}
    year = max(m[0] for m in want_months)
    ytd = [r for r in monthly
           if not r["is_anchor"] and (r["date"].year, r["date"].month) in want_months]
    extra = [r for r in monthly
             if not r["is_anchor"] and r["date"].year == year
             and (r["date"].year, r["date"].month) not in want_months]
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

    if extra:
        print("\nMONTHS BEYOND THE FIXTURE (excluded from the YTD check, reported only):")
        for r in extra:
            print(f"  {r['date']}  buyback {_fmt(r['buyback_mxn'])} MXN  "
                  f"{_fmt(r['shares_bought'])} shares  avg {_fmt(r['avg_price'], True)}")

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


# --------------------------------------------------------------------------
# Cycle 1: the full-history table, May-2023 .. Dec-2025
# --------------------------------------------------------------------------
def verify_full(cfg: dict, log: RunLog) -> int:
    """Reproduce the owner's May-2023..Dec-2025 table from the scraped PDFs.

    This test is run ON THE OWNER'S OWN DATES, straight off the ledger, not
    off the shipped monthly frame. The shipped frame uses month-end reports
    (ruling 5) while the owner's early-2023 rows do not, and that difference
    is a DATE convention - comparing across it would confuse a date question
    with a value question. Deriving each period from the previous fixture
    row's own report isolates genuine value differences.

    The owner's buyback column is rounded to MXN mn, so column C is compared
    at mn precision. Everything else is compared exactly.

    Where the two disagree the SCRAPED figure is authoritative. Differences
    already investigated against the PDFs are declared individually in the
    fixture under known_owner_table_discrepancies - never a blanket
    tolerance, so any NEW difference still fails.
    """
    spec = yaml.safe_load(EXPECTED_FULL.read_text(encoding="utf-8"))
    tol = spec["tolerance"]
    corrections = {str(k): str(v) for k, v in (spec.get("date_corrections") or {}).items()}
    known = {(str(k["date"]), k["field"]): k
             for k in (spec.get("known_owner_table_discrepancies") or [])}

    ledger = {r["report_date"].isoformat(): {**r, "report_date": r["report_date"].isoformat()}
              for r in build_series.ledger_rows(cfg)}
    if not ledger:
        print("FAIL: ledger is empty")
        return 1

    failures, known_hits, date_notes, missing = [], [], [], []

    print()
    print("=" * 134)
    print("FULL-HISTORY ACCEPTANCE TEST - owner's table May-2023..Dec-2025 vs scraped BMV PDFs")
    print("(measured on the owner's own dates; each period derives from the previous fixture row)")
    print("=" * 134)
    print(f"{'owner date':<13}{'report used':<13}{'remanente (MXN)':>19}"
          f"{'buyback mn':>12}{'exp':>7}{'shares out':>17}{'shares bought':>15}"
          f"{'avg px':>8}{'exp':>7}  res")
    print("-" * 134)

    a = spec["anchor"]
    prev_key = corrections.get(str(a["date"]), str(a["date"]))
    prev = ledger.get(prev_key)
    if prev is None:
        print(f"FAIL: anchor report {prev_key} is not in the ledger")
        return 1
    additions = build_series.load_additions()

    for exp in spec["rows"]:
        owner_date = str(exp["date"])
        used = corrections.get(owner_date, owner_date)
        row = ledger.get(used)
        if row is None:
            missing.append((owner_date, used))
            print(f"{owner_date:<13}{'NOT HELD':<13}{'':>19}{'':>12}{'':>7}{'':>17}{'':>15}{'':>8}{'':>7}  FAIL")
            failures.append((f"{owner_date} report not held", None, None))
            continue
        if used != owner_date:
            date_notes.append((owner_date, used))

        add, _hits = build_series.addition_in(
            additions, dt.date.fromisoformat(prev["report_date"]), dt.date.fromisoformat(used))
        buyback = prev["remanente"] + add - row["remanente"]
        bought = prev["shares_outstanding"] - row["shares_outstanding"]
        avg = (buyback / bought) if bought else None
        got_mn = buyback / 1_000_000

        oks = []
        for name, got, want, t in (
            ("buybacks_mxn_mn", round(got_mn), exp["buybacks_mxn_mn"], tol["buyback_mxn_mn"]),
            ("remaining_resources_mxn", row["remanente"], exp["remaining_resources_mxn"], tol["remanente_mxn"]),
            ("shares_outstanding", row["shares_outstanding"], exp["shares_outstanding"], tol["shares_outstanding"]),
            ("buybacks_shares", bought, exp["buybacks_shares"], tol["shares_bought"]),
            ("avg_price", avg, exp["avg_price"], tol["avg_price"]),
        ):
            ok = got is not None and abs(got - want) <= t
            if not ok:
                k = known.get((owner_date, name))
                if k is not None and abs(got - k["scraped"]) <= t:
                    known_hits.append((owner_date, name, k, got))
                    ok = True          # a DECLARED owner-table error, not a new break
                else:
                    failures.append((f"{owner_date} {name}", got, want))
            oks.append(ok)

        mark = "PASS" if all(oks) else "FAIL"
        if any((owner_date, n) in known for n in
               ("buybacks_mxn_mn", "remaining_resources_mxn", "shares_outstanding",
                "buybacks_shares", "avg_price")) and all(oks):
            mark = "PASS*"
        print(f"{owner_date:<13}{used:<13}{_fmt(row['remanente']):>19}"
              f"{got_mn:>12,.0f}{exp['buybacks_mxn_mn']:>7,}"
              f"{_fmt(row['shares_outstanding']):>17}{_fmt(bought):>15}"
              f"{_fmt(avg, True):>8}{exp['avg_price']:>7.2f}  {mark}")
        prev = row
    print("=" * 134)

    if date_notes:
        print("\nDATE DIFFERENCES (reported, not failures - the workbook carries the true report date):")
        for owner_date, used in date_notes:
            print(f"  owner's table says {owner_date} -> the figures are the {used} report's")

    if known_hits:
        print(f"\nDECLARED ERRORS IN THE OWNER'S TABLE ({len(known_hits)}) - "
              "scrape is authoritative, each declared individually in the fixture:")
        for owner_date, name, k, got in known_hits:
            print(f"  {owner_date} {name}: owner={_fmt(k['owner'])} scraped={_fmt(got)} "
                  f"diff={_fmt(got - k['owner'])}")
            print(f"      {' '.join(k['note'].split())}")

    if failures:
        print(f"\nVALUE FAILURES ({len(failures)}):")
        for label, got, want in failures:
            diff = (got - want) if (got is not None and want is not None) else None
            print(f"  {label}: scraped={_fmt(got)} expected={_fmt(want)} diff={_fmt(diff)}")
        print("\nRESULT (full history): FAIL")
        return 1

    print(f"\nRESULT (full history): PASS - {len(spec['rows'])} rows reproduced from the "
          f"scraped BMV PDFs ({len(known_hits)} marked * where the owner's table is "
          "provably wrong and the scrape is authoritative)")
    return 0


if __name__ == "__main__":
    cfg = load_config()
    _log = RunLog(cfg)
    rc_2026 = verify(cfg, _log)
    rc_full = verify_full(cfg, _log)
    print()
    print(f"OVERALL: 2026 fixture {'PASS' if rc_2026 == 0 else 'FAIL'}; "
          f"full-history fixture {'PASS' if rc_full == 0 else 'FAIL'}")
    raise SystemExit(rc_2026 or rc_full)
