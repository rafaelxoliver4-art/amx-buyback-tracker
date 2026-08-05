# amx-buyback-tracker — PROGRESS

Running record, newest cycle at the top. See
[`amx-buyback-tracker-CONTEXT.md`](amx-buyback-tracker-CONTEXT.md) for the
standing brief.

---

## WHERE THINGS STAND — as of 2026-08-05

**Read this first.** Everything below it is the cycle-by-cycle history.

### Built and passing

| | |
|---|---|
| Cycles complete | **0** (recon + scaffold), **1** (backfill, styling, chart), **2** (the nine rulings + first push), **3** (Actions + email, built not live) |
| Ledger | **536 rows**, append-only, serie B from 2023-03-17 |
| PDFs held | 342, all parsed, **0 unparsed** |
| Acceptance test | **2026 fixture PASS · full-history fixture PASS (32/32 rows)** |
| Test suite | **70 passed** |
| Deliverables | `output/AMX_Buybacks.xlsx` (6 sheets), `output/amx_buybacks_chart.png`, `output/email_preview.html` |

### ⚠ BLOCKED — two settings only the owner can create

The weekly Action and the email are **built, tested and committed, but NOT
pushed and NOT live.** Neither GitHub setting they need exists (verified via
the API: both `total_count: 0`):

| Create in repo Settings → Secrets and variables → Actions | Kind | Name | Value |
|---|---|---|---|
| **Secrets** tab | secret | `EMAIL_APP_PASSWORD` | a Gmail **app password** |
| **Variables** tab | variable | `FROM_EMAIL` | `ibotatom@gmail.com` |

Pushing first would schedule a job that fetches, verifies and commits fine and
then **fails at the email step every Saturday**. Held back deliberately.

### Published

**PRIVATE repo, live since 2026-08-05:**
<https://github.com/rafaelxoliver4-art/amx-buyback-tracker>

**9 commits, full history, no squash.** Local and remote HEAD both
`12404ef`. 371 files including all 342 PDFs. Verified `"isPrivate": true`
**before** any code was pushed and again after.

Not done by instruction: **no Actions, no workflow file, no email, no repo
secret** — all verified absent on the remote. No token, password or SSH key
was ever requested, created, read or stored; the owner authenticated `gh`
themselves.

### THE NINE RULINGS — all settled

Full text and rationale in CONTEXT §11.

| # | Ruling | Status |
|---|---|---|
| 1 | Full backfill **stands**; `display.start_year` is a view (reverses Q2) | **Done** |
| 2 | Revisit trigger corrected to **seam measurability** | **Done** |
| 3 | Row-count guard **ratcheted** to a high-water mark | **Done** |
| 4 | **Ship the scraped figures**; the owner's 11 declared errors stand | **Standing policy** |
| 5 | The five additions are confirmed **by hand**; no AGM scraper | **Settled** |
| 6 | 2023-03-17 is a **permanent** floor for the derived series | **Settled** |
| 7 | PDFs **stay committed**, 100 MB revisit (reverses the gitignore decision) | **Done** |
| 8 | Programme-**reduction** guard, band calibrated from observed data | **Done** |
| 9 | Chart labels thinned beyond 24 points, extremes kept | **Done** |

**Two reversals**, both recorded explicitly in CONTEXT §11: the full backfill
stands, and the PDFs stay committed.

**Nothing moved.** Both acceptance fixtures are byte-identical to Cycle 1 and
every workbook cell is unchanged.

---

## Cycle 3 — 2026-08-05 — the weekly Action and the email (built, NOT live)

### Handed off

Make the tracker run itself weekly on GitHub and email the owner the refreshed
workbook, chart and YTD table. After this cycle the remote is the live copy.

### What came back

**Status: everything buildable is built, tested and committed. NOTHING WAS
PUSHED and no run was triggered — two of the three pre-reqs are missing.**

#### The pre-req check stopped the cycle short

| Pre-req | Result |
|---|---|
| Repo exists, private, history pushed | ✅ 10 commits, `isPrivate: true` |
| Secret `EMAIL_APP_PASSWORD` exists | ❌ **missing** — `actions/secrets` returns `total_count: 0` |
| Variable `FROM_EMAIL` = ibotatom@gmail.com | ❌ **missing** — `actions/variables` returns `total_count: 0` |

