"""Parse a BMV "Adquisicion de Acciones por Emisora (Recompras)" PDF.

We need exactly two "al presente" figures per report:
    * REMANENTE DE RECURSOS -> Al presente
    * SALDOS -> Al presente reporte -> Acciones en Circulacion
Everything in the workbook is derived from those two. The rest is captured
for integrity checking, not for arithmetic.

THE OVERLAPPING-RENDER PROBLEM
------------------------------
On the "Al presente reporte" row BMV draws some cells TWICE: the correct
value, and a ghost of the previous report's value offset ~10pt to the right.
Naive text extraction concatenates the two by x order and yields garbage:

    Al presente reporte 177,000,000 595,999,939,060,000,000,0000 0 0

Character-level x-chaining separates them cleanly, because each render is
internally contiguous (every char's x0 equals the previous char's x1):

    run A  x0=325.50  ->  59,993,000,000     (correct, column-aligned)
    run B  x0=335.50  ->  59,996,000,000     (ghost of "al ultimo")

Ambiguity is then resolved by the conservation identity
    delta(tesoreria) == -delta(circulacion)
and only if that fails, by x-alignment with the unambiguous row. If neither
resolves it the report is reported UNPARSED. A number is never guessed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    RunLog,
    fold,
    load_config,
    parse_number,
    repo_path,
    sha256_bytes,
)

LEDGER_FIELDS = [
    "report_date", "published_at", "serie", "casa_de_bolsa",
    "remanente_ultimo", "remanente_presente",
    "acciones_tesoreria_ultimo", "acciones_tesoreria_presente",
    "acciones_circulacion_ultimo", "acciones_circulacion_presente",
    "pdf_url", "pdf_sha256", "fetched_at_utc",
]


class ParseError(Exception):
    """Raised when a report cannot be parsed without guessing."""


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
class Line:
    __slots__ = ("page", "top", "chars", "runs", "text")

    def __init__(self, page: int, top: float, chars: list[dict], join_tol: float):
        self.page = page
        self.top = top
        self.chars = sorted(chars, key=lambda c: (c["x0"], c["x1"]))
        self.runs = _build_runs(self.chars, join_tol)
        # reading text = runs left to right; good enough for label matching
        self.text = " ".join(r["text"] for r in self.runs)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Line p{self.page} top={self.top:.1f} {self.text[:70]!r}>"


def _build_runs(chars: list[dict], join_tol: float) -> list[dict]:
    """Split one text line into maximally x-contiguous runs.

    Two renders overlaid on the same cell interleave when sorted by x, but
    each is internally contiguous, so following x1 -> x0 links recovers both.
    """
    n = len(chars)
    used = [False] * n
    runs: list[dict] = []
    for i in range(n):
        if used[i]:
            continue
        used[i] = True
        members = [chars[i]]
        cur = chars[i]
        while True:
            nxt = None
            for j in range(i + 1, n):
                if used[j]:
                    continue
                if abs(chars[j]["x0"] - cur["x1"]) <= join_tol:
                    nxt = j
                    break
            if nxt is None:
                break
            used[nxt] = True
            members.append(chars[nxt])
            cur = chars[nxt]
        text = "".join(m["text"] for m in members)
        runs.append({
            "text": text.strip(),
            "raw": text,
            "x0": members[0]["x0"],
            "x1": members[-1]["x1"],
            "chars": members,
        })
    runs.sort(key=lambda r: r["x0"])
    return [r for r in runs if r["text"]]


def extract_lines(pdf_path: Path, cfg: dict) -> list[Line]:
    g = cfg["parse"]["geometry"]
    line_tol = g["line_tolerance_pt"]
    join_tol = g["run_join_tolerance_pt"]
    lines: list[Line] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            buckets: list[tuple[float, list[dict]]] = []
            for ch in sorted(page.chars, key=lambda c: c["top"]):
                for top, group in buckets:
                    if abs(ch["top"] - top) <= line_tol:
                        group.append(ch)
                        break
                else:
                    buckets.append((ch["top"], [ch]))
            for top, group in buckets:
                lines.append(Line(pno, top, group, join_tol))
    lines.sort(key=lambda ln: (ln.page, ln.top))
    return lines


def _label_span(line: Line, label: str):
    """x-span of `label` inside a line, matched on folded text. None if absent."""
    want = fold(label)
    if not want:
        return None
    # Build a folded string plus a map back to the contributing chars.
    pieces, owners = [], []
    for ch in line.chars:
        f = fold(ch["text"])
        if not f:
            f = " "
        pieces.append(f)
        owners.extend([ch] * len(f))
    hay = "".join(pieces)
    hay = " ".join(hay.split()) if False else hay  # keep index alignment
    idx = hay.find(want)
    if idx < 0:
        # tolerate runs of whitespace inside the line
        squeezed = re.sub(r"\s+", " ", hay)
        if re.sub(r"\s+", " ", want) not in squeezed:
            return None
        pattern = r"\s+".join(re.escape(t) for t in want.split())
        m = re.search(pattern, hay)
        if not m:
            return None
        idx, end = m.start(), m.end()
    else:
        end = idx + len(want)
    span = owners[idx:end]
    return (min(c["x0"] for c in span), max(c["x1"] for c in span))


def _has_label(line: Line, label: str) -> bool:
    return _label_span(line, label) is not None


def _numeric_runs(line: Line) -> list[dict]:
    out = []
    for r in line.runs:
        v = parse_number(r["text"])
        if v is not None:
            out.append({**r, "value": v})
    return out


def _runs_in_band(runs: list[dict], band, min_overlap: float) -> list[dict]:
    """Runs whose horizontal midpoint falls inside the band.

    Midpoint, not overlap-with-the-header-label: values are right-aligned in
    their column and a short value (e.g. a bare "0") can sit entirely to the
    right of its own header text.
    """
    lo, hi = band
    return [r for r in runs if lo <= (r["x0"] + r["x1"]) / 2.0 < hi]


def _column_bands(header: Line, cols: dict) -> dict:
    """Turn header label spans into contiguous bands split at the midpoints."""
    spans = {}
    for key, label in cols.items():
        span = _label_span(header, label)
        if span is None:
            raise ParseError(f"SALDOS column {label!r} not found")
        spans[key] = span
    order = sorted(spans, key=lambda k: spans[k][0])
    bands, n = {}, len(order)
    for i, key in enumerate(order):
        lo = float("-inf") if i == 0 else (spans[order[i - 1]][1] + spans[key][0]) / 2.0
        hi = float("inf") if i == n - 1 else (spans[key][1] + spans[order[i + 1]][0]) / 2.0
        bands[key] = (lo, hi)
    return bands


# --------------------------------------------------------------------------
# report parsing
# --------------------------------------------------------------------------
def _find_line(lines, label, start=0, end=None):
    for i in range(start, end if end is not None else len(lines)):
        if _has_label(lines[i], label):
            return i
    return -1


def _value_after_label(line: Line, label: str):
    span = _label_span(line, label)
    if span is None:
        return None
    rest = [r for r in line.runs if r["x0"] >= span[1] - 0.5]
    return " ".join(r["text"] for r in rest).strip() or None


def _date_after_label(line: Line, label: str):
    txt = _value_after_label(line, label) or ""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", txt)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    return dt.date(y, mo, d)


def _pick_single(cands: list[dict], what: str, warnings: list[str]):
    if len(cands) == 1:
        return cands[0]["value"], cands
    if not cands:
        raise ParseError(f"no value found for {what}")
    warnings.append(f"{what}: {len(cands)} overlapping renders {[c['text'] for c in cands]}")
    return None, cands


def parse_pdf(pdf_path: Path, cfg: dict) -> dict:
    pc = cfg["parse"]
    min_ov = pc["geometry"]["column_overlap_min_pt"]
    lines = extract_lines(Path(pdf_path), cfg)
    warnings: list[str] = []

    out: dict = {"warnings": warnings, "series": []}

    # ---- header -----------------------------------------------------------
    hl = pc["header_labels"]
    for key, label in (("clave", "clave_cotizacion"), ("razon_social", "razon_social")):
        i = _find_line(lines, hl[label])
        out[key] = _value_after_label(lines[i], hl[label]) if i >= 0 else None
    i = _find_line(lines, hl["fecha_operacion"])
    out["fecha_operacion"] = _date_after_label(lines[i], hl["fecha_operacion"]) if i >= 0 else None
    i = _find_line(lines, hl["fecha_documento"])
    out["fecha_documento"] = _date_after_label(lines[i], hl["fecha_documento"]) if i >= 0 else None

    # ---- remanente de recursos (report level, one per PDF) ----------------
    rc = pc["remanente"]
    i_sec = _find_line(lines, rc["section"])
    if i_sec < 0:
        raise ParseError("REMANENTE DE RECURSOS section not found")
    i_ser = _find_line(lines, pc["serie"]["block_heading"], i_sec)
    stop = i_ser if i_ser > 0 else len(lines)

    for key, label in (("remanente_ultimo", rc["row_ultimo"]),
                       ("remanente_presente", rc["row_presente"])):
        idx = _find_line(lines, label, i_sec + 1, stop)
        if idx < 0:
            raise ParseError(f"REMANENTE row {label!r} not found")
        span = _label_span(lines[idx], label)
        cands = [r for r in _numeric_runs(lines[idx]) if r["x0"] >= span[1] - 0.5]
        val, all_c = _pick_single(cands, key, warnings)
        out[key] = val
        out[f"_{key}_cands"] = all_c

    # remanente ambiguity -> resolve by x-alignment against the clean row
    _resolve_pair_by_alignment(out, "remanente_ultimo", "remanente_presente", warnings)
    for key in ("remanente_ultimo", "remanente_presente"):
        if out[key] is None:
            raise ParseError(f"could not resolve {key} between overlapping renders")

    # ---- one block per SERIE ---------------------------------------------
    sc = pc["serie"]
    serie_idx = [i for i in range(i_ser + 1 if i_ser >= 0 else 0, len(lines))
                 if re.fullmatch(r"serie\s+[a-z0-9\-\.]+", fold(lines[i].text))]
    if not serie_idx:
        raise ParseError("no SERIE block found")

    for n, start in enumerate(serie_idx):
        end = serie_idx[n + 1] if n + 1 < len(serie_idx) else len(lines)
        out["series"].append(_parse_serie_block(lines, start, end, cfg, min_ov, warnings))

    # ---- comentarios ------------------------------------------------------
    i_com = _find_line(lines, pc["operaciones"]["comentarios_label"])
    out["comentarios"] = (_value_after_label(lines[i_com], pc["operaciones"]["comentarios_label"])
                          if i_com >= 0 else None)
    return out


def _resolve_pair_by_alignment(holder: dict, key_a: str, key_b: str, warnings: list[str]) -> None:
    """If one of two sibling rows is ambiguous, align it on the clean one's x0."""
    for amb, clean in ((key_a, key_b), (key_b, key_a)):
        if holder.get(amb) is not None or holder.get(clean) is None:
            continue
        cands = holder.get(f"_{amb}_cands") or []
        ref = holder.get(f"_{clean}_cands") or []
        if not cands or len(ref) != 1:
            continue
        best = min(cands, key=lambda c: abs(c["x0"] - ref[0]["x0"]))
        holder[amb] = best["value"]
        warnings.append(f"{amb}: resolved by x-alignment -> {best['text']}")


