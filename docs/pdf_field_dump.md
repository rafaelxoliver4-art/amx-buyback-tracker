# PDF field dump — AMX recompras report of 31-07-2026 17:31

Complete inventory of every field the PDF contains. Source of truth for the
parser.

| | |
|---|---|
| Listing row | `31-07-2026 17:31` / ASUNTO `Recompras` / Descargar |
| PDF URL | `https://www.bmv.com.mx/docs-pub/recompra/recompra_1579180_1.pdf` |
| Bytes | 94,367 |
| sha256 | `e0d183a1421938801f8bfc8679b579e234b0154417d6c537f6eb122bb02de02d` |
| Pages | 2 |
| Page size | 612 × 792 pt (US Letter) |
| Fonts | `HelveticaLTStd-Roman` only — a real text PDF, no OCR needed |
| Local copy | `data/raw/2026-07-31_B.pdf` |

## Confirmation of the two expected figures

| Field | Expected by Architect | Found in PDF | |
|---|---:|---:|---|
| Remanente de recursos, al presente | 17,040,109,597 | **17,040,109,597** | ✅ confirmed |
| Acciones en circulación, al presente | 59,993,000,000 | **59,993,000,000** | ✅ confirmed |

The second figure is **not** obtainable by naive text extraction — see
[The overlapping-render defect](#the-overlapping-render-defect) below.

---

## Every field, in document order

### Page 1 — header block

| Label | Value | Notes |
|---|---|---|
| *(title)* | `Informacion de recompra` | no accent in the source |
| `FECHA:` | `31/07/2026` | document date |
| *(banner)* | `BOLSA MEXICANA DE VALORES, S.A.B. DE C.V., INFORMA:` | constant |
| `CLAVE DE COTIZACIÓN` | `AMX` | |
| `RAZÓN SOCIAL` | `AMERICA MOVIL, S.A.B. DE C.V.` | |
| `FECHA DE OPERACIÓN` | `31/07/2026` | **equals `FECHA:` and equals the listing date** |

### Page 1 — REMANENTE DE RECURSOS

Report-level, **not** per serie. Appears once per PDF, above the serie block.

| Row | Value |
|---|---:|
| `Al último reporte` | 17,106,344,282 |
| `Al presente` | **17,040,109,597** ← *one of the two figures we need* |

Note the label asymmetry: this block says `Al presente`, the SALDOS block
below says `Al presente reporte`. Both are matched from config, separately.

### Page 1 — OPERACIÓN POR SERIE

| Field | Value |
|---|---|
| `SERIE` | `B` |
| `CASA DE BOLSA` | `INBUR` |

**Exactly one serie and exactly one casa de bolsa.** See
[Multiple series / casas de bolsa](#multiple-series--casas-de-bolsa).

### Page 1 — SALDOS

Three columns, two rows:

| | Acciones en Tesoreria | Acciones en Circulación | Acciones con Cargo C.C. |
|---|---:|---:|---:|
| `Al último reporte` | 174,000,000 | 59,996,000,000 | 0 |
| `Al presente reporte` | 177,000,000 | **59,993,000,000** | 0 |

← *`Acciones en Circulación / Al presente reporte` is the second figure we need.*

### Page 1–2 — OPERACIONES

Columns: `FOLIO`, `TIPO DE OPERACION`, `NÚMERO DE ACCIONES`,
`PRECIO UNITARIO`, `IMPORTE DE LA OPERACIÓN`, `ACCIONES CON CARGO A CAPITAL`.

All 15 rows, verbatim:

| FOLIO | TIPO | NÚMERO DE ACCIONES | PRECIO UNITARIO | IMPORTE | CARGO A CAPITAL |
|---:|---|---:|---:|---:|---|
| 57876 | Compra | 200,000 | $22 | $4,400,000 | Social |
| 57877 | Compra | 100,000 | $22.02 | $2,202,000 | Social |
| 57878 | Compra | 20,000 | $22.03 | $440,600 | Social |
| 57879 | Compra | 2,898 | $22.04 | $63,872 | Social |
| 57880 | Compra | 194,760 | $22.05 | $4,294,458 | Social |
| 57881 | Compra | 199,342 | $22.06 | $4,397,485 | Social |
| 57882 | Compra | 706,000 | $22.07 | $15,581,420 | Social |
| 57883 | Compra | 492,000 | $22.08 | $10,863,360 | Social |
| 57884 | Compra | 94,000 | $22.09 | $2,076,460 | Social |
| 57885 | Compra | 279,000 | $22.1 | $6,165,900 | Social |
| 57886 | Compra | 149,000 | $22.11 | $3,294,390 | Social |
| 57887 | Compra | 501,000 | $22.12 | $11,082,120 | Social |
| 57888 | Compra | 23,000 | $22.13 | $508,990 | Social |
| 57889 | Compra | 22,000 | $22.14 | $487,080 | Social |
| 57890 | Compra | 17,000 | $22.15 | $376,550 | Social |
| | **total** | **3,000,000** | | **$66,234,685** | |

### Page 2 — footer

| Field | Value |
|---|---|
| `COMENTARIOS:` | *(empty)* |
| *(page footer)* | `Bolsa Mexicana de Valores S.A.B. de C.V.` + page number |

That is the complete document. **There is nothing else in it.**

---

## Three internal consistency checks that all hold

1. Shares purchased sum to **3,000,000**.
2. Treasury rose 174,000,000 → 177,000,000 = **+3,000,000**. ✅
3. Circulation fell 59,996,000,000 → 59,993,000,000 = **−3,000,000**. ✅

Check 3 is what lets the parser resolve the rendering defect below without
guessing. Separately, `IMPORTE` sums to $66,234,685, whereas remanente fell
17,106,344,282 → 17,040,109,597 = **66,234,685**. ✅ Exact.

---

## The overlapping-render defect

**This is the single most important parsing finding.**

On the `Al presente reporte` row BMV draws some cells **twice**: the correct
value, and a ghost of the previous report's value offset **exactly +10.0 pt**
to the right. Naive `extract_text()` sorts characters by x and concatenates,
producing garbage:

```
Al presente reporte 177,000,000 595,999,939,060,000,000,0000 0 0
```

At the character level the two renders are cleanly separable, because each is
internally contiguous — every character's `x0` equals the previous
character's `x1`:

| run | x0 | x1 | text | |
|---|---:|---:|---|---|
| A | 325.50 | 395.00 | `59,993,000,000` | correct — column-aligned with the row above |
| B | 335.50 | 405.00 | `59,996,000,000` | ghost of `al último`, +10.0 pt |

Observed behaviour across all 38 downloaded reports:

- The ghost appears on **Acciones en Circulación** and **Acciones con Cargo
  C.C.**, on the `Al presente reporte` row only.
- It never appears on **Acciones en Tesoreria**, and never on the
  `Al último reporte` row.
- It never appears in the REMANENTE DE RECURSOS block.
- The ghost always carries the **previous** report's value.

**How the parser resolves it** (`src/parse_report.py`), in order:

1. **Conservation identity** — pick the candidate satisfying
   `Δtesorería == −Δcirculación`. Unambiguous in all 38 reports.
2. **x-alignment fallback** — the candidate whose `x0` matches the
   unambiguous sibling row.
3. **Otherwise the report is reported UNPARSED.** A number is never guessed.

---

## Questions the Architect asked

### Multiple series / casas de bolsa?

**No — one of each, in every report.** Verified across all 38 downloaded
reports spanning Dec-2025 to Jul-2026:

```
series-blocks per report: {1: 38}
series seen:              {'B': 38}
casas de bolsa seen:      {'INBUR': 38}
reports with >1 casa or >1 serie mention: NONE
```

AMX has only serie B listed on BMV and routes all repurchases through Casa de
Bolsa Inbursa. The parser nonetheless emits **one ledger row per serie** and
raises an ALERT if a report ever contains more than one, or a serie other than
`B` — this is not assumed away.

### A field naming the approved programme amount or the AGM resolution?

**No. Neither exists anywhere in the document.** The PDF states only the
*remaining* balance (`REMANENTE DE RECURSOS`), never the programme size, never
the authorised total, never an AGM/asamblea reference, and `COMENTARIOS:` is
empty. There is no field to parse.

This is precisely why `config/program_additions.yaml` has to exist: a
programme top-up is invisible in the source except as an unexplained rise in
the remanente.

### Is FECHA Y HORA the as-of date or the publication date?

**The DATE is the as-of (operation) date; the TIME is the publication time.**

For this report: the listing shows `31-07-2026 17:31`, and the PDF's
`FECHA DE OPERACIÓN` is `31/07/2026` — the same day. Asserted for every
downloaded report by `tests/test_parser.py::test_report_date_is_operation_date`,
which passes for all of them.

The times cluster at 16:39–17:59 local, i.e. each trading day's report is
filed the same evening after the close. The date needs no shifting.

### Does each PDF carry the prior report's values?

**Yes** — `al último reporte` on both the remanente and the saldos blocks. It
is used as a free integrity check on the previously stored row
(`tests/test_integrity.py`), and it is what makes a programme addition
exactly measurable: within one report `al último → al presente` is pure
buyback, so a top-up can only appear in the **seam between two reports**.

That seam is how the 2026 addition was pinned to the peso:

```
22-Apr report, al presente : 11,042,617,352
23-Apr report, al último   : 21,042,617,352   -> exactly +10,000,000,000
```

**One defect found in BMV's own data:** the 24-Apr report opens at
20,997,161,415 while the 23-Apr report closed at 20,997,161,389 — BMV's
restatement is **26 MXN** higher. Recorded explicitly in
`config/sources.yaml → integrity.known_source_discrepancies`. It does not
affect any derived figure, because the series chains `al presente` to
`al presente` and never consumes `al último`.
