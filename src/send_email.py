"""Compose and send the weekly buyback email.

CREDENTIAL HANDLING - the rule this module exists to enforce:

    The sender address and the SMTP password are read from the ENVIRONMENT
    and from nowhere else. There is no config value for them, no default, no
    literal, and no fallback. config/email.yaml carries only their NAMES.

    The password is never logged, printed, echoed, written to run_log.txt, or
    allowed into an exception message. Every SMTP call is wrapped so a failure
    reports the exception CLASS and nothing else - smtplib puts server
    responses (which can quote what was sent) into exception args, so the args
    are deliberately dropped rather than formatted.

`--dry-run` writes output/email_preview.html and sends nothing. It works with
NO credentials present at all, which is what makes the body reviewable
locally without ever touching a secret.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import RunLog, load_config, repo_path  # noqa: E402


# --------------------------------------------------------------------------
# credentials - environment only
# --------------------------------------------------------------------------
def read_credentials(ecfg: dict) -> tuple[str | None, str | None]:
    """(sender, password) from the environment. Never from config, never a
    default. Returns (None, None)-ish when absent so --dry-run still works."""
    return os.environ.get(ecfg["from_env"]) or None, os.environ.get(ecfg["password_env"]) or None


def credentials_present(ecfg: dict) -> bool:
    sender, password = read_credentials(ecfg)
    return bool(sender and password)


# --------------------------------------------------------------------------
# body
# --------------------------------------------------------------------------
def _fmt_mxn_mn(v) -> str:
    return "—" if v is None else f"{v / 1_000_000:,.0f}"


def _fmt_sh_mn(v) -> str:
    return "—" if v is None else f"{v / 1_000_000:,.1f}"


def _fmt_px(v) -> str:
    return "—" if v is None else f"{v:,.2f}"


def _fmt_pct(v) -> str:
    return "—" if v is None else f"{v * 100:,.2f}%"


def read_ytd(cfg: dict) -> list[list]:
    """The YTD sheet, straight out of the workbook, so the email and the
    workbook can never disagree."""
    from openpyxl import load_workbook

    path = repo_path(cfg["workbook"]["path"])
    if not path.exists():
        return []
    ws = load_workbook(path, data_only=True)[cfg["email"]["body"]["ytd_sheet"]]
    return [[c.value for c in row] for row in ws.iter_rows()]


def build_html(cfg: dict, latest: dict | None, ytd: list[list],
               notices: list[dict], chart_cid: str | None,
               no_new_reports: bool) -> str:
    ecfg = cfg["email"]
    b = ecfg["body"]
    loud = [n for n in notices if n.get("severity") in b["loud_notice_severities"]]
    quiet = [n for n in notices if n.get("severity") in b["quiet_notice_severities"]]

    css = (
        "font-family:Calibri,'Segoe UI',sans-serif;color:#4A3F35;"
        "font-size:14px;line-height:1.45;max-width:760px;"
    )
    th = ("text-align:right;padding:4px 10px;border-bottom:1px solid #4A3F35;"
          "font-weight:bold;white-space:nowrap;")
    td = "text-align:right;padding:3px 10px;white-space:nowrap;"
    td_l = "text-align:left;padding:3px 10px;white-space:nowrap;"

    p: list[str] = [f'<div style="{css}">']

    # ---- headline --------------------------------------------------------
    if no_new_reports:
        p.append(f'<p style="margin:0 0 14px 0;">{b["no_new_reports_text"]}</p>')
    if latest:
        p.append(
            f'<p style="margin:0 0 6px 0;font-size:16px;">'
            f'<b>Week to {latest["date"]}</b></p>'
            f'<p style="margin:0 0 16px 0;font-size:15px;">'
            f'AMX bought back <b>MXN {_fmt_mxn_mn(latest["buyback_mxn"])} mn</b> '
            f'&nbsp;·&nbsp; <b>{_fmt_sh_mn(latest["shares_bought"])} mn shares</b> '
            f'&nbsp;·&nbsp; average <b>MXN {_fmt_px(latest["avg_price"])}</b>'
            f'</p>'
        )
    else:
        p.append('<p style="margin:0 0 16px 0;">No derived period is available yet.</p>')

    # ---- chart, embedded BY CID -----------------------------------------
    if chart_cid:
        p.append(
            f'<p style="margin:0 0 18px 0;">'
            f'<img src="cid:{chart_cid}" alt="AMX monthly buybacks and % of shares outstanding" '
            f'style="width:100%;max-width:740px;height:auto;border:0;"></p>'
        )

    # ---- YTD table -------------------------------------------------------
    if ytd:
        title = ytd[0][0] if ytd and ytd[0] and ytd[0][0] else "YTD"
        p.append(f'<p style="margin:18px 0 6px 0;font-size:15px;"><b>{title}</b></p>')
        p.append('<table style="border-collapse:collapse;font-size:13px;">')
        header_i = next((i for i, r in enumerate(ytd) if r and r[0] == "Month"), None)
        if header_i is not None:
            p.append("<tr>" + "".join(
                f'<th style="{th}{"text-align:left;" if j == 0 else ""}">{c}</th>'
                for j, c in enumerate(ytd[header_i]) if c is not None) + "</tr>")
            for row in ytd[header_i + 1:]:
                if not row or row[0] is None:
                    continue
                total = str(row[0]).strip().upper() == "TOTAL"
                weight = "font-weight:bold;border-top:1px solid #4A3F35;" if total else ""
                cells = [f'<td style="{td_l}{weight}">{row[0]}</td>']
                cells.append(f'<td style="{td}{weight}">{_fmt_mxn_mn(row[1])}</td>')
                cells.append(f'<td style="{td}{weight}">{_fmt_sh_mn(row[2])}</td>')
                cells.append(f'<td style="{td}{weight}">{_fmt_px(row[3])}</td>')
                cells.append(f'<td style="{td}{weight}">{_fmt_pct(row[4])}</td>')
                p.append("<tr>" + "".join(cells) + "</tr>")
        p.append("</table>")

    # ---- ALERTs: first and prominent ------------------------------------
    if loud:
        p.append(
            '<div style="margin:20px 0 0 0;padding:10px 14px;'
            'border-left:4px solid #C00000;background:#FBF2F2;">'
            f'<p style="margin:0 0 6px 0;color:#C00000;"><b>{len(loud)} ALERT'
            f'{"S" if len(loud) != 1 else ""} — this run needs a look</b></p><ul style="margin:0;padding-left:18px;">'
        )
        for n in loud:
            when = f' <span style="opacity:.7">({n["affected_date"]})</span>' if n.get("affected_date") else ""
            p.append(f'<li style="margin:3px 0;">{n["message"]}{when}</li>')
        p.append("</ul></div>")

    # ---- INFO: last and quiet -------------------------------------------
    # Ruling 5: the five unconfirmed additions appear here EVERY week by
    # design. A footnote, not a warning block.
    if quiet:
        p.append(
            '<p style="margin:22px 0 4px 0;font-size:11px;opacity:.65;">'
            f'{len(quiet)} routine notice{"s" if len(quiet) != 1 else ""}</p>'
            '<ul style="margin:0;padding-left:18px;font-size:11px;opacity:.65;">'
        )
        for n in quiet:
            p.append(f'<li style="margin:2px 0;">{n["message"]}</li>')
        p.append("</ul>")

    p.append(
        '<p style="margin:22px 0 0 0;font-size:11px;opacity:.55;">'
        'Generated from the BMV "Adquisición de Acciones por Emisora (Recompras)" '
        'PDFs. Figures are derived from the two "al presente" fields of each '
        'report; the workbook and chart are attached.</p></div>'
    )
    return "\n".join(p)


# --------------------------------------------------------------------------
# send
# --------------------------------------------------------------------------
def compose(cfg: dict, html: str, subject: str, sender: str,
            chart_cid: str | None) -> EmailMessage:
    ecfg = cfg["email"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ecfg["to"]
    msg.set_content("This message requires an HTML-capable reader.")
    msg.add_alternative(html, subtype="html")

    if chart_cid:
        chart = repo_path(ecfg["body"]["chart_path"])
        if chart.exists():
            msg.get_payload()[1].add_related(
                chart.read_bytes(), maintype="image", subtype="png",
                cid=f"<{chart_cid}>")

    for rel in ecfg.get("attach") or []:
        path = repo_path(rel)
        if not path.exists():
            continue
        sub = "vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
            if path.suffix == ".xlsx" else path.suffix.lstrip(".")
        main = "application" if path.suffix == ".xlsx" else "image"
        msg.add_attachment(path.read_bytes(), maintype=main, subtype=sub,
                           filename=path.name)
    return msg


def send(cfg: dict, msg: EmailMessage, password: str, log: RunLog) -> bool:
    """Send it. The password never reaches the log, and neither does anything
    smtplib puts in an exception's args - only the exception CLASS is
    reported, because server responses can echo what was sent."""
    s = cfg["email"]["smtp"]
    try:
        with smtplib.SMTP(s["host"], s["port"], timeout=60) as srv:
            if s.get("starttls"):
                srv.starttls()
            srv.login(msg["From"], password)
            srv.send_message(msg)
    except Exception as exc:                       # noqa: BLE001 - deliberate
        # NOTE: str(exc) is NOT interpolated. smtplib raises
        # SMTPAuthenticationError with the server's reply in .args, and a
        # reply can quote the credential it rejected.
        log.alert(f"email FAILED: {type(exc).__name__} (details suppressed so no "
                  "credential can reach the log)", code="EMAIL_FAILED")
        return False
    log.info(f"email sent to {cfg['email']['to']} ({len(msg.get_payload())} parts)")
    return True


# --------------------------------------------------------------------------
def latest_period(monthly: list[dict], weekly: list[dict]) -> dict | None:
    frame = weekly or monthly
    rows = [r for r in frame if r.get("buyback_mxn") is not None]
    if not rows:
        return None
    r = rows[-1]
    return {"date": r["date"].strftime("%d-%b-%Y"), "buyback_mxn": r["buyback_mxn"],
            "shares_bought": r["shares_bought"], "avg_price": r["avg_price"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Send the weekly buyback email.")
    ap.add_argument("--dry-run", action="store_true",
                    help="write output/email_preview.html and send nothing "
                         "(works with no credentials at all)")
    ap.add_argument("--no-new-reports", action="store_true",
                    help="say so in the body; the run still emails")
    ap.add_argument("--notice", action="append", default=[], metavar="SEV:CODE:MESSAGE",
                    help="inject a notice into the body, e.g. "
                         "'ALERT:FETCH_FAILED:the fetch step failed'. The workflow uses "
                         "this to report a failed EARLIER step, which send_email.py "
                         "cannot otherwise see - it builds its own fresh run log.")
    args = ap.parse_args()

    import build_series

    cfg = load_config()
    cfg["email"] = load_config("email.yaml")
    log = RunLog(cfg)
    ecfg = cfg["email"]

    if not ecfg.get("enabled"):
        log.info("email disabled in config/email.yaml - nothing sent")
        return 0

    weekly, monthly = build_series.build(cfg, log, probe=False)

    # notices injected by the workflow for steps that ran BEFORE this process
    for raw in args.notice:
        sev, _, rest = raw.partition(":")
        code, _, message = rest.partition(":")
        log.notices.append({"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                            "severity": sev.strip().upper() or "ALERT",
                            "code": code.strip() or "WORKFLOW",
                            "message": message.strip(), "affected_date": ""})

    latest = latest_period(monthly, weekly)
    ytd = read_ytd(cfg)
    report_date = latest["date"] if latest else dt.date.today().isoformat()

    chart_cid = None
    if repo_path(ecfg["body"]["chart_path"]).exists():
        chart_cid = make_msgid(idstring=ecfg["body"]["chart_cid"]).strip("<>")

    html = build_html(cfg, latest, ytd, log.notices, chart_cid, args.no_new_reports)
    has_alert = any(n["severity"] == "ALERT" for n in log.notices)
    subject = ecfg["subject"]["alert" if has_alert else "normal"].format(report_date=report_date)

    if args.dry_run:
        out = repo_path("output/email_preview.html")
        # the preview cannot render a cid: image, so point at the file
        out.write_text(html.replace(f"cid:{chart_cid}", "amx_buybacks_chart.png")
                       if chart_cid else html, encoding="utf-8")
        log.info(f"DRY RUN: subject {subject!r}")
        log.info(f"DRY RUN: preview written to {out} - nothing sent")
        return 0

    sender, password = read_credentials(ecfg)
    if not sender or not password:
        missing = [n for n, v in ((ecfg["from_env"], sender), (ecfg["password_env"], password)) if not v]
        log.alert(f"email NOT sent: {', '.join(missing)} absent from the environment. "
                  "These are owner-created GitHub settings and are referenced by name "
                  "only; no value is stored in this repo.", code="EMAIL_NO_CREDENTIALS")
        return 1

    msg = compose(cfg, html, subject, sender, chart_cid)
    return 0 if send(cfg, msg, password, log) else 1


if __name__ == "__main__":
    raise SystemExit(main())
