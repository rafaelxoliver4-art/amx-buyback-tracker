# Recon notes — BMV recompras source

Recon date: **2026-08-03**. Everything below was verified against the live
site, not assumed.

## 1. robots.txt

| URL | Result |
|---|---|
| `https://www.bmv.com.mx/robots.txt` | **404** (HTML error page, `ISO-8859-1`) |
| `https://bmv.com.mx/robots.txt` | **404** (same) |

**No robots.txt is published on either host, so nothing is disallowed.** We
may proceed. `src/common.py::check_robots` re-checks this on every run and
**stops the fetcher** if a future robots.txt ever disallows `/es/emisoras/` or
`/docs-pub/recompra/`. It never works around a `Disallow`.

## 2. How a report is addressed

### 2a. The issuer id — the one genuinely non-obvious step

The listing URL needs BMV's **internal numeric issuer id**, not the ticker.
The clave in the URL is decorative and **ignored by the server** — a trap:

```
/es/emisoras/perfil/AMX-6386   -> renders IEF (iShares 7-10Y Treasury ETF)
```

The `6386` binds, `AMX` does not. Worse, the tab links rendered *on AMX's own
profile page* point at `IEF-6386`, so following the site's own navigation
lands on the wrong issuer.

The id comes from the issuer-search endpoint:

```
POST/GET https://www.bmv.com.mx/es/Grupo_BMV/Informacion_de_emisora/_rid/541/_mto/3/_mod/doSearch
         ?idTipoMercado=CGEN_CAPIT&idTipoInstrumento=&idTipoEmpresa=
         &idSector=&idSubsector=&idRamo=&idSubramo=&random=1234
```

which returns JSON prefixed with the anti-hijacking guard `for(;;);(` …`)`:

```json
{ "idEmisora": 6024, "claveEmisora": "AMX",
  "razonSocial": "AMERICA MOVIL, S.A.B. DE C.V." }
```

**AMX = idEmisora 6024**, market `CGEN_CAPIT`. Stored in `config/sources.yaml`.

> Sending the same request with the browser form's *own* field names
> (`tipoMercado=…`) returns a JBoss **500**. Only the `idTipoMercado=…` names
> used by the sibling `doDownload` action work.

### 2b. The listing — HTML, but only one request

```
https://www.bmv.com.mx/es/emisoras/informcioncorporativa/AMX-6024-CGEN_CAPIT
```

(BMV's own typo: `informcioncorporativa`, no `a` after `inform`.)

**There is no JSON/REST endpoint behind this page — and none is needed.** The
page is fully server-rendered and contains **every row at once**. The ~251
"pages" of ~5 rows a browser shows are **DataTables client-side pagination**,
configured in
`/work/models/Grupo_BMV/assets/js/public/empresas_listadas/informacion_corporativa.min.js`:

```js
a = l.DataTable({ iDisplayLength: 5, bSort: !1, ... })
```

So **one GET yields the complete inventory**: 1,255 Recompras rows spanning
2021-08-03 → 2026-07-31 (~950 KB). This is the single most important
operational finding — no pagination loop, no 251 requests.

The page holds several accordion sections (`Reestructuras Corporativas`,
`Recompras`, …). The parser keys on the `<h2>` heading
`ADQUISICION DE ACCIONES POR EMISORA (RECOMPRAS)` and stops at the next `<h2>`.

Row shape:

```html
<tr>
  <td>31-07-2026 17:31</td>
  <td>Recompras</td>
  <td>… <a href="/docs-pub/recompra/recompra_1579180_1.pdf" class="lnk-download">…</a></td>
</tr>
```

### 2c. The PDF URL — stable but NOT predictable

```
/docs-pub/recompra/recompra_<doc_id>_<seq>.pdf
```

`doc_id` is an opaque, monotonically increasing **EMISNET document id**
(1,519,714 on 31-Dec-2025 → 1,579,180 on 31-Jul-2026). It is **not derivable
from the date** — the increments are irregular because the counter is shared
across every issuer's filings:

| report date | doc_id | Δ vs prior month-end |
|---|---:|---:|
| 2025-12-31 | 1519714 | — |
| 2026-01-30 | 1528791 | +9,077 |
| 2026-02-27 | 1537781 | +8,990 |
| 2026-03-31 | 1545704 | +7,923 |
| 2026-04-30 | 1554646 | +8,942 |
| 2026-05-29 | 1564194 | +9,548 |
| 2026-06-30 | 1571409 | +7,215 |
| 2026-07-31 | 1579180 | +7,771 |

**Therefore the listing must be scraped; URLs cannot be constructed.**

Once known, the URL is a **stable, permanent, unauthenticated static file** —
no token, no cookie, no session, no `Referer` check. Verified by fetching
`recompra_1579180_1.pdf` with a bare `requests.get` and no prior page visit.
There is no login and no CAPTCHA anywhere in this path.

## 3. Publication cadence

| | |
|---|---|
| Frequency | one report per trading day |
| 2026 volume | Jan 21, Feb 19, Mar 24, Apr 20, May 20, Jun 22, Jul 23 |
| Filing time | 16:39–17:59 local, same evening as the trading day |
| Weekends/holidays | no report (e.g. Sat 30-May-2026 does not exist) |
| Duplicate dates | occur in earlier years (two filings same day); handled by taking the **last** by `published_at` |

`FECHA Y HORA` in the listing: the **date is the as-of/operation date**, the
**time is the publication time**. Confirmed for every downloaded report by
`tests/test_parser.py::test_report_date_is_operation_date`.

## 4. What the PDF contains

See [`pdf_field_dump.md`](pdf_field_dump.md) for the complete field inventory,
the confirmation of both expected 31-Jul figures, the
**overlapping-render defect** and how it is resolved, and the answers on
multiple series / casas de bolsa and the missing programme-amount field.

## 5. Fragility register for the unattended weekly run

Ranked by likelihood × impact. See `amx-buyback-tracker-PROGRESS.md` for the
same list with mitigations.

| # | Risk | Detected by |
|---|---|---|
| 1 | `idEmisora` 6024 changes or the URL typo `informcioncorporativa` is fixed | listing GET returns 200 with 0 rows → **ALERT**, no data wiped |
| 2 | The `<h2>` heading text changes | 0 rows → **ALERT** |
| 3 | The listing page grows unbounded (1,255 rows / ~950 KB today, +~250 rows/yr) | none yet — see open questions |
| 4 | The overlapping-render defect changes shape | conservation identity fails → report **UNPARSED**, never guessed |
| 5 | An undeclared programme top-up | negative buyback → daily probe → **ALERT**, `confirmed_by_owner: false` |
| 6 | Site 500s / JBoss errors (observed during recon) | retry + backoff, then **ALERT** |
| 7 | A second serie or casa de bolsa appears | per-serie rows + **ALERT** |
| 8 | BMV restates a prior figure | `al último` integrity test |