Not a permissions artefact: the token carries `repo` and `workflow` scope, so
it can read secret *metadata* (names, never values). They genuinely do not
exist. Existence was all that was checked — no attempt was made to read a
value, and none can be.

**So the workflow was not pushed.** Pushing it would have put a job on the
Saturday schedule that fetches, verifies and commits correctly and then
**fails at the email step every week**. Everything else was built, because
none of it needs a credential — the dry run is designed to work without one.

#### What was built

- **`config/email.yaml`** — the whole email shape. Recipient, SMTP host/port,
  both subject templates, attachments, and the two env **names**. No value,
  no password, no default.
- **`config/schedule.yaml`** — `enabled: true`, `cron: "0 12 * * 6"`, with the
  timezone reasoning written out: GitHub cron is UTC; BMV files ~17:30 Mexico
  City (UTC-6 year round, no DST since 2022), so Friday's report is public by
  ~23:30 UTC Friday, and Saturday noon UTC is ~12.5 h later — 09:00 in São
  Paulo.
- **`src/send_email.py`** — HTML body in the required order: headline, chart
  **embedded by CID**, YTD table read straight from the workbook's YTD sheet,
  then ALERTs prominent and INFO quiet. `--dry-run` writes
  `output/email_preview.html` and works with no credentials at all.
- **`.github/workflows/weekly.yml`** — schedule + `workflow_dispatch`,
  `contents: write`, a concurrency group, and the gate.
- **`tests/test_workflow.py`** — 14 new tests (70 total).

#### The gate

`fetch → parse → build → VERIFY → commit → email`, and **only verify can stop
the job.** If either fixture fails: no commit, no email, non-zero exit, and
GitHub's failed-run notification is the alarm.

`fetch`, `parse` and `build` are `continue-on-error` **on purpose**. They exit
non-zero when they raise an ALERT, and an ALERT is a data condition the owner
must *see* — not a reason to kill the job and send nothing. A non-success
outcome is injected into the email as a prominent ALERT via a new `--notice`
flag, which exists because `send_email.py` builds its own fresh run log and
cannot otherwise see what earlier steps did.

Tests assert the gate is not `continue-on-error`, and that both the commit and
the email come *after* it.

#### Credential hygiene

The password is read from the environment only — no config value, no default,
no literal. The SMTP call reports the exception **class and nothing else**,
because `smtplib` puts the server's reply into the exception args and a reply
can quote the credential it rejected.

**The test that matters** drives a failing login against a fake server that
echoes the password back, then asserts the secret reaches **neither stdout,
stderr, the run log on disk, nor the alert list** — and that the failure is
still reported. Another test greps every file in `src/` for an address or SMTP
host literal.

#### The dry run (step 5a)

Ran with **no credentials in the environment**. Produced
`output/email_preview.html`, 7,256 bytes. Verified: section order correct
(headline → chart → YTD → alerts → notices → footer), headline reads *"AMX
bought back MXN 173 mn · 8.0 mn shares · average MXN 21.61"*, the YTD table
matches the workbook row for row including the TOTAL, **no ALERT block** (a
clean run), and the **five ruling-5 notices render as a quiet footnote**
exactly as intended. No credential-shaped string anywhere in it.

#### Steps 5b–5d NOT done

The manual `workflow_dispatch` run, the run-log inspection and the
Action-pushed commit all require the workflow to be live, which requires the
two settings. **No run URL, no Action commit, and no runner-vs-local
comparison can be reported this cycle** — including whether BMV rate-limits a
datacentre IP, which is genuinely unknown until a real runner tries it.

#### The 60-day question — researched, and the honest answer is "undocumented"

- The rule **applies here.** GitHub's docs say *"In a public repository…"*, but
  the community reports it hitting private repos too and the docs state no
  exemption. Assume it applies.
- **Only new commits** reset the timer — not tags, releases, issues or PRs.
- **Whether a `github-actions[bot]` commit via `GITHUB_TOKEN` resets it is not
  documented by GitHub**, and the community threads asking got no staff
  answer. Unresolved, not merely unread.

**Do not add a dummy-commit keepalive**: the most popular tool for it,
`gautamkrishnar/keepalive-workflow`, has been **disabled by GitHub Staff for a
ToS violation**. Manufacturing activity to game the timer is not safe.

