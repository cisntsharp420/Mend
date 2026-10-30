"""Export finished runs as incident reports: a CSV (one row per episode) and a PDF.

python -m recovery export <tag> [<tag> ...] [--out DIR]
writes DIR/<tag>.csv and DIR/<tag>.pdf per run, plus DIR/all_episodes.csv when several tags are given.
The PDF needs reportlab (pip install -e '.[export]'); the CSV needs nothing extra.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from .faults import FAULTS
from .sandbox import ROOT
from .scoring import WEIGHTS

COLUMNS = [
    "run", "agent", "repeat", "scenario", "split", "recovered", "score", "recovery_points", "diagnosis_points",
    "safety_points", "diagnosis_precision", "diagnosis_recall", "diagnosis_f1", "collateral_actions",
    "blocked_calls", "actions", "tool_calls", "agent_seconds", "traffic_success_rate", "p95_ms",
    "injected_faults", "red_herrings", "true_root_causes", "reported_root_causes", "evidence", "agent_summary",
    "actions_taken", "verifier_findings", "agent_error",
]


def load(tag: str) -> list[dict]:
    """All episode records of a run, in scenario order, with their repeat index."""
    base = ROOT / "runs" / tag
    recs = []
    for rep in sorted(base.glob("rep*")):
        for f in sorted(rep.glob("*.json")):
            rec = json.loads(f.read_text())
            rec["_run"], rec["_repeat"] = tag, int(rep.name.removeprefix("rep") or 0)
            recs.append(rec)
    if not recs:
        raise SystemExit(f"no episodes under {base}")
    return sorted(recs, key=lambda r: (r["split"] != "dev", r["scenario"], r["_repeat"]))


def _causes(rc: list[dict]) -> str:
    return "; ".join(f"{c['component']}/{c['category']}" for c in rc)


def _truth(truth: list[list[dict]]) -> str:
    return "; ".join(" or ".join(f"{c['component']}/{c['category']}" for c in alts) for alts in truth)


def _actions(audit: list[dict]) -> list[str]:
    out = []
    for e in audit:
        if e["kind"] != "act":
            continue
        args = ", ".join(f"{k}={v}" for k, v in e["args"].items())
        out.append(f"{e['tool']}({args})" + (" [blocked]" if e.get("blocked") else ""))
    return out


def row(rec: dict) -> dict:
    m, fv, rep = rec["metrics"], rec.get("final_verification") or {}, rec.get("report") or {}
    rc = rep.get("root_causes", [])
    return {
        "run": rec.get("_run", ""), "agent": rec["agent"], "repeat": rec.get("_repeat", 0),
        "scenario": rec["scenario"], "split": rec["split"], "recovered": "yes" if m["recovered"] else "no",
        "score": m["score"], "recovery_points": WEIGHTS["recovered"] if m["recovered"] else 0,
        "diagnosis_points": round(WEIGHTS["diagnosis"] * m["diagnosis"]["f1"], 1),
        "safety_points": round(WEIGHTS["safety"] * m["safety"], 1),
        "diagnosis_precision": m["diagnosis"]["precision"], "diagnosis_recall": m["diagnosis"]["recall"],
        "diagnosis_f1": m["diagnosis"]["f1"], "collateral_actions": m["collateral_actions"],
        "blocked_calls": m.get("blocked_calls", 0), "actions": rec.get("actions", 0),
        "tool_calls": rec.get("tool_calls", 0), "agent_seconds": rec.get("agent_seconds"),
        "traffic_success_rate": fv.get("success_rate"), "p95_ms": fv.get("p95_ms"),
        "injected_faults": "; ".join(f"{f['kind']}@{f.get('target', '')}" for f in rec["faults"]),
        "red_herrings": "; ".join(rec.get("noise", [])), "true_root_causes": _truth(rec["truth"]),
        "reported_root_causes": _causes(rc), "evidence": " | ".join(c.get("evidence", "") for c in rc if c.get("evidence")),
        "agent_summary": rep.get("summary", ""), "actions_taken": "; ".join(_actions(rec.get("audit", []))),
        "verifier_findings": "; ".join(fv.get("failures", [])), "agent_error": (rec.get("agent_error") or "").strip()[:300],
    }


def write_csv(recs: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:   # BOM so Excel detects UTF-8
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(row(r) for r in recs)


def _split_stats(rows: list[dict]) -> list[list[str]]:
    out = []
    for split in ("dev", "heldout"):
        rs = [r for r in rows if r["split"] == split]
        if not rs:
            continue
        n = len(rs)
        out.append(["dev" if split == "dev" else "held-out", str(n),
                    f"{sum(r['recovered'] == 'yes' for r in rs) / n:.0%}",
                    f"{sum(r['diagnosis_f1'] for r in rs) / n:.2f}",
                    f"{sum(r['score'] for r in rs) / n:.1f}",
                    str(sum(r['collateral_actions'] for r in rs))])
    return out


def write_pdf(recs: list[dict], path: Path, title: str) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate,
                                        Spacer, Table, TableStyle)
    except ImportError:
        raise SystemExit("PDF export needs reportlab: pip install -e '.[export]'") from None

    ink, muted, line = colors.HexColor("#18212b"), colors.HexColor("#5a6573"), colors.HexColor("#d8dee5")
    ss = getSampleStyleSheet()
    st = {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24,
                                alignment=0, textColor=ink, spaceAfter=4),
        "sub": ParagraphStyle("s", parent=ss["Normal"], fontSize=9.5, leading=13, textColor=muted),
        "h1": ParagraphStyle("h1", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=17,
                             textColor=ink, spaceBefore=2, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10,
                             textColor=muted, spaceBefore=9, spaceAfter=3),
        "body": ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=13, textColor=ink),
        "cell": ParagraphStyle("c", parent=ss["Normal"], fontSize=8, leading=10, textColor=ink),
        "mono": ParagraphStyle("m", parent=ss["Code"], fontName="Courier", fontSize=7.4, leading=9.2,
                               textColor=ink, backColor=colors.HexColor("#f6f8fa"), borderPadding=5,
                               leftIndent=5, rightIndent=5, spaceBefore=2, spaceAfter=4),
    }
    P = lambda text, style="body": Paragraph(text, st[style])  # noqa: E731

    def table(data, widths, header=True, align_right_from=1):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (-1, -1), ink),
                 ("LINEBELOW", (0, 0), (-1, -1), 0.4, line), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                 ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT")]
        if header:
            style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5), ("TEXTCOLOR", (0, 0), (-1, 0), muted),
                      ("LINEBELOW", (0, 0), (-1, 0), 0.8, ink)]
        t.setStyle(TableStyle(style))
        return t

    rows = [row(r) for r in recs]
    agents = sorted({r["agent"] for r in rows})
    made = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story = [P(escape(title), "title"),
             P(f"Agent: <b>{escape(', '.join(agents))}</b> &nbsp;·&nbsp; {len(rows)} incidents &nbsp;·&nbsp; "
               f"generated {made}", "sub"),
             Spacer(1, 6 * mm),
             P("How to read this report", "h2"),
             P("Each incident was injected into a live five-service system. The agent investigated and acted only "
               "through a guarded toolbox, then filed a root-cause report. An independent verifier sent real user "
               "traffic over a soak window and checked that each fault's root cause was actually gone. Score: "
               f"{WEIGHTS['recovered']} points for a verified recovery, {WEIGHTS['diagnosis']} for naming the right "
               f"root cause (F1), {WEIGHTS['safety']} for touching nothing that was not broken."),
             P("Summary", "h2"),
             table([["SPLIT", "INCIDENTS", "RECOVERED", "DIAGNOSIS F1", "MEAN SCORE", "COLLATERAL"]]
                   + _split_stats(rows), [32 * mm, 26 * mm, 26 * mm, 28 * mm, 28 * mm, 26 * mm]),
             P("Incidents", "h2")]
    overview = [["INCIDENT", "SPLIT", "RESULT", "SCORE", "REPORTED ROOT CAUSE"]]
    for r in rows:
        res = ('<font color="#1d7a4c">recovered</font>' if r["recovered"] == "yes"
               else '<font color="#be3329">not recovered</font>')
        overview.append([P(escape(r["scenario"]), "cell"), "dev" if r["split"] == "dev" else "held-out",
                         P(res, "cell"), f"{r['score']:.0f}",
                         P(escape(r["reported_root_causes"] or "none"), "cell")])
    ov = table(overview, [52 * mm, 18 * mm, 24 * mm, 14 * mm, 58 * mm], align_right_from=3)
    ov.setStyle(TableStyle([("ALIGN", (4, 0), (4, -1), "LEFT")]))
    story += [ov]

    for rec, r in zip(recs, rows):
        good = r["recovered"] == "yes"
        verdict = (f'<font color="{"#1d7a4c" if good else "#be3329"}"><b>{"RECOVERED" if good else "NOT RECOVERED"}'
                   f'</b></font> &nbsp; score <b>{r["score"]:.0f}/100</b> &nbsp;=&nbsp; recovery {r["recovery_points"]:.0f}'
                   f' + diagnosis {r["diagnosis_points"]:.0f} + safety {r["safety_points"]:.0f}')
        story += [PageBreak(),
                  P(f'{escape(r["scenario"])} <font size="9" color="#b45a0c">'
                    f'{"DEV" if r["split"] == "dev" else "HELD-OUT"}</font>', "h1"),
                  P(verdict),
                  P("Pager alert", "h2"), Preformatted(rec["alert"].strip(), st["mono"], maxLineLength=118),
                  P("What was actually broken", "h2")]
        for f in rec["faults"]:
            story.append(P(f"• <b>{escape(f['kind'])}</b> on {escape(f.get('target', ''))}: "
                           f"{escape(FAULTS[f['kind']].description)}"))
        if rec.get("noise"):
            story.append(P(f"• Red herrings planted: {escape(', '.join(rec['noise']))}"))
        story.append(P(f"Root causes to name: <b>{escape(r['true_root_causes'])}</b>"))

        rep = rec.get("report") or {}
        story.append(P("Agent's incident report", "h2"))
        if rep.get("root_causes"):
            for c in rep["root_causes"]:
                story.append(P(f"• <b>{escape(c['component'])}/{escape(c['category'])}</b>"
                               + (f": {escape(c['evidence'])}" if c.get("evidence") else "")))
        else:
            story.append(P("No root cause reported."))
        if rep.get("summary"):
            story.append(P(f"Summary: {escape(rep['summary'])}"))
        if r["agent_error"]:
            story.append(P(f'<font color="#be3329">Agent error: {escape(r["agent_error"])}</font>'))

        steps = [["#", "TIME", "TYPE", "TOOL CALL"]]
        for e in rec.get("audit", []):
            args = ", ".join(f"{k}={v}" for k, v in e["args"].items())
            kind = "blocked" if e.get("blocked") else e["kind"]
            color = "#b45a0c" if kind == "act" else "#be3329" if kind == "blocked" else "#5a6573"
            steps.append([str(e["step"]), f"{e['t']:.1f}s", P(f'<font color="{color}">{kind}</font>', "cell"),
                          P(f"<b>{escape(e['tool'])}</b>({escape(args)})", "cell")])
        story += [P(f"Investigation and actions ({r['tool_calls']} tool calls, {r['actions']} state changes, "
                    f"{r['agent_seconds'] or 0:.1f} s)", "h2"),
                  table(steps, [9 * mm, 14 * mm, 18 * mm, 125 * mm], align_right_from=9)]

        sr = r["traffic_success_rate"]
        facts = [["USER TRAFFIC SUCCESS", "P95 LATENCY", "COLLATERAL ACTIONS", "DIAGNOSIS F1"],
                 [f"{sr:.0%}" if sr is not None else "–",
                  f"{r['p95_ms']:.0f} ms" if r["p95_ms"] is not None else "–",
                  str(r["collateral_actions"]), f"{r['diagnosis_f1']:.2f}"]]
        verif = [P("Independent verification", "h2"),
                 table(facts, [42 * mm, 42 * mm, 42 * mm, 40 * mm], align_right_from=9)]
        if r["verifier_findings"]:
            verif.append(P(f"Findings: {escape(r['verifier_findings'])}"))
        story.append(KeepTogether(verif))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(18 * mm, 10 * mm, f"{title} · {made}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, title=title, author="Agentic Recovery benchmark",
                            leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def export(tags: list[str], out: Path, pdf: bool = True) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written, every = [], []
    for tag in tags:
        recs = load(tag)
        every += recs
        write_csv(recs, out / f"{tag}.csv")
        written.append(out / f"{tag}.csv")
        if pdf:
            write_pdf(recs, out / f"{tag}.pdf", f"Incident Recovery Report: {tag}")
            written.append(out / f"{tag}.pdf")
    if len(tags) > 1:
        write_csv(every, out / "all_episodes.csv")
        written.append(out / "all_episodes.csv")
    return written
