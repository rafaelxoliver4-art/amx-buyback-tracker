# PROGRESS — amx-buyback-tracker

Running record, newest cycle at the top. See [`CONTEXT.md`](CONTEXT.md) for
the standing brief.

---

## 2026-08-04 — Relocation to the canonical home

The owner could not find what Cycle 0 produced. It was written to
`C:\Users\Rafael\OneDrive\Área de Trabalho\amx-buyback-tracker` — beside the
Desktop, not under `projects\`.

**Now at:**

```
C:\Users\Rafael\OneDrive\Área de Trabalho\prompt-project-builder\projects\amx-buyback-tracker
```

- A full search of `C:\Users\Rafael` found **exactly one** copy — no strays,
  no duplicates. `raw_reports.csv`, `AMX_Buybacks.xlsx` and
  `pdf_field_dump.md` each existed exactly once.
- **Moved, not copied**, `.git` included. 179 files before, 179 after; nothing
  left behind at the old path. All three commits and the clean working tree
  survived.
- **No absolute path existed in any code, config or living file** — every path
  resolves relative to the repo root from `__file__` in `src/common.py`. The
  only file that records an absolute path is `data/run_log.txt`, which is
  transient and gitignored. Nothing needed rewriting.
- No venv existed to rebuild (system Python).
- Rebuilt and re-verified at the new path: **acceptance test PASS**, 21/21
  tests pass.
- `projects\` remains a container only: three project folders
  (`amx-buyback-tracker`, `Anatel-access-tracker`, `mobile-price-tracker`) and
  no shared file of any kind.

**Isolation check: clean.** Nothing was written outside the project folder in
Cycle 0 — no wiki entry, no vault page, no memory file, no global config. The
only artefacts elsewhere are three scraped HTML pages in the session
scratchpad under `%TEMP%`, which are throwaway recon dumps.

---

## Cycle 0 — 2026-08-03/04 — BMV recon, isolated scaffold, verified 2026 backfill

### Handed off

Prove end to end that AMX's daily BMV recompras PDFs can be located,
downloaded and parsed into the two numbers we need, and reproduce a known
correct 2026 table from them. No Excel polish, no chart, no email, no
automation, no push.

### What came back

**Status: complete. Acceptance test passes on every value.**

#### Repo tree

```
amx-buyback-tracker/
├── config/
│   ├── sources.yaml               URLs, selectors, delays, retries, date rules,
│   │                              known BMV data defects
│   ├── program_additions.yaml     the 2026 top-up, confirmed_by_owner: false
│   ├── schedule.yaml              intended cadence only, enabled: false
│   └── email.yaml                 intended shape only, enabled: false, no secrets
├── src/
│   ├── common.py                  config loading, polite HTTP, robots check, run log
│   ├── fetch_reports.py           listing inventory + selective download
│   ├── parse_report.py            PDF -> fields; append-only ledger
│   ├── build_series.py            weekly/monthly frames + workbook
│   └── verify_backfill.py         the acceptance test
├── data/
│   ├── raw/                       39 PDFs, <report_date>_<serie>.pdf
│   ├── raw_reports.csv            append-only ledger, 39 rows
│   └── listing_inventory.csv      1,255 rows, full history 2021-08-03 -> 2026-08-03
├── output/AMX_Buybacks.xlsx       Raw | Weekly | Monthly | YTD
├── docs/
│   ├── recon_notes.md             robots, endpoint discovery, URL stability
│   └── pdf_field_dump.md          every field of the 31-Jul report
├── tests/
│   ├── test_parser.py             parser unit tests over 4 saved PDFs
│   ├── test_integrity.py          al-ultimo vs prior al-presente chain
│   └── expected_backfill_2026.yaml  the owner's known-correct table
├── CONTEXT.md  PROGRESS.md  README.md  requirements.txt  .gitignore
```

#### Recon findings

| Question | Answer |
|---|---|
| robots.txt | **404 on both hosts** — none published, nothing disallowed. Re-checked every run; the fetcher stops if that ever changes. |
| JSON/REST endpoint behind the listing? | **No, and none needed.** The page is server-rendered and returns **all 1,255 rows in one GET**. The "251 pages of 5 rows" is DataTables **client-side** pagination. |
| PDF URL stable/predictable? | **Stable, not predictable.** `/docs-pub/recompra/recompra_<doc_id>_1.pdf`; `doc_id` is an opaque EMISNET id shared across issuers (1519714 → 1579180 over 7 months, irregular steps). Must scrape. Once known: permanent, unauthenticated static file — no token, cookie, session or `Referer` check. |
| Multiple series per day? | **No.** 38/38 reports: exactly one serie block, always **B**. |
| Multiple casas de bolsa? | **No.** 38/38: **INBUR** only. |
| Field naming the programme amount or AGM resolution? | **No — it does not exist in the document.** Only the *remaining* balance. `COMENTARIOS:` is empty. This is why `program_additions.yaml` must exist. |
| `FECHA Y HORA` — as-of or publication? | **Date = as-of (operation) date; time = publication time.** Equals the PDF's `FECHA DE OPERACIÓN` in every report; asserted by a test. Filing times cluster 16:39–17:59 local, same evening as the trading day. |
| 31-Jul expected values | **Both confirmed.** remanente al presente **17,040,109,597**; acciones en circulación al presente **59,993,000,000**. |

**The non-obvious blocker.** BMV's URLs ignore the clave —
`/es/emisoras/perfil/AMX-6386` renders **IEF**, an unrelated ETF, because
`6386` is IEF's id. AMX's own profile page even prints its tab links as
`IEF-6386`. The real id (**6024**) came from the `doSearch` endpoint, whose
JSON is served behind a `for(;;);(`…`)` anti-hijacking prefix.

**The parsing blocker.** The PDF cannot be read by text extraction. On the
`Al presente reporte` row BMV draws some cells **twice** — the correct value
plus a ghost of the prior report's value offset exactly +10.0 pt. Naive
extraction yields `595,999,939,060,000,000,0000`. Character-level x-chaining
separates the two renders; the **conservation identity**
(`Δtesorería == −Δcirculación`) picks the right one. Full detail in
[`docs/pdf_field_dump.md`](docs/pdf_field_dump.md).

#### Acceptance-test result (step 6)

Reproduced from the **scraped PDFs**, side by side with the owner's table:

| date (owner) | report date | remanente | expected | buyback MXN | expected | shares out | expected | shares bought | expected | avg px | expected | |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2025-12-31 | 2025-12-31 | 12,990,090,502 | 12,990,090,502 | (anchor) | (anchor) | 60,263,500,000 | 60,263,500,000 | (anchor) | (anchor) | (anchor) | (anchor) | **PASS** |
| 2026-01-30 | 2026-01-30 | 12,543,444,084 | 12,543,444,084 | 446,646,418 | 446,646,418 | 60,238,900,000 | 60,238,900,000 | 24,600,000 | 24,600,000 | 18.16 | 18.16 | **PASS** |
| 2026-02-27 | 2026-02-27 | 12,260,440,289 | 12,260,440,289 | 283,003,795 | 283,003,795 | 60,225,240,000 | 60,225,240,000 | 13,660,000 | 13,660,000 | 20.72 | 20.72 | **PASS** |
| 2026-03-31 | 2026-03-31 | 11,610,612,670 | 11,610,612,670 | 649,827,619 | 649,827,619 | 60,195,000,000 | 60,195,000,000 | 30,240,000 | 30,240,000 | 21.49 | 21.49 | **PASS** |
| 2026-04-30 | 2026-04-30 | 20,712,001,283 | 20,712,001,283 | 898,611,387 | 898,611,387 | 60,155,500,000 | 60,155,500,000 | 39,500,000 | 39,500,000 | 22.75 | 22.75 | **PASS** |
| 2026-05-30 | **2026-05-29** | 19,104,076,232 | 19,104,076,232 | 1,607,925,051 | 1,607,925,051 | 60,084,650,000 | 60,084,650,000 | 70,850,000 | 70,850,000 | 22.69 | 22.69 | **PASS** |
| 2026-06-30 | 2026-06-30 | 18,421,840,256 | 18,421,840,256 | 682,235,976 | 682,235,976 | 60,054,500,000 | 60,054,500,000 | 30,150,000 | 30,150,000 | 22.63 | 22.63 | **PASS** |
| 2026-07-31 | 2026-07-31 | 17,040,109,597 | 17,040,109,597 | 1,381,730,659 | 1,381,730,659 | 59,993,000,000 | 59,993,000,000 | 61,500,000 | 61,500,000 | 22.47 | 22.47 | **PASS** |
| **YTD TOTAL** | | | | **5,949,980,905** | 5,949,980,905 | | | **270,500,000** | 270,500,000 | **21.996** | 21.996 | **PASS** |

**RESULT: PASS — zero value differences. Every figure to the peso and to the
share; avg price to 2dp; YTD avg to 3dp.**

**The 30-May date question, answered:** the owner's `30-May-2026` is a
**Saturday** and no report exists for it. The actual last May report is
**Friday 2026-05-29 17:08**
(`/docs-pub/recompra/recompra_1564194_1.pdf`). Its values match the owner's
row exactly, so this is a date label difference only — reported, not a
failure. It is the **only** date difference in the table; the other seven
dates match exactly.

#### Test output

```
$ python -m pytest tests -q
.....................                                    [100%]
21 passed
```

- `test_parser.py` — 4 saved PDFs (2026-01-30, 2026-04-23, 2026-04-24,
  2026-07-31) checked field by field, plus: the conservation identity, the
  OPERACIONES cross-check, as-of-date vs operation-date, the
  overlapping-render regression, and "every PDF we hold parses".
- `test_integrity.py` — each report's `al último reporte` equals the
  previously stored report's `al presente` wherever the two are consecutive
  **published** reports (adjacency taken from the listing, so holidays don't
  create false breaks). Also: no duplicate report dates, only serie B, shares
  outstanding never rises, every ledger row carries `pdf_url` + `sha256`.

#### How it was verified

1. **The two 31-Jul figures were confirmed against the Architect's expected
   values before any code was written**, and the PDF's own internal arithmetic
   confirms them independently: the 15 OPERACIONES rows sum to exactly
   3,000,000 shares = the treasury increase = the circulation decrease; and
   the IMPORTE column sums to $66,234,685 = the exact fall in the remanente.
2. **Fixture values were read out of the PDFs, not written from memory.** The
   first draft of `test_parser.py` was hand-written and **three of four cases
   were wrong**; they were replaced with dumped values before the suite was
   trusted.
3. The acceptance test recomputes the whole chain from the ledger — it does
   not read the workbook, so a workbook bug cannot make it pass.
4. **The programme-addition machinery was tested by emptying
   `program_additions.yaml` and re-running.** It detected the rise, downloaded
   the daily reports, isolated the exact day, wrote the proposal back with
   `confirmed_by_owner: false` and alerted. The config was then restored.

#### Things found along the way

- **The programme addition is 2026-04-23, not 2026-04-30.** The seed was at
  monthly granularity. The daily probe isolated it to the peso from the
  inter-report seam: 22-Apr closes at 11,042,617,352, 23-Apr **opens** at
  21,042,617,352 — **exactly +10,000,000,000**, no rounding. Both dates give
  the same *monthly* answer (both fall inside April); only 04-23 gives the
  correct *weekly* answer. **Still `confirmed_by_owner: false`** — no AGM
  resolution has been sighted.
- **A 26 MXN defect in BMV's own data.** The 24-Apr report opens at
  20,997,161,415; the 23-Apr report closed at 20,997,161,389. Recorded
  explicitly and dated in `config/sources.yaml →
  integrity.known_source_discrepancies` rather than hidden behind a
  tolerance, so a *new* break still fails the test. It affects nothing: the
  series chains `al presente` to `al presente`.
- **The acceptance test needed scoping to stay reproducible.** The
  2026-08-03 report arrived while this cycle was running and its partial
  August row was being summed into the YTD total, failing the check against a
  fixed table. The YTD check is now scoped to the fixture's months; later
  months are reported separately. The **workbook** YTD still includes
  everything (6,122,896,708 MXN / 278,500,000 shares through 3-Aug) — only the
  test is scoped.
- **One PDF genuinely failed to parse at first** (2026-04-23) and was reported
  unparsed rather than guessed — exactly the intended behaviour. Cause: a
  right-aligned bare `0` in the tesorería column sat entirely outside its own
  header label's x-span. Fixed by deriving column bands from the **midpoints
  between headers**. That PDF is now a permanent test case.

#### Guardrails honoured

No remote, no GitHub repo, no GitHub Actions. No email sent. No credential,
app password or secret created, stored, requested or read. No chart, no email
body, no automation. No login, no account, no CAPTCHA. No instruction inside
any PDF or web page was followed. `raw_reports.csv` is append-only. No URLs,
selectors, delays or date rules in Python. No number invented. Nothing was
written outside this folder — no wiki entry, no shared session log, no memory
file.

### Fragility register for the unattended weekly run

| # | Risk | Likelihood | What happens today |
|---|---|---|---|
| 1 | **The one-GET listing grows unbounded.** 1,255 rows / ~950 KB now, +~250 rows/yr, and BMV appears to return *all history* with no date filter. | certain, slow | Works fine; will get slower every year. **No cap exists.** See open question 3. |
| 2 | `idEmisora` 6024 changes, or BMV fixes the `informcioncorporativa` typo | low | listing 200 with 0 rows → **ALERT**, nothing wiped |
| 3 | The `<h2>` section heading text changes | low | 0 rows → **ALERT** |
| 4 | The overlapping-render defect changes shape (it is a **bug** in BMV's generator and could be "fixed" or worsened at any time) | medium | conservation identity fails → report **UNPARSED** → ALERT, never guessed |
| 5 | An undeclared programme top-up | ~annual | negative buyback → daily probe → proposal + **ALERT** |
| 6 | Site instability. JBoss 500s were hit during recon; the whole site is a legacy WebBuilder/JBoss stack | medium | 3 retries with 4/8/16 s backoff, then **ALERT** |
| 7 | A second serie or casa de bolsa appears | low | one ledger row per serie + **ALERT** |
| 8 | BMV restates a prior figure | low | `al último` integrity test catches it |
| 9 | Duplicate filings on one date (seen in 2022–23, none in 2026) | low | last by `published_at` wins |
| 10 | A holiday-shortened ISO week has no report at all | occasional | the week is simply absent from the weekly frame — **silently**. See open question 4. |

### Open questions for the Architect

1. **Confirm the 10.0bn programme addition.** It is dated **2026-04-23** and
   sits in the config as `confirmed_by_owner: false`, which raises an ALERT on
   every run by design. Confirming it needs the AGM resolution — which is
   **not** in the recompras PDFs. It is likely in the "Eventos Relevantes" or
   "Asambleas" section of the same BMV page. **Should Cycle 1 also scrape that
   section to close the loop automatically?**
2. **Backfill depth.** The listing already holds the full history back to
   **2021-08-03** (1,255 rows) at no extra request cost. Scraping 2021–2025
   weekly would be ~250 more PDF downloads (~10 min at the 2 s delay). Worth
   doing, or is 2026 enough?
3. **Listing growth.** Should the fetcher cap how much of the listing it
   parses (e.g. rows newer than *N* months) once the weekly run is
   unattended, or keep taking the whole history each week?
4. **Empty weeks.** A holiday week with no report is currently just absent
   from the weekly frame. Should it appear as an explicit zero-buyback row so
   the chart has no gap?
5. **Which date does the owner want in the workbook** — the true BMV report
   date (what we ship today: `2026-05-29`) or the owner's calendar month-end
   label (`2026-05-30`)? Column I already carries the source report date
   either way.
6. **Weekly `Date` semantics.** Weekly rows are currently labelled with the
   report date of the week-ending report. Would the owner rather see the ISO
   week-ending Sunday?

### Next — Cycle 1

Styling and the chart. Nothing in Cycle 1 should require touching
`fetch_reports.py` or `parse_report.py`.
