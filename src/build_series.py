"""Derive the weekly and monthly buyback series and write the workbook.

    buyback_mxn     = remanente_prior + program_addition - remanente_current
    shares_bought   = shares_outstanding_prior - shares_outstanding_current
    avg_price       = buyback_mxn / shares_bought
    pct_outstanding = shares_bought / shares_outstanding_current

program_addition is 0 in normal periods. When AMX tops up the programme the
remanente JUMPS UP and, without the adjustment, the period shows a negative
buyback. Such a rise is NEVER silently absorbed: config/program_additions.yaml
is consulted first, and if the date is absent the daily reports of that week
are downloaded to isolate the exact day, a proposal is written to the config
with confirmed_by_owner: false, and an ALERT is raised.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_reports  # noqa: E402
import parse_report  # noqa: E402
from common import (  # noqa: E402
    CONFIG_DIR,
    PoliteSession,
    RunLog,
    load_config,
    repo_path,
    resolve_date,
)

FRAME_FIELDS = [
    "date", "remanente", "buyback_mxn", "shares_outstanding", "shares_bought",
    "avg_price", "program_addition", "pct_outstanding", "source_report_date", "pdf_url",
]


# --------------------------------------------------------------------------
# program additions
# --------------------------------------------------------------------------
def load_additions() -> list[dict]:
    path = CONFIG_DIR / "program_additions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for a in data.get("additions") or []:
        out.append({**a, "date": resolve_date(a["date"])})
    return sorted(out, key=lambda a: a["date"])


def append_addition(date: dt.date, amount: int, source: str) -> None:
    """Append a proposal. Never rewrites or removes an existing entry."""
    path = CONFIG_DIR / "program_additions.yaml"
    text = path.read_text(encoding="utf-8")
    entry = (f"  - date: {date.isoformat()}\n"
             f"    amount_mxn: {amount}\n"
             f"    source: \"{source}\"\n"
             f"    confirmed_by_owner: false\n")
    # an empty list must become a block sequence before items can be appended
    if re.search(r"^additions:\s*\[\s*\]\s*$", text, re.M):
        text = re.sub(r"^additions:\s*\[\s*\]\s*$", "additions:", text, count=1, flags=re.M)
        path.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")
        return
    path.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")


def addition_in(additions, lo: dt.date, hi: dt.date) -> tuple[int, list[dict]]:
    hits = [a for a in additions if lo < a["date"] <= hi]
    return sum(a["amount_mxn"] for a in hits), hits


def check_duplicate_additions(additions: list[dict], log: RunLog, window_days: int = 45) -> None:
    """A re-probe can propose an addition the config already holds under a
    slightly different date. Two equal unconfirmed amounts close together are
    almost certainly the same top-up counted twice."""
    for i, a in enumerate(additions):
        for b in additions[i + 1:]:
            if (a["amount_mxn"] == b["amount_mxn"]
                    and abs((b["date"] - a["date"]).days) <= window_days
                    and not (a.get("confirmed_by_owner") and b.get("confirmed_by_owner"))):
                log.alert(
                    f"possible DUPLICATE programme addition: {a['amount_mxn']:,} MXN on "
                    f"{a['date']} and on {b['date']} - these would double-count. "
                    "Keep one entry in config/program_additions.yaml.")


# --------------------------------------------------------------------------
# ledger -> rows
# --------------------------------------------------------------------------
def ledger_rows(cfg: dict) -> list[dict]:
    serie = cfg["issuer"]["expected_series"][0]
    inv = {r["report_date"]: r for r in fetch_reports.read_inventory(cfg)}
    rows = []
    for r in parse_report.read_ledger(cfg):
        if r["serie"] != serie:
            continue
        d = dt.date.fromisoformat(r["report_date"])
        rows.append({
            "report_date": d,
            "remanente": int(r["remanente_presente"]),
            "remanente_ultimo": int(r["remanente_ultimo"]),
            "shares_outstanding": int(r["acciones_circulacion_presente"]),
            "shares_outstanding_ultimo": int(r["acciones_circulacion_ultimo"]),
            "pdf_url": r["pdf_url"] or (inv.get(r["report_date"], {}).get("pdf_url", "")),
        })
    rows.sort(key=lambda r: r["report_date"])
    return rows


def _bucket_last(rows: list[dict], keyfn) -> list[dict]:
    buckets: dict = {}
    for r in rows:                       # rows are date-sorted
        buckets[keyfn(r["report_date"])] = r
    return [buckets[k] for k in sorted(buckets)]


# --------------------------------------------------------------------------
# frame construction
# --------------------------------------------------------------------------
def build_frame(anchors: list[dict], additions: list[dict], cfg: dict,
                log: RunLog, probe: bool = True) -> list[dict]:
    frame: list[dict] = []
    for i, r in enumerate(anchors):
        row = {
            "date": r["report_date"],
            "remanente": r["remanente"],
            "shares_outstanding": r["shares_outstanding"],
            "source_report_date": r["report_date"],
            "pdf_url": r["pdf_url"],
            "program_addition": 0,
            "buyback_mxn": None,
            "shares_bought": None,
            "avg_price": None,
            "pct_outstanding": None,
            "is_anchor": i == 0,
        }
        if i == 0:
            frame.append(row)
            continue

        prev = anchors[i - 1]
        add, hits = addition_in(additions, prev["report_date"], r["report_date"])
        buyback = prev["remanente"] + add - r["remanente"]

        if buyback < 0:
            add2 = _handle_unexplained_rise(prev, r, add, cfg, log, probe)
            if add2 is not None:
                additions[:] = load_additions()
                add, hits = addition_in(additions, prev["report_date"], r["report_date"])
                buyback = prev["remanente"] + add - r["remanente"]
            if buyback < 0:
                log.alert(f"{r['report_date']}: remanente rose by "
                          f"{r['remanente'] - prev['remanente'] - add:,} MXN with no known "
                          f"programme addition - buyback left NEGATIVE, not absorbed")

        for h in hits:
            if not h.get("confirmed_by_owner", False):
                log.alert(f"{r['report_date']}: uses UNCONFIRMED programme addition "
                          f"{h['amount_mxn']:,} MXN dated {h['date']} "
                          f"(confirmed_by_owner: false)")

        shares = prev["shares_outstanding"] - r["shares_outstanding"]
        row["program_addition"] = add
        row["buyback_mxn"] = buyback
        row["shares_bought"] = shares
        row["avg_price"] = (buyback / shares) if shares else None
        row["pct_outstanding"] = (shares / r["shares_outstanding"]) if r["shares_outstanding"] else None
        frame.append(row)
    return frame


def _handle_unexplained_rise(prev, cur, known_add, cfg, log, probe) -> int | None:
    """Isolate the day of an unexplained remanente rise and propose an addition."""
    rise = cur["remanente"] + known_add - prev["remanente"]
    log.alert(f"{cur['report_date']}: unexplained remanente rise of "
              f"{cur['remanente'] - prev['remanente'] - known_add:,} MXN since {prev['report_date']}")
    if not probe:
        log.warn("probing disabled (--no-network); no addition proposed")
        return None

    sc = cfg["series"]
    lo = max(prev["report_date"] + dt.timedelta(days=1),
             cur["report_date"] - dt.timedelta(days=sc["jump_probe_days_before"]))
    hi = cur["report_date"] + dt.timedelta(days=sc["jump_probe_days_after"])
    log.info(f"probing DAILY reports {lo}..{hi} to isolate the jump")

    sess = PoliteSession(cfg, log)
    fetch_reports.download_range(cfg, sess, log, lo, hi)
    parse_report.parse_all(cfg, log)

    daily = [r for r in ledger_rows(cfg) if prev["report_date"] <= r["report_date"] <= cur["report_date"]]

    # Within one report, remanente_ultimo -> remanente_presente is pure buyback.
    # So a top-up shows up in the SEAM between reports: it is the difference
    # between yesterday's "al presente" and today's "al ultimo reporte". That
    # isolates the addition EXACTLY, with no rounding.
    jump_day, jump_amt, exact = None, 0, False
    for a, b in zip(daily, daily[1:]):
        seam = b["remanente_ultimo"] - a["remanente"]
        if seam > jump_amt:
            jump_day, jump_amt, exact = b["report_date"], seam, True
    if jump_day is None:                      # seam unusable - fall back
        for a, b in zip(daily, daily[1:]):
            delta = b["remanente"] - a["remanente"]
            if delta > jump_amt:
                jump_day, jump_amt, exact = b["report_date"], delta, False

    if jump_day is None:
        log.alert("probe found no single-day remanente rise - nothing proposed")
        return None

    step = cfg["series"]["addition_round_to_mxn"]
    if exact and jump_amt % step == 0:
        proposed, how = jump_amt, f"exact seam of {jump_amt:,} MXN"
    else:
        proposed = int(round(jump_amt / step) * step)
        how = f"observed rise of {jump_amt:,} MXN rounded to the nearest {step:,}"
    append_addition(jump_day, proposed,
                    f"inferred from {how} on {jump_day} (daily probe); "
                    "AGM resolution not yet confirmed")
    log.alert(f"PROPOSED programme addition {proposed:,} MXN on {jump_day} "
              f"written to config/program_additions.yaml with confirmed_by_owner: false "
              f"- OWNER MUST CONFIRM")
    return proposed


# --------------------------------------------------------------------------
# workbook
# --------------------------------------------------------------------------
def write_workbook(cfg: dict, ledger: list[dict], weekly: list[dict],
                   monthly: list[dict], log: RunLog) -> Path:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    wc = cfg["workbook"]
    cols = wc["monthly_columns"]
    wb = Workbook()

    # ---- Raw --------------------------------------------------------------
    ws = wb.active
    ws.title = wc["sheets"]["raw"]
    ws.append(parse_report.LEDGER_FIELDS)
    numeric = {"remanente_ultimo", "remanente_presente",
               "acciones_tesoreria_ultimo", "acciones_tesoreria_presente",
               "acciones_circulacion_ultimo", "acciones_circulacion_presente"}
    for r in ledger:
        row = []
        for k in parse_report.LEDGER_FIELDS:
            v = r.get(k, "")
            if k in numeric and str(v).strip().lstrip("-").isdigit():
                v = int(v)
            row.append(v)
        ws.append(row)
    for j, k in enumerate(parse_report.LEDGER_FIELDS, start=1):
        if k in numeric:
            for i in range(2, len(ledger) + 2):
                ws.cell(row=i, column=j).number_format = "#,##0"

    # ---- Weekly / Monthly -------------------------------------------------
    def dump(title: str, frame: list[dict]) -> None:
        sh = wb.create_sheet(title)
        sh.append([c["header"] for c in cols])
        for row in frame:
            sh.append([row.get(c["key"]) for c in cols])
        for j, c in enumerate(cols, start=1):
            letter = get_column_letter(j)
            sh.column_dimensions[letter].width = max(12, len(c["header"]) + 2)
            for i in range(2, len(frame) + 2):
                sh.cell(row=i, column=j).number_format = c["number_format"]

    dump(wc["sheets"]["weekly"], weekly)
    dump(wc["sheets"]["monthly"], monthly)

    # ---- YTD --------------------------------------------------------------
    year = max(r["date"].year for r in monthly)
    ytd = [r for r in monthly if r["date"].year == year and not r["is_anchor"]]
    prior = [r for r in monthly if r["date"].year < year]
    base_shares = prior[-1]["shares_outstanding"] if prior else None

    sh = wb.create_sheet(wc["sheets"]["ytd"])
    sh.append(["Month", "Buybacks (MXN mn)", "Buybacks (# Shares mn)",
               "Avg. Buyback Price (MXN)", "% Shares Outstanding"])
    for r in ytd:
        sh.append([r["date"], r["buyback_mxn"], r["shares_bought"], r["avg_price"],
                   (r["shares_bought"] / base_shares) if base_shares else None])

    tot_mxn = sum(r["buyback_mxn"] for r in ytd)
    tot_sh = sum(r["shares_bought"] for r in ytd)
    sh.append(["TOTAL", tot_mxn, tot_sh, (tot_mxn / tot_sh) if tot_sh else None,
               (tot_sh / base_shares) if base_shares else None])
    # shares in millions to 1dp: at 0dp a 24.6mn month would display as "25"
    fmts = ["mmm-yyyy", "#,##0,,", "#,##0.0,,", "#,##0.000", "0.00%"]
    for j, f in enumerate(fmts, start=1):
        sh.column_dimensions[get_column_letter(j)].width = 24
        for i in range(2, len(ytd) + 3):
            sh.cell(row=i, column=j).number_format = f
    sh.cell(row=len(ytd) + 2, column=1).number_format = "General"

    path = repo_path(wc["path"])
    wb.save(path)
    log.info(f"workbook written: {path}")
    log.info(f"YTD {year}: MXN {tot_mxn:,} / {tot_sh:,} shares / avg {tot_mxn / tot_sh:.3f}")
    return path


# --------------------------------------------------------------------------
def build(cfg: dict, log: RunLog, probe: bool = True):
    rows = ledger_rows(cfg)
    if not rows:
        log.alert("ledger is empty - nothing to build, existing data left untouched")
        return [], []
    additions = load_additions()
    check_duplicate_additions(additions, log)
    weekly = build_frame(_bucket_last(rows, lambda d: d.isocalendar()[:2]), additions, cfg, log, probe)
    monthly = build_frame(_bucket_last(rows, lambda d: (d.year, d.month)), additions, cfg, log, probe)
    return weekly, monthly


def main() -> int:
    ap = argparse.ArgumentParser(description="Build weekly/monthly series and the workbook.")
    ap.add_argument("--no-network", action="store_true",
                    help="do not probe daily reports when an unexplained rise is found")
    args = ap.parse_args()

    cfg = load_config()
    log = RunLog(cfg)
    weekly, monthly = build(cfg, log, probe=not args.no_network)
    if not monthly:
        return 1
    write_workbook(cfg, parse_report.read_ledger(cfg), weekly, monthly, log)
    return 1 if log.alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