def _parse_serie_block(lines, start, end, cfg, min_ov, warnings) -> dict:
    pc = cfg["parse"]
    sc, sal = pc["serie"], pc["saldos"]
    blk: dict = {"serie": lines[start].text.split()[-1]}

    i_casa = _find_line(lines, sc["casa_de_bolsa_label"], start, end)
    blk["casa_de_bolsa"] = (_value_after_label(lines[i_casa], sc["casa_de_bolsa_label"])
                            if i_casa >= 0 else None)

    i_sal = _find_line(lines, sal["section"], start, end)
    if i_sal < 0:
        raise ParseError(f"SALDOS section not found for serie {blk['serie']}")

    # column bands come from the header line, which is the first line after
    # SALDOS carrying the tesoreria label
    cols = sal["columns"]
    i_hdr = _find_line(lines, cols["acciones_tesoreria"], i_sal, end)
    if i_hdr < 0:
        raise ParseError(f"SALDOS column header not found for serie {blk['serie']}")
    bands = _column_bands(lines[i_hdr], cols)

    rows = {}
    for suffix, label in (("ultimo", sal["row_ultimo"]), ("presente", sal["row_presente"])):
        idx = _find_line(lines, label, i_hdr, end)
        if idx < 0:
            raise ParseError(f"SALDOS row {label!r} not found")
        rows[suffix] = idx

    cand: dict[str, list[dict]] = {}
    for suffix, idx in rows.items():
        nums = _numeric_runs(lines[idx])
        for key in cols:
            cand[f"{key}_{suffix}"] = _runs_in_band(nums, bands[key], min_ov)

    for key, cs in cand.items():
        val, _ = _pick_single(cs, key, warnings) if cs else (None, [])
        blk[key] = val

    _resolve_saldos(blk, cand, cfg, warnings)

    # cross-check against the OPERACIONES table
    blk["operaciones_shares"] = _sum_operaciones(lines, i_sal, end, cfg)
    return blk