GitHub emails a warning before disabling and re-enabling is one click — so the
practical answer is: **if the weekly email ever stops arriving, check the
Actions tab first.** If bot commits turn out not to count, the clean fix is
pushing with a fine-grained PAT, which needs a new owner-created secret and is
not approved.

### Next

Owner creates the two settings; then push the workflow, trigger one manual
run, and confirm the log is clean and free of the secret. Cycle 3 is otherwise
complete.

---

## Cycle 2 — 2026-08-05 — the nine rulings settled, and the first push

### Handed off

Implement the four fixes the rulings call for, record all nine in the standing
brief, then create the private GitHub repo and push.

### What came back

**Status: complete. All nine steps done, including the gated first push.**

**No reported figure moved.** Both acceptance fixtures produce output
**byte-identical** to Cycle 1, and every cell of Raw, Weekly, Monthly and YTD
is unchanged. 56 tests pass (41 → 56; 15 new).

#### Ruling 1 — the display window

`display.start_year` in `config/sources.yaml`. `null` = all history, `2026` =
2026 onward. It filters the **Weekly, Monthly, YTD and chart output only**.

Two ordering details make it safe: the derivation runs **before** the filter,
so the earliest visible period keeps the buyback measured from its hidden
predecessor; and the YTD denominator is read from the **unfiltered** frame, or
a 2026 window would hide the 31-Dec-2025 row it comes from.

Four tests, including one that asserts `data/raw_reports.csv` is
**byte-identical** with the filter set, and one that asserts a filtered row's
`buyback_mxn` and `shares_bought` match the unfiltered frame exactly.

#### Ruling 3 — the row-count ratchet

High-water mark in `data/listing_rowcount_highwater.json`, **committed, not
gitignored**. Gitignored, the first run after a fresh clone would start from no
mark, accept whatever the listing returned and adopt a shrunken history as its
baseline — exactly the failure the ratchet prevents. Same reasoning as the
ledger.

Three tests: a shrink alerts and does **not** lower the mark; a new high raises
it; and a shrink that persists keeps alerting — the specific weakness of the
previous-run version, where one bad day silently became the new normal.

#### Ruling 8 — the programme-reduction guard, and the band I chose

**Observed range, measured rather than assumed** (177 weekly + 41 monthly
periods, 2023-03..2026-08):

| | weekly | monthly |
|---|---|---|
| min | 14.17 | 14.40 |
| median | 16.40 | 16.26 |
| max | 24.38 | 22.75 |

Worst legitimate deviation from the trailing-12 median: **1.316×**
(2025-11-28, 21.10 against a median of 16.04 — a genuine move as the stock
re-rated, not an error).

| Parameter | Chosen | Why |
|---|---:|---|
| `min_mxn` | **5.0** | 2.8× below the observed minimum. Only an order-of-magnitude or sign error reaches it; no market move will. |
| `max_mxn` | **60.0** | 2.5× above the observed maximum and far above any plausible AMX B price. A backstop for when the trailing median has itself drifted. |
| `max_ratio_vs_median` | **2.0** | Against a worst legitimate 1.316×, a **52% margin**. The sharp instrument; the absolute band is the blunt one. |
| `zero_share_spend_alert_mxn` | **1,000,000** | A reduction with no shares retired divides by zero and produces no price, so the band alone would miss it entirely. |

**I checked the Architect's suggested 5.0 / 60.0 / 2.0 against the data rather
than taking them on faith, and they hold up** — every one clears the observed
range with margin to spare. The one thing they did not cover was the
divide-by-zero case, which is why the fourth parameter exists.

Five tests: silent across the whole real series (a guard that cries wolf is
worse than none), catches a gross cancellation, catches a smaller one that
stays inside the absolute band but doubles the median, catches cash-out with
zero shares, and asserts the band is wider than everything observed.

#### Ruling 9 — chart label density

`label_every_n: auto` in `config/chart.yaml`: every point up to 24, every
second beyond, with **first, last, min and max always kept**. At 41 months
that is **22 of 41** labels. No hex colour entered `build_chart.py`; the grep
test still passes.

Both renders agree. openpyxl does not model OOXML's `<c:delete>` on an
individual data label, so the dropped points get an explicit `showVal=False`
instead — which *is* modelled and blanks them just the same. Verified by
reading the saved workbook back: 19 of 41 points blanked, 22 shown.

#### Ruling 7 — .gitignore

The PDFs stay committed; no history rewritten. `.gitignore` records the
reversal, the reason (they are the evidence every figure re-derives from), and
a **100 MB revisit threshold**.

