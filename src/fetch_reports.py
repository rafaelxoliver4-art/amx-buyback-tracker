"""Walk the BMV recompras listing and download the selected PDFs.

The listing at
    /es/emisoras/informcioncorporativa/AMX-6024-CGEN_CAPIT
is server-rendered and contains EVERY row in one response. The "~251 pages"
a browser shows are DataTables client-side pagination (5 rows per page), not
server paging - so one GET builds the whole inventory.

The PDF href is /docs-pub/recompra/recompra_<doc_id>_<seq>.pdf where doc_id is
an opaque incrementing EMISNET document id. It is NOT derivable from the date,
so the listing must be scraped to learn it.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    PoliteSession,
    RunLog,
    check_robots,
    fold,
    listing_url,
    load_config,
    repo_path,
    resolve_date,
    resolve_end_date,
    sha256_bytes,
    utcnow_iso,
)

INVENTORY_FIELDS = ["report_date", "published_at", "asunto", "pdf_url", "doc_id"]


# --------------------------------------------------------------------------
# listing parser (stdlib only - no extra dependency)
# --------------------------------------------------------------------------
class _RecompraListingParser(HTMLParser):
    """Pulls rows out of the accordion section named in config.

    Structure (verified 2026-08-03):
        <li>
          <h2>ADQUISICION DE ACCIONES POR EMISORA (RECOMPRAS)</h2>
          <div class="slide"><table class="table-downloads">
            <tbody><tr>
              <td>31-07-2026 17:31</td><td>Recompras</td>
              <td>...<a href="/docs-pub/recompra/recompra_1579180_1.pdf">...</a></td>
            </tr>...
    """

    def __init__(self, cfg: dict):
        super().__init__(convert_charrefs=True)
        lc = cfg["listing"]
        self.want_heading = fold(lc["section_heading"])
        self.href_prefix = lc["link_href_prefix"]
        self.i_fecha = lc["cell_index_fecha_hora"]
        self.i_asunto = lc["cell_index_asunto"]

        self._in_h2 = False
        self._h2_text: list[str] = []
        self._section_active = False
        self._section_done = False

        self._in_td = False
        self._td_text: list[str] = []
        self._cells: list[str] = []
        self._row_hrefs: list[str] = []
        self.rows: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if self._section_done:
            return
        if tag == "h2":
            self._in_h2, self._h2_text = True, []
        elif self._section_active and tag == "tr":
            self._cells, self._row_hrefs = [], []
        elif self._section_active and tag == "td":
            self._in_td, self._td_text = True, []
        elif self._section_active and tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith(self.href_prefix):
                self._row_hrefs.append(href)

    def handle_endtag(self, tag):
        if self._section_done:
            return
        if tag == "h2":
            self._in_h2 = False
            heading = fold("".join(self._h2_text))
            if self._section_active:
                # a new section heading ends ours
                self._section_active = False
                self._section_done = True
            elif heading == self.want_heading:
                self._section_active = True
        elif self._section_active and tag == "td":
            self._in_td = False
            self._cells.append(" ".join("".join(self._td_text).split()))
        elif self._section_active and tag == "tr":
            if self._row_hrefs and len(self._cells) > max(self.i_fecha, self.i_asunto):
                self.rows.append(
                    {
                        "fecha_hora": self._cells[self.i_fecha],
                        "asunto": self._cells[self.i_asunto],
                        "hrefs": list(self._row_hrefs),
                    }
                )
            self._cells, self._row_hrefs = [], []

    def handle_data(self, data):
        if self._in_h2:
            self._h2_text.append(data)
        elif self._in_td:
            self._td_text.append(data)


def fetch_inventory(cfg: dict, sess: PoliteSession, log: RunLog) -> list[dict]:
    """One GET -> every recompras row ever published for this issuer."""
    url = listing_url(cfg)
    log.info(f"listing: GET {url}")
    resp = sess.get(url)
    if resp.status_code != 200:
        log.alert(f"listing returned HTTP {resp.status_code} - no inventory")
        return []

    lc = cfg["listing"]
    parser = _RecompraListingParser(cfg)
    parser.feed(resp.text)

    rx = re.compile(lc["pdf_filename_regex"])
    base = cfg["http"]["base_url"]
    want_asunto = fold(lc["asunto_expected"])

    inventory, skipped = [], 0
    for row in parser.rows:
        if fold(row["asunto"]) != want_asunto:
            skipped += 1
            continue
        try:
            stamp = dt.datetime.strptime(row["fecha_hora"], lc["fecha_hora_format"])
        except ValueError:
            log.warn(f"unparseable FECHA Y HORA {row['fecha_hora']!r} - skipped")
            continue
        for href in row["hrefs"]:
            m = rx.search(href)
            inventory.append(
                {
                    "report_date": stamp.date().isoformat(),
                    "published_at": stamp.isoformat(timespec="minutes"),
                    "asunto": row["asunto"],
                    "pdf_url": base + href,
                    "doc_id": m.group("doc_id") if m else "",
                }
            )

    inventory.sort(key=lambda r: (r["report_date"], r["published_at"]))
    log.info(f"listing: {len(inventory)} recompras rows ({skipped} non-recompras rows ignored)")
    return inventory


def write_inventory(cfg: dict, inventory: list[dict]) -> Path:
    path = repo_path(cfg["paths"]["inventory_csv"])
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INVENTORY_FIELDS)
        w.writeheader()
        for r in inventory:
            w.writerow({k: r[k] for k in INVENTORY_FIELDS})
    return path


def read_inventory(cfg: dict) -> list[dict]:
    path = repo_path(cfg["paths"]["inventory_csv"])
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------
def select_reports(cfg: dict, inventory: list[dict], log: RunLog) -> list[dict]:
    """Last report of each ISO week + last of each calendar month + anchors."""
    sel = cfg["selection"]
    start = resolve_date(sel["inventory_start"])
    end = resolve_end_date(sel["inventory_end"])

    in_window = [r for r in inventory if start <= dt.date.fromisoformat(r["report_date"]) <= end]

    chosen: dict[str, dict] = {}
    reasons: dict[str, set] = {}

    def take(rec, why):
        chosen[rec["report_date"]] = rec
        reasons.setdefault(rec["report_date"], set()).add(why)

    if sel["rules"].get("last_of_iso_week"):
        buckets: dict[tuple, dict] = {}
        for r in in_window:
            d = dt.date.fromisoformat(r["report_date"])
            buckets[d.isocalendar()[:2]] = r  # inventory is date-sorted
        for r in buckets.values():
            take(r, "last_of_iso_week")

    if sel["rules"].get("last_of_calendar_month"):
        buckets = {}
        for r in in_window:
            buckets[r["report_date"][:7]] = r
        for r in buckets.values():
            take(r, "last_of_calendar_month")

    for anchor in sel.get("anchor_reports") or []:
        month = anchor["month"]
        cands = [r for r in inventory if r["report_date"].startswith(month)]
        if cands:
            take(cands[-1], f"anchor:{month}")
        else:
            log.alert(f"anchor month {month} has no report in the inventory")

    out = [chosen[k] for k in sorted(chosen)]
    for r in out:
        r["selection_reason"] = ",".join(sorted(reasons[r["report_date"]]))
    log.info(f"selection: {len(out)} reports of {len(in_window)} in window {start}..{end}")
    return out


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------
def _known_hashes(cfg: dict) -> set[str]:
    """sha256 of every PDF already on disk - the download cache key."""
    d = repo_path(cfg["paths"]["raw_pdf_dir"] + "/.keep").parent
    return {sha256_bytes(p.read_bytes()) for p in d.glob("*.pdf")}


def download_reports(cfg: dict, sess: PoliteSession, log: RunLog, records: list[dict]) -> list[dict]:
    """Download each record's PDF. Never re-downloads a sha256 we already hold."""
    raw_dir = repo_path(cfg["paths"]["raw_pdf_dir"] + "/.keep").parent
    serie = cfg["issuer"]["expected_series"][0]
    tmpl = cfg["selection"]["raw_pdf_filename_template"]
    have = _known_hashes(cfg)

    out = []
    for rec in records:
        target = raw_dir / tmpl.format(report_date=rec["report_date"], serie=serie)
        if target.exists():
            data = target.read_bytes()
            out.append({**rec, "pdf_path": str(target), "pdf_sha256": sha256_bytes(data),
                        "fetched_at_utc": "", "cached": True})
            continue

        resp = sess.get(rec["pdf_url"])
        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            log.alert(f"download failed {rec['report_date']} {rec['pdf_url']} -> HTTP {resp.status_code}")
            continue

        digest = sha256_bytes(resp.content)
        if digest in have:
            log.info(f"cache hit by sha256 for {rec['report_date']} - not re-storing")
        target.write_bytes(resp.content)
        have.add(digest)
        log.info(f"downloaded {rec['report_date']} -> {target.name} ({len(resp.content)} bytes)")
        out.append({**rec, "pdf_path": str(target), "pdf_sha256": digest,
                    "fetched_at_utc": utcnow_iso(), "cached": False})
    return out