def _resolve_saldos(blk: dict, cand: dict, cfg: dict, warnings: list[str]) -> None:
    """Resolve overlapping renders with the conservation identity first."""
    res = cfg["parse"]["overlap_resolution"]
    keys = ["acciones_tesoreria", "acciones_circulacion"]
    if all(blk.get(f"{k}_{s}") is not None for k in keys for s in ("ultimo", "presente")):
        return

    if res.get("use_conservation_identity", True):
        opts = {f"{k}_{s}": (cand.get(f"{k}_{s}") or []) for k in keys for s in ("ultimo", "presente")}
        solutions = []
        for tu in opts["acciones_tesoreria_ultimo"]:
            for tp in opts["acciones_tesoreria_presente"]:
                for cu in opts["acciones_circulacion_ultimo"]:
                    for cp in opts["acciones_circulacion_presente"]:
                        if tp["value"] - tu["value"] == cu["value"] - cp["value"]:
                            solutions.append((tu, tp, cu, cp))
        uniq = {tuple(x["value"] for x in s) for s in solutions}
        if len(uniq) == 1:
            tu, tp, cu, cp = solutions[0]
            blk["acciones_tesoreria_ultimo"] = tu["value"]
            blk["acciones_tesoreria_presente"] = tp["value"]
            blk["acciones_circulacion_ultimo"] = cu["value"]
            blk["acciones_circulacion_presente"] = cp["value"]
            warnings.append("saldos: overlap resolved by conservation identity "
                            f"(delta tesoreria {tp['value'] - tu['value']:,})")
            return
        warnings.append(f"saldos: conservation identity gave {len(uniq)} solutions")

    if res.get("use_x_alignment_fallback", True):
        for key in cfg["parse"]["saldos"]["columns"]:
            holder = {"a": blk.get(f"{key}_ultimo"), "b": blk.get(f"{key}_presente"),
                      "_a_cands": cand.get(f"{key}_ultimo"), "_b_cands": cand.get(f"{key}_presente")}
            _resolve_pair_by_alignment(holder, "a", "b", warnings)
            if holder["a"] is not None:
                blk[f"{key}_ultimo"] = holder["a"]
            if holder["b"] is not None:
                blk[f"{key}_presente"] = holder["b"]

    missing = [f"{k}_{s}" for k in keys for s in ("ultimo", "presente") if blk.get(f"{k}_{s}") is None]
    if missing:
        raise ParseError(f"unresolved overlapping renders for {missing}")