**I had the size wrong and corrected it.** I wrote "~4 MB" into three files;
the real corpus is **31.2 MB across 342 PDFs, mean 94 KB**. The "~4 MB" was
the pre-backfill figure — 39 PDFs — carried forward without re-measuring after
the backfill added ~300 more. The ruling is unaffected (31 MB is unremarkable
for a git repo), but the revisit arithmetic changes materially: 100 MB is
~1,094 reports, i.e. **~18 more years** at the current ~60/yr selection rate,
not the ~30 years I first wrote — and only **~4 years** if selection ever
widened to every trading day.

Also found by the pre-publish inspection: **`data/backfill_run.log` (0.21 MB)
was tracked.** It is a transient run log of the same class as
`data/run_log.txt`, which has always been ignored — an oversight from Cycle 1.
It is now gitignored and untracked going forward. History was **not**
rewritten, so the existing copy stays in past commits.

#### Rulings 2, 4, 5, 6

- **2 — the revisit trigger was wrong**, and is corrected in CONTEXT §11.
  "Revisit if additions stop being round" was *already false when written*:
  2023-04-14 is 1,586,249,981, a reset to a round total rather than a round
  increment, and three other seams carry a few pesos of drift. Taken literally
  it fired immediately. **The correct trigger is seam measurability** — an
  addition pinned to the peso by two consecutive reports is better evidence
  than a published resolution, round or not.
- **4 — ship the scraped figures.** Already the standing rule (CONTEXT §9) and
  restated as a guardrail on this cycle. The 11 declared errors in the owner's
  table stand as declared.
- **5 and 6 — no ruling was stated in this task.** Confirming the five
  programme additions, and whether the 2023-03-17 series-B floor is permanent,
  remain open. Recorded as open rather than resolved; nothing was invented.

#### How it was verified

1. **The acceptance output was captured before and after**, by `git stash`ing
   the cycle's changes and re-running against the Cycle 1 code. The two files
   are byte-identical.
2. **Every workbook cell was diffed** — Raw (537 rows), Weekly (179), Monthly
   (43) and YTD (12), all four identical cell for cell.
3. The Excel chart was **read back from the saved file** to confirm the label
   thinning survived serialisation, rather than trusting the write.

#### Step 8 — PUBLISH

The first attempt **stopped at the gate**: `gh auth status` reported no
logged-in host, so nothing was created or pushed and no credential was
touched. Diagnosis for the record — `gh` was installed and Windows Credential
Manager still held a token for `rafaelxoliver4-art`, but `gh`'s `hosts.yml`
was missing from every location, so `gh` had no record of being logged in and
the orphaned keyring entry was invisible to it. **The owner ran
`gh auth login` themselves** (browser flow, no token handled here) and it
recreated the config.

| | |
|---|---|
| Repo | <https://github.com/rafaelxoliver4-art/amx-buyback-tracker> |
| Visibility | **PRIVATE** — verified *before* pushing and again after |
| Commits | **9**, full history, no squash, no re-init |
| Sync | local and remote HEAD both `12404ef` |
| Files on remote | **371 blobs**, including all **342 PDFs** |
| Size | ~32 MB working tree, ~64 MB with `.git` |

**Order of operations was deliberate:** the repo was created *without*
`--push`, its `isPrivate` flag confirmed, and only then was the history
pushed. A repo that came out public would have been caught before a single
line of code left the machine.

Verified absent on the remote: **no workflow file, no Action, no repo
secret**, and no `run_log.txt`, `backfill_run.log`, `.env` or anything
credential-shaped. Excluded exactly as `.gitignore` intends.

### Next — Cycle 3

The email body and the weekly unattended run. Both need the Architect's
sign-off on Actions and on an owner-created SMTP secret, neither of which is
approved yet. Rulings 5 and 6 are also still open.

---

## 2026-08-04 — Architect rulings + governance decisions (documentation cycle)

**No code was changed and no build was run.** Nothing in `src/`, `config/`,
`tests/` or `output/` was touched; the fetcher, parser, builder and acceptance
test were not run. Only the two living files were edited — and, in the
2026-08-05 addendum, renamed to `amx-buyback-tracker-CONTEXT.md` and
`amx-buyback-tracker-PROGRESS.md`.

### What was decided

