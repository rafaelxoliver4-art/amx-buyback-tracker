# amx-buyback-tracker

Tracks **América Móvil (AMX)** share buybacks from the primary source: the
daily "Adquisición de Acciones por Emisora (Recompras)" PDFs published by the
Bolsa Mexicana de Valores.

> **Read [`CONTEXT.md`](CONTEXT.md) first.** It is the standing brief: the
> source, the derivation, the governance rules and the decisions log.
> [`PROGRESS.md`](PROGRESS.md) is the running cycle-by-cycle record.

**This project is isolated.** Everything lives in this folder. Local git only —
no remote, no GitHub Actions, no email, no secrets.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python src/backfill.py          # one-off, resumable: the FULL history 2021 -> today
```

```bash
python src/fetch_reports.py     # walk the listing, download the selected PDFs
```

```bash
python src/parse_report.py      # PDFs -> data/raw_reports.csv (append-only)
```

```bash
python src/build_series.py      # weekly + monthly frames -> output/AMX_Buybacks.xlsx
```

```bash
python src/verify_backfill.py   # acceptance test vs the owner's known-correct table
```

```bash
python -m pytest tests -q       # unit + integrity tests
```

`build_series.py` writes the workbook **and** the chart PNG in one pass.

Useful flags:

- `backfill.py --dry-run` — report what would be fetched and stop.
- `backfill.py --limit N` — fetch at most N reports, resume later.
- `backfill.py --from-cached-inventory` — skip the listing GET.
- `fetch_reports.py --inventory-only` — refresh `data/listing_inventory.csv`
  and stop.
- `fetch_reports.py --from-cached-inventory` — skip the listing GET.
- `parse_report.py --dump <pdf>` — print every parsed field of one PDF.
- `build_series.py --no-network` — don't probe daily reports on an unexplained
  remanente rise.
- `build_chart.py` — re-render the PNG only, without rewriting the workbook.

## Layout

```
config/    sources.yaml, program_additions.yaml, chart.yaml,
           schedule.yaml, email.yaml
src/       backfill.py, fetch_reports.py, parse_report.py, build_series.py,
           build_chart.py, verify_backfill.py
           common.py (config loading, polite HTTP, run log)
data/raw/  downloaded PDFs, named <report_date>_<serie>.pdf
data/      raw_reports.csv (append-only ledger), listing_inventory.csv
output/    AMX_Buybacks.xlsx, amx_buybacks_chart.png
docs/      recon_notes.md, pdf_field_dump.md
tests/     test_parser.py, test_integrity.py, test_series.py,
           expected_backfill_2026.yaml, expected_backfill_full.yaml
```

**Config over code**: every URL, selector, delay, retry count and date rule is
in `config/*.yaml`. Nothing of the sort belongs in Python.

## The three things most likely to surprise you

1. **The clave in a BMV URL is ignored.** `/es/emisoras/perfil/AMX-6386`
   renders a completely different issuer. AMX is `idEmisora` **6024**.
2. **One GET returns all 1,255 listing rows.** The pagination is client-side
   DataTables, not server paging.
3. **The PDF cannot be read by text extraction.** BMV draws some cells twice,
   overlapping; naive extraction yields
   `595,999,939,060,000,000,0000`. See
   [`docs/pdf_field_dump.md`](docs/pdf_field_dump.md).

## Status

Cycle 1 complete — full history backfilled to 2021, workbook styled, chart
built. Both acceptance fixtures pass on every value. The email body and the
weekly automation are Cycle 2.