def _sum_operaciones(lines, start, end, cfg) -> int | None:
    """Sum NUMERO DE ACCIONES over the operations rows (integrity check only)."""
    i_ops = _find_line(lines, cfg["parse"]["operaciones"]["section"], start, end)
    if i_ops < 0:
        return None
    total, seen = 0, False
    for ln in lines[i_ops:end]:
        toks = ln.text.split()
        if len(toks) < 3 or not toks[0].isdigit():
            continue
        tipo = fold(toks[1])
        if tipo not in ("compra", "venta"):
            continue
        n = parse_number(toks[2])
        if n is None:
            continue
        seen = True
        total += n if tipo == "compra" else -n
    return total if seen else None


# --------------------------------------------------------------------------
# ledger (append-only)
# --------------------------------------------------------------------------
def read_ledger(cfg: dict) -> list[dict]:
    path = repo_path(cfg["paths"]["ledger_csv"])
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def append_ledger(cfg: dict, rows: list[dict]) -> int:
    """APPEND-ONLY. Never rewrites or truncates existing history."""
    if not rows:
        return 0
    path = repo_path(cfg["paths"]["ledger_csv"])
    existing = read_ledger(cfg)
    have = {(r["report_date"], r["serie"]) for r in existing}
    new = [r for r in rows if (r["report_date"], r["serie"]) not in have]
    if not new:
        return 0
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        if write_header:
            w.writeheader()
        for r in new:
            w.writerow({k: r.get(k, "") for k in LEDGER_FIELDS})
    return len(new)