- **Q1 — AGM confirmation: not automated.** A second scraper for a
  once-a-year fact is out of scope; the 2026-04-23 / MXN 10,000,000,000 figure
  stands as measured, because the inter-report seam pins it to the peso.
- **Q1 alerting** — an addition already in config with
  `confirmed_by_owner: false` emits **one INFO line**, not an ALERT; a **new**
  unexplained rise still ALERTs and gets probed; a rise nothing explains still
  leaves the buyback negative and ALERTs.
- **Q2 — Backfill depth: 2026 only.** 2021–2025 can be added later with one
  more run of the existing selector, no re-architecting.
- **Q3 — Listing growth: no cap.** Two guards instead: ALERT over 10 MB, and
  ALERT if the row count drops below the highest ever recorded. Revisit the
  cap at 5,000 rows.
- **Q4 — Empty weeks: emit an explicit row** — zero buyback, zero shares,
  balances carried forward, `avg_price` blank, `no_report: true`.
- **Q5 — Workbook date: the true BMV report date**, plus a `Month` column on
  Monthly for chart labelling.
- **Q6 — Weekly `Date` stays the report date**, plus `ISO Week` and
  `Week Ending (Sun)`.
- **Governance — the first push is approved:** a **private** GitHub repo named
  `amx-buyback-tracker`, **not yet executed**, gated on the acceptance test
  passing. Actions, email and secrets remain unapproved and unbuilt.
  Authentication is the owner's to arrange: if `gh auth status` is not already
  authenticated when the push cycle runs, **stop and report** — never request,
  create, read or store a credential.

### These rulings arrived after Cycle 1 had already shipped

The task briefing for this cycle describes the repo as it stood at the end of
Cycle 0 and says the next cycle is "the Cycle 1 build — styling, the bar +
%-line chart, the YTD table, and the gated first push". **Cycle 1 was built on
2026-08-05**: the styling, the chart, the YTD table and the full backfill are
all delivered, committed and passing. The rulings have therefore been recorded
as history, each annotated with where it now stands, rather than as pending
spec. Writing "not yet implemented" against five already-shipped, tested
behaviours would have made the standing brief wrong.

Where a ruling **is** already built exactly as stated — Q1's alerting, Q4, Q5,
Q6 — it is marked implemented and nothing changed. Three items do **not**
match, and are flagged rather than resolved:

