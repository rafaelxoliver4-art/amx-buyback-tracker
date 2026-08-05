"""The buybacks chart, rendered twice from one config.

Every colour, size, rotation and gap width comes from config/chart.yaml.
Nothing of the sort is hardcoded here.

    render_png(...)  -> output/amx_buybacks_chart.png
                        matplotlib. The pixel-accurate match to the owner's
                        house style, and what Cycle 2 will email.

    add_excel(...)   -> the "Chart" sheet of the workbook
                        a NATIVE openpyxl combo chart, so it is live in the
                        file. OOXML/openpyxl cannot express three of the
                        properties matplotlib can; they are listed in
                        chart.yaml under excel.known_limitations and reported
                        rather than silently absorbed.

Combo: COLUMNS = buybacks in MXN mn (primary axis)
       LINE + MARKERS = % shares outstanding (secondary axis, fully hidden)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_config, repo_path  # noqa: E402


# --------------------------------------------------------------------------
def label_indices(dl: dict, values: list[float]) -> set[int]:
    """Which points on the % line get a data label (ruling 9).

    A stride thins the crowd; first, last, min and max are always kept so the
    endpoints and the extremes survive whatever the stride.
    """
    n = len(values)
    if n == 0:
        return set()
    every = dl.get("label_every_n", 1)
    if every == "auto":
        every = dl.get("auto_stride", 2) if n > dl.get("auto_threshold", 24) else 1
    every = max(1, int(every))

    keep = set(range(0, n, every))
    always = dl.get("always_label") or []
    if "first" in always:
        keep.add(0)
    if "last" in always:
        keep.add(n - 1)
    if "min" in always:
        keep.add(min(range(n), key=lambda i: values[i]))
    if "max" in always:
        keep.add(max(range(n), key=lambda i: values[i]))
    return keep


def chart_rows(cfg: dict, ccfg: dict, monthly: list[dict]) -> list[dict]:
    """The plotted subset: every derived month (the anchor has no buyback)."""
    src = ccfg["source"]
    rows = [r for r in monthly if r.get(src["bar_key"]) is not None]
    if not src.get("include_no_report_rows", True):
        rows = [r for r in rows if not r.get("no_report")]
    return rows


# --------------------------------------------------------------------------
# matplotlib - the pixel-accurate render
# --------------------------------------------------------------------------
def render_png(cfg: dict, ccfg: dict, monthly: list[dict], log=None) -> Path | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    rows = chart_rows(cfg, ccfg, monthly)
    if not rows:
        if log:
            log.alert("chart: no plottable rows - PNG not written", code="CHART_EMPTY")
        return None

    src, out = ccfg["source"], ccfg["output"]
    b, ln, ax_c, lg, fnt = ccfg["bars"], ccfg["line"], ccfg["axes"], ccfg["legend"], ccfg["font"]

    x = list(range(len(rows)))
    labels = [r[src["x_key"]] for r in rows]
    bar_vals = [(r[src["bar_key"]] or 0) / src["bar_divisor"] for r in rows]
    line_vals = [(r[src["line_key"]] or 0) for r in rows]

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = list(fnt["family"])

    fig, ax = plt.subplots(
        figsize=(out["width_px"] / out["dpi"], out["height_px"] / out["dpi"]),
        dpi=out["dpi"],
    )
    fig.patch.set_facecolor(out["facecolor"])
    ax.set_facecolor(out["facecolor"])

    # ---- COLUMNS ----------------------------------------------------------
    # Excel's "gap width" is the gap as a % of bar width, so bar = 1/(1+gap).
    width = 1.0 / (1.0 + b["gap_width_pct"] / 100.0)
    ax.bar(x, bar_vals, width=width,
           color=b["color"],
           edgecolor=b["edge_color"] or "none",
           linewidth=b["edge_width"],
           zorder=b["z_order"],
           label=b["label"])

    # ---- primary Y --------------------------------------------------------
    yp = ax_c["y_primary"]
    top = yp["max"] if yp["max"] is not None else max(bar_vals) * (1 + yp["headroom_pct"] / 100.0)
    ax.set_ylim(yp["min"], top)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.tick_params(axis="y", labelsize=yp["label_font_size_pt"],
                   colors=yp["color"], length=ax_c["x"]["tick_length_pt"])

    # ---- LINE + MARKERS on the secondary axis -----------------------------
    ys = ax_c["y_secondary"]
    ax2 = ax.twinx()
    ax2.set_facecolor("none")
    mk = ln["marker"]
    ax2.plot(x, line_vals,
             color=ln["color"], linewidth=ln["width_pt"], linestyle=ln["style"],
             marker=mk["symbol"], markersize=mk["size_pt"],
             markerfacecolor=mk["face_color"],
             markeredgecolor=mk["edge_color"],
             markeredgewidth=mk["edge_width_pt"],
             zorder=ln["z_order"], label=ln["label"], clip_on=False)
    ax2.set_ylim(ys["min"], max(line_vals) * (1 + ys["headroom_pct"] / 100.0) or 1)

    # secondary axis COMPLETELY HIDDEN - no line, no labels, no ticks
    if not ys["visible"]:
        ax2.set_yticks([])
        ax2.yaxis.set_visible(False)
        for s in ax2.spines.values():
            s.set_visible(False)

    # ---- line data labels -------------------------------------------------
    dl = ln["data_labels"]
    if dl["show"]:
        keep = label_indices(dl, line_vals)
        for xi, v in zip(x, line_vals):
            if xi not in keep:
                continue
            ax2.annotate(_pct(v, dl["number_format"]),
                         xy=(xi, v),
                         xytext=(0, dl["offset_pt"]),
                         textcoords="offset points",
                         rotation=dl["rotation_deg"],
                         rotation_mode="anchor",
                         ha="left", va="bottom",
                         fontsize=dl["font_size_pt"], color=dl["color"],
                         zorder=ln["z_order"] + 1, annotation_clip=False)

    # ---- X axis -----------------------------------------------------------
    xa = ax_c["x"]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=xa["label_rotation_deg"],
                       ha=xa["label_ha"], fontsize=xa["label_font_size_pt"],
                       color=xa["color"])
    ax.set_xlim(-0.7, len(rows) - 0.3)
    ax.tick_params(axis="x", length=xa["tick_length_pt"], colors=xa["color"])

    # ---- no gridlines, no plot-area border --------------------------------
    ax.grid(ax_c["gridlines"]["show"])
    ax2.grid(False)
    for name, sp in ax.spines.items():
        if name == "bottom":
            sp.set_visible(True)
            sp.set_color(xa["color"])
            sp.set_linewidth(xa["line_width_pt"])
        elif name == "left":
            sp.set_visible(yp["show_line"])
            sp.set_color(yp["color"])
            sp.set_linewidth(yp["line_width_pt"])
        else:
            sp.set_visible(ax_c["plot_area_border"]["show"])

    # ---- legend, bottom centre -------------------------------------------
    if lg["show"]:
        handles = {"bars": ax.get_legend_handles_labels(),
                   "line": ax2.get_legend_handles_labels()}
        hs, ls = [], []
        for key in lg["entries"]:
            h, l = handles[key]
            hs += h
            ls += l
        ax.legend(hs, ls, loc="upper center",
                  bbox_to_anchor=(0.5, lg["y_offset"]),
                  ncol=lg["columns"], frameon=lg["frame"],
                  fontsize=lg["font_size_pt"], labelcolor=fnt["color"])

    path = repo_path(out["png_path"])
    fig.savefig(path, dpi=out["dpi"], bbox_inches=out["bbox_inches"],
                pad_inches=out["pad_inches"], facecolor=out["facecolor"],
                transparent=out["transparent"])
    plt.close(fig)
    if log:
        shown = len(label_indices(dl, line_vals)) if dl["show"] else 0
        log.info(f"chart PNG written: {path} ({len(rows)} months, "
                 f"{labels[0]}..{labels[-1]}; {shown} of {len(rows)} % labels drawn)")
    return path


def _pct(v: float, number_format: str) -> str:
    dp = len(number_format.split(".")[1].rstrip("%")) if "." in number_format else 0
    return f"{v * 100:.{dp}f}%"


# --------------------------------------------------------------------------
# openpyxl - the live workbook chart
# --------------------------------------------------------------------------
def add_excel(cfg: dict, ccfg: dict, wb, monthly: list[dict], log=None):
    """Native combo chart on its own sheet, driven off the Monthly sheet.

    openpyxl combines charts IN PLACE (`bar += line`); `bar + line` requires
    both operands to be the same class and raises.
    """
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.chart.axis import ChartLines
    from openpyxl.chart.label import DataLabel, DataLabelList
    from openpyxl.chart.marker import Marker
    from openpyxl.chart.series import SeriesLabel
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.chart.text import RichText
    from openpyxl.drawing.line import LineProperties
    from openpyxl.drawing.text import Paragraph, ParagraphProperties, RichTextProperties

    xc, src = ccfg["excel"], ccfg["source"]
    b, ln, ax_c, lg = ccfg["bars"], ccfg["line"], ccfg["axes"], ccfg["legend"]
    emu_pt = 12700                       # 1 pt in EMU
    deg = 60000                          # 1 degree in OOXML text rotation units

    ws_m = wb[cfg["workbook"]["sheets"]["monthly"]]
    cols = {c["key"]: i for i, c in enumerate(cfg["workbook"]["monthly_columns"], start=1)}

    rows = chart_rows(cfg, ccfg, monthly)
    if not rows:
        return None
    # the Monthly sheet has a header row; the anchor is its first data row and
    # carries no buyback, so the plotted block starts one row further down.
    first = 2 + (len(monthly) - len(rows))
    last = 1 + len(monthly)

    ws = wb.create_sheet(xc["sheet"])

    def _rot(size_pt: float, rotation: float):
        return RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=None), endParaRPr=None)],
                        bodyPr=RichTextProperties(rot=int(-rotation * deg), vert="horz"))

    # ---- COLUMNS ----------------------------------------------------------
    bar = BarChart()
    bar.type = "col"
    bar.gapWidth = b["gap_width_pct"]
    bar.add_data(Reference(ws_m, min_col=cols[src["bar_key"]], min_row=first, max_row=last),
                 titles_from_data=False)
    bar.set_categories(Reference(ws_m, min_col=cols[src["x_key"]], min_row=first, max_row=last))
    bs = bar.series[0]
    bs.tx = SeriesLabel(v=b["label"])
    bs.graphicalProperties = GraphicalProperties(solidFill=b["color"].lstrip("#"))
    bs.graphicalProperties.line = LineProperties(noFill=True)

    # ---- LINE + MARKERS ---------------------------------------------------
    line = LineChart()
    line.add_data(Reference(ws_m, min_col=cols[src["line_key"]], min_row=first, max_row=last),
                  titles_from_data=False)
    ls = line.series[0]
    ls.tx = SeriesLabel(v=ln["label"])
    ls.smooth = False
    ls.graphicalProperties = GraphicalProperties()
    ls.graphicalProperties.line = LineProperties(
        solidFill=ln["color"].lstrip("#"), w=int(ln["width_pt"] * emu_pt))
    mk = ln["marker"]
    ls.marker = Marker(symbol=mk["excel_symbol"], size=int(mk["size_pt"]))
    ls.marker.graphicalProperties = GraphicalProperties(
        solidFill=mk["face_color"].lstrip("#"))
    ls.marker.graphicalProperties.line = LineProperties(
        solidFill=mk["edge_color"].lstrip("#"), w=int(mk["edge_width_pt"] * emu_pt))

    dl = ln["data_labels"]
    if dl["show"]:
        line.dataLabels = DataLabelList()
        line.dataLabels.showVal = True
        line.dataLabels.numFmt = dl["number_format"]
        line.dataLabels.dLblPos = "t"
        line.dataLabels.showSerName = False
        line.dataLabels.showCatName = False
        line.dataLabels.showLegendKey = False
        line.dataLabels.txPr = _rot(dl["font_size_pt"], dl["rotation_deg"])
        # ruling 9: thin the labels in Excel too, so the two renders agree.
        # openpyxl does not model OOXML's <c:delete> on an individual label,
        # so the dropped points get an explicit showVal=False instead - which
        # IS modelled, and blanks them just the same.
        line_vals = [(r[src["line_key"]] or 0) for r in rows]
        keep = label_indices(dl, line_vals)
        line.dataLabels.dLbl = [
            DataLabel(idx=i, showVal=False, showSerName=False,
                      showCatName=False, showLegendKey=False)
            for i in range(len(rows)) if i not in keep
        ]

    # ---- axes -------------------------------------------------------------
    yp, ys = ax_c["y_primary"], ax_c["y_secondary"]
    bar.y_axis.scaling.min = yp["min"]
    bar.y_axis.numFmt = yp["number_format"]
    bar.y_axis.majorGridlines = ChartLines() if ax_c["gridlines"]["show"] else None
    bar.x_axis.majorGridlines = None
    bar.y_axis.title = bar.x_axis.title = None
    bar.x_axis.txPr = _rot(ax_c["x"]["label_font_size_pt"], ax_c["x"]["label_rotation_deg"])

    # secondary axis: own id, fully hidden
    line.y_axis.axId = 200
    line.y_axis.majorGridlines = None
    line.y_axis.scaling.min = ys["min"]
    line.y_axis.delete = not ys["visible"]
    bar.y_axis.crosses = "max"

    # ---- combine ----------------------------------------------------------
    bar += line                          # IN PLACE - see the docstring
    bar.title = None
    if lg["show"]:
        bar.legend.position = {"bottom": "b", "top": "t",
                               "right": "r", "left": "l"}[lg["position"]]
        bar.legend.overlay = False
    else:
        bar.legend = None
    bar.width = xc["width_cm"]
    bar.height = xc["height_cm"]
    bar.roundedCorners = False

    ws.add_chart(bar, xc["anchor"])
    if log:
        log.info(f"native Excel chart added to sheet {xc['sheet']!r} "
                 f"({len(rows)} months, {rows[0][src['x_key']]}..{rows[-1][src['x_key']]})")
    return ws


# --------------------------------------------------------------------------
def main() -> int:
    """Re-render the PNG from the current ledger without touching the workbook."""
    import build_series
    from common import RunLog

    cfg = load_config()
    ccfg = load_config("chart.yaml")
    log = RunLog(cfg)
    _weekly, monthly = build_series.build(cfg, log, probe=False)
    if not monthly:
        return 1
    return 0 if render_png(cfg, ccfg, monthly, log) else 1


if __name__ == "__main__":
    raise SystemExit(main())