def _ledger_row(cfg: dict, meta: dict, parsed: dict, blk: dict) -> dict:
    return {
        "report_date": parsed["fecha_operacion"].isoformat() if parsed["fecha_operacion"] else meta.get("report_date", ""),
        "published_at": meta.get("published_at", ""),
        "serie": blk["serie"],
        "casa_de_bolsa": blk.get("casa_de_bolsa") or "",
        "remanente_ultimo": parsed["remanente_ultimo"],
        "remanente_presente": parsed["remanente_presente"],
        "acciones_tesoreria_ultimo": blk["acciones_tesoreria_ultimo"],
        "acciones_tesoreria_presente": blk["acciones_tesoreria_presente"],
        "acciones_circulacion_ultimo": blk["acciones_circulacion_ultimo"],
        "acciones_circulacion_presente": blk["acciones_circulacion_presente"],
        "pdf_url": meta.get("pdf_url", ""),
        "pdf_sha256": meta.get("pdf_sha256", ""),
        "fetched_at_utc": meta.get("fetched_at_utc", ""),
    }


def parse_all(cfg: dict, log: RunLog) -> list[dict]:
    """Parse every PDF in data/raw and append new rows to the ledger."""
    import fetch_reports

    raw_dir = repo_path(cfg["paths"]["raw_pdf_dir"] + "/.keep").parent
    inv = {r["report_date"]: r for r in fetch_reports.read_inventory(cfg)}
    expected = set(cfg["issuer"]["expected_series"])

    rows, failures = [], 0
    for pdf in sorted(raw_dir.glob("*.pdf")):
        report_date = pdf.stem.split("_")[0]
        meta = dict(inv.get(report_date, {}))
        meta["pdf_sha256"] = sha256_bytes(pdf.read_bytes())
        meta.setdefault("report_date", report_date)
        try:
            parsed = parse_pdf(pdf, cfg)
        except Exception as exc:
            failures += 1
            log.alert(f"UNPARSED {pdf.name}: {type(exc).__name__}: {exc}")
            continue

        if len(parsed["series"]) > 1:
            log.alert(f"{pdf.name}: {len(parsed['series'])} series in one report "
                      f"{[b['serie'] for b in parsed['series']]}")
        for blk in parsed["series"]:
            if blk["serie"] not in expected:
                log.alert(f"{pdf.name}: unexpected serie {blk['serie']!r}")
            rows.append(_ledger_row(cfg, meta, parsed, blk))
        for w in parsed["warnings"]:
            log.info(f"{pdf.name}: {w}")

    added = append_ledger(cfg, rows)
    log.info(f"parse: {len(rows)} report-series parsed, {added} appended, {failures} unparsed")
    if failures:
        log.alert(f"{failures} report(s) could not be parsed - reported unparsed, not guessed")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse recompras PDFs into the ledger.")
    ap.add_argument("--dump", metavar="PDF", help="dump every field of one PDF and exit")
    args = ap.parse_args()

    cfg = load_config()
    log = RunLog(cfg)

    if args.dump:
        parsed = parse_pdf(Path(args.dump), cfg)
        for k, v in parsed.items():
            if k.startswith("_"):
                continue
            print(f"{k}: {v}")
        return 0

    parse_all(cfg, log)
    return 1 if log.alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
