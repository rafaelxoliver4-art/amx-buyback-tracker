"""Unit tests for the recompras PDF parser, against saved PDFs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from common import load_config  # noqa: E402
from parse_report import parse_pdf  # noqa: E402

CFG = load_config()
RAW = REPO_ROOT / "data" / "raw"

# Independently verified against the PDFs themselves.
CASES = [
    # (file,                remanente_ult,  remanente_pres, tes_ult,   tes_pres,  circ_ult,      circ_pres)
    ("2026-07-31_B.pdf", 17_106_344_282, 17_040_109_597,   174_000_000,   177_000_000, 59_996_000_000, 59_993_000_000),
    ("2026-01-30_B.pdf", 12_561_463_301, 12_543_444_084, 1_005_100_000, 1_006_100_000, 60_239_900_000, 60_238_900_000),
    # right-aligned bare "0" in the tesoreria column - the case that broke the
    # first (header-label-span) band implementation. Also the programme top-up
    # day: this report OPENS 10.0bn above the previous report's close.
    ("2026-04-23_B.pdf", 21_042_617_352, 20_997_161_389,             0,     2_000_000, 60_170_000_000, 60_168_000_000),
    ("2026-04-24_B.pdf", 20_997_161_415, 20_985_620_942,     2_000_000,     2_500_000, 60_168_000_000, 60_167_500_000),
]


@pytest.mark.parametrize("name,rem_u,rem_p,tes_u,tes_p,cir_u,cir_p", CASES)
def test_parse_known_pdfs(name, rem_u, rem_p, tes_u, tes_p, cir_u, cir_p):
    path = RAW / name
    if not path.exists():
        pytest.skip(f"{name} not downloaded")
    got = parse_pdf(path, CFG)
    assert got["clave"] == CFG["issuer"]["clave"]
    assert got["remanente_ultimo"] == rem_u
    assert got["remanente_presente"] == rem_p

    assert len(got["series"]) == 1, "AMX is expected to file exactly one serie per report"
    blk = got["series"][0]
    assert blk["serie"] == "B"
    assert blk["acciones_tesoreria_ultimo"] == tes_u
    assert blk["acciones_tesoreria_presente"] == tes_p
    assert blk["acciones_circulacion_ultimo"] == cir_u
    assert blk["acciones_circulacion_presente"] == cir_p


@pytest.mark.parametrize("name", [c[0] for c in CASES])
def test_conservation_identity(name):
    """Shares leaving circulation must equal shares entering treasury, and
    both must equal the net of the OPERACIONES table."""
    path = RAW / name
    if not path.exists():
        pytest.skip(f"{name} not downloaded")
    blk = parse_pdf(path, CFG)["series"][0]
    d_tes = blk["acciones_tesoreria_presente"] - blk["acciones_tesoreria_ultimo"]
    d_cir = blk["acciones_circulacion_ultimo"] - blk["acciones_circulacion_presente"]
    assert d_tes == d_cir
    if blk["operaciones_shares"] is not None:
        assert blk["operaciones_shares"] == d_tes


@pytest.mark.parametrize("name", [c[0] for c in CASES])
def test_report_date_is_operation_date(name):
    """FECHA Y HORA in the listing is the AS-OF date, not a publication date:
    the PDF's FECHA DE OPERACION equals the filename's report date."""
    path = RAW / name
    if not path.exists():
        pytest.skip(f"{name} not downloaded")
    got = parse_pdf(path, CFG)
    assert got["fecha_operacion"].isoformat() == name.split("_")[0]
    assert got["fecha_documento"] == got["fecha_operacion"]


def test_overlapping_render_is_separated_not_concatenated():
    """The regression this parser exists for: naive text extraction yields
    '595,999,939,060,000,000,0000' for the 31-Jul acciones-en-circulacion cell.
    The parser must return the correct 59,993,000,000."""
    path = RAW / "2026-07-31_B.pdf"
    if not path.exists():
        pytest.skip("2026-07-31_B.pdf not downloaded")
    blk = parse_pdf(path, CFG)["series"][0]
    assert blk["acciones_circulacion_presente"] == 59_993_000_000
    # and specifically NOT the ghost render of the prior value
    assert blk["acciones_circulacion_presente"] != blk["acciones_circulacion_ultimo"]


def test_all_downloaded_pdfs_parse():
    """Every PDF we hold must parse, or be reported - never silently skipped."""
    pdfs = sorted(RAW.glob("*.pdf"))
    if not pdfs:
        pytest.skip("no PDFs downloaded")
    failures = []
    for p in pdfs:
        try:
            parse_pdf(p, CFG)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{p.name}: {type(exc).__name__}: {exc}")
    assert not failures, "unparsed reports:\n" + "\n".join(failures)