1. **Q2 conflicts with what was delivered.** This ruling says 2026 only;
   Cycle 1's briefing said "backfill the FULL listing history, 2021-08-03 to
   present", and it did — 259 PDFs, ledger 39 → 536 rows. The shipped chart
   starts **Apr-2023** and already spans three years, so the ruling's stated
   consequence ("the chart starts at Jan-2026 … will not match the owner's
   3-year reference chart") no longer holds. Nothing was deleted or rolled
   back — that is a data decision, not a documentation one.
2. **Q3 is built, but with the weaker comparison.** The guard compares against
   the **previous run's** row count, not the **highest ever**; a one-off shrink
   would be adopted as the new baseline. Recorded as spec in CONTEXT §7, not
   built. The 5,000-row revisit was not recorded anywhere before now.
3. **Q1's own revisit trigger has already fired.** The ruling says to revisit
   automated AGM scraping "only if additions ever stop being round numbers".
   Cycle 1 found they already have: 2023-04-14 is **1,586,249,981**, a reset to
   a round *total* of 20.0bn rather than a round increment, and three of the
   other four seams carry a few pesos of BMV drift.

### Addendum, 2026-08-05 — the living files are renamed

`CONTEXT.md` → `amx-buyback-tracker-CONTEXT.md`, `PROGRESS.md` →
`amx-buyback-tracker-PROGRESS.md`, both via `git mv` so history follows them.
Seven references across five files were updated in the same pass: both H1
headings, the header link in this file, the repo-contents list and the
open-question pointer in CONTEXT, the two README links, the repo tree in this
file, a comment in `config/chart.yaml` and a pointer in `docs/recon_notes.md`.
A repo-wide grep for the bare old names now returns nothing.

`config/chart.yaml` and `docs/recon_notes.md` were edited despite this being a
documentation cycle: the addendum explicitly directs the reference sweep at
`config/*.yaml`, `src/*.py` and `tests/*`. Both changes are comment text only,
no behaviour.

Sibling projects under `projects\` are unchanged. The convention applies to
them too, but each migrates by its own task.

### Also flagged, for the push cycle

The governance ruling gitignores `data/raw/*.pdf`, but the repo **commits**
them today and `.gitignore` carries an explicit note saying that is
deliberate. 331 PDFs (~4 MB) are already in git history from Cycles 0 and 1,
so adding the rule later would stop tracking new PDFs without removing the
existing ones. `.gitignore` was left untouched — it belongs to the push spec,
and building the push spec is a later cycle.

### Next

Settle the three conflicts above — Q2 scope above all, since it decides
whether the delivered backfill and chart stand. Then the push cycle: the
private repo, gated on the acceptance test, with authentication already
arranged by the owner.

---

## Cycle 1 — 2026-08-04/05 — full backfill, workbook styling, and the chart

### Handed off

Extend the series back to the start of the listing, make the workbook
presentable, build the buybacks chart, and implement six Architect rulings.
Still local: no remote, no Actions, no email.

### What came back

**Status: complete. Both acceptance fixtures PASS. 41/41 tests pass.**

Neither `fetch_reports.py`'s listing/parse logic nor `parse_report.py`'s field
extraction needed changing, as the pre-req required. Three additive changes
were made around them and are called out below.

#### Backfill

| | |
|---|---|
| PDFs downloaded | **259** in the main run, 0 failures, 0 unparsed |
| Elapsed | 16m37s downloading + 11m parsing = **27m42s** |
| Selected | 294 reports across **2021-08-06 → 2026-08-03** |
| Ledger rows | **39 → 492** in the main run (**536** after the investigation downloads below) |
| Listing | 1,255 rows, 958,373 bytes — inside both new guards |

A further ~44 daily PDFs were downloaded while investigating the discrepancies
below (Apr/Jun-2023, Aug-2024). Every one is appended, nothing rewritten.

#### The finding that reshaped the cycle: AMX's share consolidation

**Until 2023-03-10 AMX filed three series — A, AA and L — and no series B at
all.** Series B begins **2023-03-17**. 97 reports carry the old structure.

Cycle 0's "AMX files exactly one serie (B)" was true of 2026 and false of the
history. The design held: the parser already alerted rather than silently
passing, and `ledger_rows` already filtered to B. The old series are now
**declared** in config, stored, summarised once per run, and excluded from the
derived series; two tests assert neither structure leaks across 2023-03-10.

**So the derived series cannot start before 2023-03-17** — there is no B to
chain to. The full backfill still ran and the pre-2023 reports are in the
ledger, but the chart and frames begin Mar-2023. Extending further would mean
deciding how to splice A + AA + L into B. **Open question 1.**

#### Programme additions — all five, with the seam evidence

Each isolated by the same inter-report seam method that dated 2026-04-23:
yesterday's `al presente` versus today's `al último reporte`.

| Date | Amount (MXN) | Prior `al presente` → this `al último` | Reading |
|---|---:|---|---|
| 2023-04-14 | 1,586,249,981 | 18,413,750,019 → **20,000,000,000** | **reset to a round 20.0bn total** |
| 2024-04-29 | 15,000,000,066 | 276,274,141 → 15,276,274,207 | 15.0bn + 66 drift |
| 2024-11-08 | 15,000,000,033 | 3,645,395,812 → 18,645,395,845 | 15.0bn + 33 drift |
| 2025-05-14 | 10,000,000,012 | 9,556,658,919 → 19,556,658,931 | 10.0bn + 12 drift |
| 2026-04-23 | 10,000,000,000 | 11,042,617,352 → 21,042,617,352 | exactly 10.0bn |

All five `confirmed_by_owner: false`, each with a `notes:` field. **Open
question 2.**

**A real bug, found by the guardrail.** The first pass rounded 2023-04-14 to
1.5bn and left a **negative buyback** — the "never absorb a rise" rule
refusing to paper over a wrong answer. The cause: the code only trusted an
exact seam *if it was already round*. But 2023-04-14 is a **reset to a round
total**, not a round increment. An exact seam is a measurement; rounding is
now only a fallback for when the seam cannot be measured. The three
few-peso residues (+66/+33/+12) are the same defect class as the recorded
2026-04-24 +26 MXN.

**How it was proved end to end:** after fixing the logic the four
auto-proposed entries were **deleted from the config** and the probe re-derived
all of them from scratch, arriving at the exact seams above.

#### Acceptance test

**2026 fixture (Cycle 0, untouched): PASS** — all 8 rows and the YTD total to
the peso, unchanged. A test asserts that fixture's values are still the
original ones.

**Full-history fixture (May-2023 → Dec-2025): PASS — 32/32 rows.**

Measured **on the owner's own dates**, straight off the ledger, each period
deriving from the previous fixture row. The shipped monthly frame uses
month-end reports (ruling 5) and the owner's early-2023 rows do not; comparing
across that confused a date question with a value one. Once separated:

- **21 rows match exactly** — remanente, shares outstanding and shares bought
  to the peso/share, avg price to 2dp.
- **2 date differences**, reported not failed: the owner's `27-Jun-2023` is the
  **26-Jun** report (shares 63,167,000,000 matches exactly), and `30-Oct-2024`
  is the **31-Oct** report.
- **11 declared errors in the owner's table**, from four root causes, each
  recorded individually with evidence in the fixture — never a blanket
  tolerance, so a new break still fails.

| Owner's figure | Scraped | Diagnosis |
|---|---|---|
| 2023-05-30 buyback 485 mn | **495 mn** | shares bought (25,775,000) and both balance columns reconcile exactly, so only column C is wrong; their 18.83 avg was computed from it |
| 2023-06-27 remanente 18,970,488,531 | **18,979,488,531** | single digit; explains Jun **and** Jul buybacks and avg prices |
| 2024-03-27 remanente ...485 | **...414** | 71 MXN slip; date and shares match exactly |
| 2024-04-30 remanente 15,029,**3**36,004 | **15,029,9<br>36,004** | single digit, 600,000 MXN |
| **2024-09-30 buyback 1,521 mn / 95.2 mn sh** | **1,086 mn / 68.0 mn sh** | **the owner's Sep row re-counts most of August** |

The last is material and worth the Architect's attention. Both balance columns
match the 30-Sep PDF exactly, and so does the 30-Aug row it should measure
from. No August report reproduces the owner's figure. Decisive check: the true
31-Jul → 30-Sep window is **1,630,947,310 MXN / 102,000,000 shares**; scraped
Aug + Sep (545 + 1,086 = 1,631 mn / 102.0 mn) **ties to it exactly**, while the
owner's (545 + 1,521 = 2,066 mn / 129.2 mn) **overstates it by 435 mn /
27.2 mn**.

**No scraped figure was adjusted to fit, and neither fixture's values were
edited to make anything pass.**

#### Test output

```
$ python -m pytest tests -q
.........................................                    [100%]
41 passed in 102.81s
```

20 new tests in `tests/test_series.py` covering the six rulings: label
formats, ISO-week arithmetic, empty-period filling on synthetic frames, the
built weekly frame having no gaps at all, "one notice per run, severity INFO",
every unconfirmed addition having `notes:`, the listing guards, "no cap"
staying absent from config, the YTD total being weighted rather than a mean of
means, the chart config holding every style value, and a grep asserting **no
hex colour appears in `build_chart.py`**. Plus three rewritten integrity tests
for the share consolidation.

#### The chart

`output/amx_buybacks_chart.png` — 41 months, Apr-23 → Aug-26. Tan columns on
the primary axis, dark-brown line with white-filled circle markers on a fully
hidden secondary axis, 45°-rotated `0.00%` labels above each point,
45°-rotated month labels, no gridlines, no plot border, legend bottom centre.
Every value from `config/chart.yaml`.

**How the native Excel chart differs from the PNG:**

| | |
|---|---|
| **Data-label rotation** | requested via `txPr`, but Excel's own renderer is the authority and it does not always honour rotation on a line series' labels. The PNG is the reference. |
| **Marker fill/border** | set explicitly, but Excel may substitute theme colours depending on version. |
| **Hidden secondary axis** | `delete=True` hides the labels and ticks; Excel still reserves a sliver of plot width for it, so the plot area is marginally narrower than the PNG's. |
| **Gap width** | 40 in both, but Excel and matplotlib compute bar width from it slightly differently, so bars are a hair wider in Excel. |

These are recorded in `chart.yaml → excel.known_limitations`. Accepted, not
fought, as instructed.

#### Additive changes around the protected modules

Three, none touching listing/parse logic or field extraction:

1. `fetch_inventory` gained the two ruling-3 guards (wrapped around the
   existing parse, which is unchanged).
2. `parse_all` gained the declared-historical-series branch, a richer return
   value, and the already-in-ledger skip.
3. `RunLog` gained structured `notices` so the Alerts sheet has something to
   render.

#### Things found along the way

- **`bar + line` does not build an openpyxl combo chart.** `__add__` requires
  both operands to be the same class and raises `TypeError: Cannot combine
  instances of different types`. The idiom is in-place `bar += line`. The
  first build lost both charts to this; the PNG now renders first, in its own
  guard, so a native-chart failure can never cost the PNG or the workbook.
- **Every addition probe re-parsed all 300+ PDFs** — about five minutes each,
  four probes. `parse_all` now skips PDFs already in the ledger, which is
  sound because the ledger is append-only, and the probes dropped to seconds.
- **The empty-week rule never fires.** Every ISO week from 2023-03-17 to
  2026-08-03 has a report. The rule is held by unit tests on synthetic frames
  plus a test that the real weekly frame has no gaps.
- **The Alerts sheet is clean** — five INFO notices, one per unconfirmed
  addition, and zero ALERTs.

### Fragility register — changes since Cycle 0

Cycle 0's ten risks all stand. Ruling 3 closed the "unbounded listing" gap
(#1) with guards rather than a cap. Two new entries:

| # | Risk | Likelihood | What happens today |
|---|---|---|---|
| 11 | **A fourth programme addition style.** We have seen a round increment and a reset to a round total. A third pattern (e.g. a partial cancellation *reducing* the remanente) would not be recognised. | low | a fall in the remanente reads as buyback and would be **silently wrong** — nothing detects it. See open question 4. |
| 12 | **A future series change.** AMX consolidated once already; the cutoff is a fixed date in config. | low | a new serie ALERTs and lands in the ledger; the derived series silently stays on B |

### Open questions for the Architect

1. **The series-B floor.** The derived series cannot start before
   **2023-03-17** — before that AMX filed A, AA and L and no B. The owner's
   table starts May-2023, so nothing is currently lost. Should Cycle 2 attempt
   to splice the pre-2023 series into a continuous history, or is Mar-2023 the
   permanent start?
2. **Confirming five programme additions.** All five are
   `confirmed_by_owner: false` and each emits an INFO every run by design.
   Confirming them needs the AGM resolutions, which are not in the recompras
   PDFs. Ruling 1 said not to scrape Eventos Relevantes this cycle — should
   Cycle 2, or will you confirm them by hand?
3. **The owner's Sep-2024 row overstates buybacks by 435 mn.** Our figure ties
   exactly to the two PDFs either side. Confirm we ship the scraped figure —
   and note it changes any published FY2024 total by that amount.
4. **A programme *reduction*.** Additions are handled; a cancellation that
   *lowered* the remanente would be indistinguishable from a buyback and would
   pass silently. Worth a guard (e.g. alert when implied avg price falls
   outside a sane band)?
5. **Chart density.** 41 months of 45°-rotated labels collide in the busy
   stretches. Match-the-house-style says leave it. Label every other point, or
   keep as is?
6. **Cycle 0's open questions 4, 5 and 6 are now answered by rulings 4, 5 and
   6.** Question 3 (listing cap) is answered by the guards. Nothing outstanding
   from Cycle 0.

### Next — Cycle 2

The email body and the weekly unattended run. The YTD sheet is already built
to be the email table.

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
├── amx-buyback-tracker-CONTEXT.md   amx-buyback-tracker-PROGRESS.md
├── README.md  requirements.txt  .gitignore
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

> **ALL SIX ARE ANSWERED — see the 2026-08-04 rulings in CONTEXT §11.** Kept
> here as the historical record of what Cycle 0 asked. **The text below
> describes behaviour as it was on 2026-08-03 and is superseded in two
> places:** question 1's "raises an ALERT on every run" became **one INFO line
> per run** under ruling Q1, and question 5's open choice of date was settled
> by ruling Q5 in favour of the true BMV report date. Nothing here was
> reworded — the markers are the correction.

1. **Confirm the 10.0bn programme addition.** It is dated **2026-04-23** and
   sits in the config as `confirmed_by_owner: false`, which raises an ALERT on
   every run by design. *(Superseded by ruling Q1: it now emits one INFO line
   per run, not an ALERT.)* Confirming it needs the AGM resolution — which is
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