def download_range(cfg: dict, sess: PoliteSession, log: RunLog,
                   start: dt.date, end: dt.date) -> list[dict]:
    """Every DAILY report in [start, end]. Used to isolate a remanente jump."""
    inv = read_inventory(cfg)
    recs = [r for r in inv if start <= dt.date.fromisoformat(r["report_date"]) <= end]
    log.info(f"daily probe: {len(recs)} reports in {start}..{end}")
    return download_reports(cfg, sess, log, recs)


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch AMX recompras PDFs from BMV.")
    ap.add_argument("--inventory-only", action="store_true")
    ap.add_argument("--from-cached-inventory", action="store_true",
                    help="skip the listing GET and reuse data/listing_inventory.csv")
    args = ap.parse_args()

    cfg = load_config()
    log = RunLog(cfg)
    sess = PoliteSession(cfg, log)

    if not check_robots(cfg, sess, log):
        log.alert("robots.txt disallows the paths we need - STOPPED, nothing fetched")
        return 2

    inventory = read_inventory(cfg) if args.from_cached_inventory else fetch_inventory(cfg, sess, log)
    if not inventory:
        log.alert("listing returned ZERO reports - existing data left untouched")
        return 1
    if not args.from_cached_inventory:
        write_inventory(cfg, inventory)

    if args.inventory_only:
        return 0

    selected = select_reports(cfg, inventory, log)
    got = download_reports(cfg, sess, log, selected)
    if not got:
        log.alert("zero PDFs downloaded - existing data left untouched")
        return 1
    log.info(f"fetch complete: {len(got)} reports available locally")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
