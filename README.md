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

Useful flags:

- `fetch_reports.py --inventory-only` — refresh `data/listing_inventory.csv`
  and stop.
- `fetch_reports.py --from-cached-inventory` — skip the listing GET.
- `parse_report.py --dump <pdf>` — print every parsed field of one PDF.
- `build_series.py --no-network` — don't probe daily reports on an unexplained
  remanente rise.

## Layout

```
config/    sources.yaml, program_additions.yaml, schedule.yaml, email.yaml
src/       fetch_reports.py, parse_report.py, build_series.py, verify_backfill.py
           common.py (config loading, polite HTTP, run log)
data/raw/  downloaded PDFs, named <report_date>_<serie>.pdf
data/      raw_reports.csv (append-only ledger), listing_inventory.csv
output/    AMX_Buybacks.xlsx
docs/      recon_notes.md, pdf_field_dump.md
tests/     test_parser.py, test_integrity.py, expected_backfill_2026.yaml
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

Cycle 0 complete — recon, scaffold and a verified 2026 backfill.
Acceptance test passes on every value. Chart, email body and weekly
automation are Cycles 1 and 2.
