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

from .agents import DESCRIPTIONS, display_name
from .faults import FAULTS
from .playbook import recommendations
from .sandbox import ROOT
from .scoring import WEIGHTS

COLUMNS = [
    "run", "agent", "agent_name", "repeat", "scenario", "split", "recovered", "score", "recovery_points", "diagnosis_points",
    "safety_points", "diagnosis_precision", "diagnosis_recall", "diagnosis_f1", "collateral_actions",
    "blocked_calls", "actions", "tool_calls", "agent_seconds", "traffic_success_rate", "p95_ms",
    "injected_faults", "red_herrings", "true_root_causes", "reported_root_causes", "evidence", "agent_summary",
    "actions_taken", "verifier_findings", "agent_error", "fix_status", "recommended_fix", "prevention",
    "agent_recommendations",
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
        "run": rec.get("_run", ""), "agent": rec["agent"], "agent_name": display_name(rec["agent"]), "repeat": rec.get("_repeat", 0),
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
        "fix_status": "done by the agent" if m["recovered"] else "still needed",
        "recommended_fix": " | ".join(r["fix"] for r in recommendations(rec["faults"])),
        "prevention": " | ".join(p for r in recommendations(rec["faults"]) for p in r["prevent"]),
        "agent_recommendations": " | ".join(rep.get("recommendations", [])),
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


FONTS = Path(__file__).parent / "assets" / "fonts"
# Mend palette (matches the web app): deep teal night, glass panels, lime accent.
PALETTE = {"bg": "#04110f", "panel": "#0c2321", "panel2": "#112e2b", "line": "#1f3d3a", "ink": "#e9f3f0",
           "muted": "#8aa6a1", "dim": "#5f7c77", "lime": "#c6f24e", "teal": "#3fc1b0", "sky": "#7cc7d9",
           "ok": "#86e39a", "bad": "#ff8a78", "alert": "#d5e4e0"}
SLABS = [("#0e4a4a", .55), ("#13605b", .7), ("#1b7a6f", .8), ("#2b9a82", .88), ("#5fbf6e", .92),
         ("#a6e05a", .95), ("#c6f24e", .9), ("#bfe9d8", .75), ("#8fd0dc", .6)]


def _register_fonts() -> tuple[str, str, str, str]:
    """Mend's typefaces (bundled, SIL OFL); falls back to Helvetica/Courier if they are missing."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    files = {"Mend-Display": "Unbounded-Bold.ttf", "Mend-Body": "Manrope-Regular.ttf",
             "Mend-Body-Bold": "Manrope-Bold.ttf", "Mend-Mono": "JetBrainsMono-Regular.ttf"}
    if not all((FONTS / f).exists() for f in files.values()):
        return "Helvetica-Bold", "Helvetica", "Helvetica-Bold", "Courier"
    for name, f in files.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONTS / f)))
    for bold, italic, face in [(0, 0, "Mend-Body"), (1, 0, "Mend-Body-Bold"), (0, 1, "Mend-Body"), (1, 1, "Mend-Body-Bold")]:
        addMapping("Mend-Body", bold, italic, face)
    return "Mend-Display", "Mend-Body", "Mend-Body-Bold", "Mend-Mono"


def write_pdf(recs: list[dict], path: Path, title: str, single: bool = False) -> None:
    """Full report (cover, overview, one page per incident) or, with single=True, just the incident pages."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate,
                                        Spacer, Table, TableStyle)
    except ImportError:
        raise SystemExit("PDF export needs reportlab: pip install -e '.[export]'") from None

    DISPLAY, BODY, BOLD, MONO = _register_fonts()
    C = {k: colors.HexColor(v) for k, v in PALETTE.items()}
    W, H = A4
    margin = 18 * mm
    width = W - 2 * margin

    def style(name, **kw):
        base = dict(fontName=BODY, fontSize=9.4, leading=13.5, textColor=C["ink"])
        return ParagraphStyle(name, **{**base, **kw})
    st = {
        "eyebrow": style("eyebrow", fontName=DISPLAY, fontSize=7.5, leading=10, textColor=C["teal"]),
        "cover": style("cover", fontName=DISPLAY, fontSize=34, leading=38, textColor=C["ink"]),
        "lede": style("lede", fontSize=11, leading=16, textColor=C["alert"]),
        "sub": style("sub", fontSize=8.5, leading=12, textColor=C["muted"]),
        "subr": style("subr", fontSize=8.5, leading=12, textColor=C["muted"], alignment=2),
        "h1": style("h1", fontName=MONO, fontSize=15, leading=19),
        "h2": style("h2", fontName=DISPLAY, fontSize=7, leading=9, textColor=C["muted"], spaceBefore=12, spaceAfter=5),
        "body": style("body"),
        "cell": style("cell", fontSize=8.2, leading=10.5),
        "cellmono": style("cellmono", fontName=MONO, fontSize=7.6, leading=10),
        "stat": style("stat", fontName=DISPLAY, fontSize=17, leading=20, textColor=C["lime"]),
        "statl": style("statl", fontSize=7.6, leading=10, textColor=C["muted"]),
        "score": style("score", fontName=DISPLAY, fontSize=26, leading=30, alignment=2),
        "mono": ParagraphStyle("mono", fontName=MONO, fontSize=6.9, leading=9.4, textColor=C["alert"]),
    }
    P = lambda text, s="body": Paragraph(text, st[s])  # noqa: E731
    up = lambda s: escape(s.upper())  # noqa: E731

    def h2(text):
        return P(up(text), "h2")

    def table(data, widths, header=True, right_from=1, zebra=False):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        s = [("FONT", (0, 0), (-1, -1), BODY, 8.4), ("TEXTCOLOR", (0, 0), (-1, -1), C["ink"]),
             ("BACKGROUND", (0, 0), (-1, -1), C["panel"]), ("LINEBELOW", (0, 0), (-1, -1), .5, C["line"]),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 7),
             ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("ALIGN", (right_from, 0), (-1, -1), "RIGHT"),
             ("BOX", (0, 0), (-1, -1), .6, C["line"])]
        if header:
            s += [("FONT", (0, 0), (-1, 0), DISPLAY, 6), ("TEXTCOLOR", (0, 0), (-1, 0), C["muted"]),
                  ("BACKGROUND", (0, 0), (-1, 0), C["panel2"]), ("TOPPADDING", (0, 0), (-1, 0), 7),
                  ("BOTTOMPADDING", (0, 0), (-1, 0), 7)]
        t.setStyle(TableStyle(s))
        return t

    def box(flowables, rule=None, pad=9):
        t = Table([[flowables]], colWidths=[width])
        s = [("BACKGROUND", (0, 0), (-1, -1), C["panel"]), ("BOX", (0, 0), (-1, -1), .6, C["line"]),
             ("LEFTPADDING", (0, 0), (-1, -1), pad + 2), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
             ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]
        if rule:
            s.append(("LINEBEFORE", (0, 0), (0, -1), 2.5, rule))
        t.setStyle(TableStyle(s))
        return t

    def tiles(items, n=None):
        n = n or len(items)
        cells = [[P(v, "stat"), P(escape(label), "statl")] for v, label in items]
        t = Table([cells], colWidths=[width / n] * n)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C["panel"]), ("BOX", (0, 0), (-1, -1), .6, C["line"]),
                               ("LINEAFTER", (0, 0), (-2, -1), .6, C["line"]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 9),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
        return t

    def pill(text, color):
        return f'<font name="{DISPLAY}" size="6.5" color="{color}">{up(text)}</font>'

    rows = [row(r) for r in recs]
    agents = sorted({r["agent"] for r in rows})
    names = ", ".join(display_name(a) for a in agents)
    made = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lime, ok, bad = PALETTE["lime"], PALETTE["ok"], PALETTE["bad"]

    # ---------------------------------------------------------------- cover + summary
    by = {sp: [r for r in rows if r["split"] == sp] for sp in ("dev", "heldout")}
    pct = lambda rs: f"{sum(r['recovered'] == 'yes' for r in rs) / len(rs):.0%}" if rs else "–"  # noqa: E731
    avg = lambda rs: f"{sum(r['score'] for r in rs) / len(rs):.0f}" if rs else "–"  # noqa: E731
    story = [] if single else [Spacer(1, 30 * mm),
             P(up("Incident recovery report"), "eyebrow"), Spacer(1, 3 * mm),
             P(up(names), "cover"), Spacer(1, 3 * mm),
             P(escape(DESCRIPTIONS.get(agents[0], "")[:1].upper() + DESCRIPTIONS.get(agents[0], "")[1:]) + "."
               if len(agents) == 1 else "", "lede"),
             Spacer(1, 2 * mm),
             P(f"{len(rows)} incidents &nbsp;·&nbsp; run <font name=\"{MONO}\">{escape(rows[0]['run'])}</font>"
               f" &nbsp;·&nbsp; generated {made}", "sub"),
             Spacer(1, 26 * mm),
             tiles([(pct(by["dev"]), "recovered, dev incidents"), (pct(by["heldout"]), "recovered, never-seen incidents"),
                    (avg(by["dev"]), "mean score, dev"), (avg(by["heldout"]), "mean score, never-seen")]),
             Spacer(1, 6 * mm),
             h2("How to read this report"),
             P("Each incident was injected into a live five-service shop. The agent investigated and acted only "
               "through a guarded toolbox, then filed a root-cause report. An independent verifier sent real user "
               "traffic over a soak window and checked that each fault's root cause was actually gone. Score: "
               f"<b>{WEIGHTS['recovered']}</b> points for a verified recovery, <b>{WEIGHTS['diagnosis']}</b> for naming "
               f"the right root cause, <b>{WEIGHTS['safety']}</b> for touching nothing that was not broken. Each incident "
               "page ends with recommendations: the immediate fix and how to prevent a repeat."),
             h2("Summary"),
             table([["SPLIT", "INCIDENTS", "RECOVERED", "DIAGNOSIS F1", "MEAN SCORE", "COLLATERAL"]] + _split_stats(rows),
                   [width * f for f in (.2, .15, .16, .17, .17, .15)]),
             PageBreak(),
             P(up("Incidents"), "eyebrow"), Spacer(1, 4 * mm)]
    overview = [["INCIDENT", "SPLIT", "RESULT", "SCORE", "REPORTED ROOT CAUSE"]]
    for r in rows:
        res = pill("recovered", ok) if r["recovered"] == "yes" else pill("not recovered", bad)
        overview.append([P(escape(r["scenario"]), "cellmono"), "dev" if r["split"] == "dev" else "held-out",
                         P(res, "cell"), f"{r['score']:.0f}", P(escape(r["reported_root_causes"] or "none"), "cellmono")])
    ov = table(overview, [width * f for f in (.33, .1, .2, .07, .3)], right_from=3)
    ov.setStyle(TableStyle([("ALIGN", (4, 0), (4, -1), "LEFT")]))
    if single:
        story = [P(up(f"Incident report · {names}"), "eyebrow"), Spacer(1, 4 * mm)]
    else:
        story.append(ov)

    # ---------------------------------------------------------------- one page per incident
    for rec, r in zip(recs, rows):
        good = r["recovered"] == "yes"
        rep = rec.get("report") or {}
        head = Table([[[P(pill("dev" if r["split"] == "dev" else "held-out", lime if r["split"] != "dev" else PALETTE["muted"]), "cell"),
                        Spacer(1, 1.5 * mm), P(escape(r["scenario"]), "h1"), Spacer(1, 1.5 * mm),
                        P(pill("system recovered", ok) if good else pill("still broken", bad), "cell")],
                       [P(f'<font color="{lime if good else PALETTE["ink"]}">{r["score"]:.0f}</font>'
                          f'<font name="{BODY}" size="9" color="{PALETTE["muted"]}"> / 100</font>', "score"),
                        Spacer(1, 2 * mm),
                        P(f'recovery {r["recovery_points"]:.0f} · diagnosis {r["diagnosis_points"]:.0f} · '
                          f'safety {r["safety_points"]:.0f}', "subr")]]],
                     colWidths=[width * .62, width * .38])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("LINEBELOW", (0, 0), (-1, 0), .6, C["line"]), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story += ([] if single and len(story) == 2 else [PageBreak()]) + [head,
                  h2("Pager alert the agent received"),
                  box(Preformatted(rec["alert"].strip(), st["mono"], maxLineLength=104), rule=C["bad"])]

        broken = [P(f'<font color="{PALETTE["sky"]}" name="{MONO}">{escape(f["kind"])}</font> on '
                    f'<font color="{PALETTE["sky"]}" name="{MONO}">{escape(f.get("target", ""))}</font>: '
                    f'{escape(FAULTS[f["kind"]].description)}') for f in rec["faults"]]
        if rec.get("noise"):
            broken.append(P(f'Red herrings planted: <font name="{MONO}">{escape(", ".join(rec["noise"]))}</font>', "sub"))
        broken.append(P(f'Root causes to name: <font name="{MONO}" color="{lime}">{escape(r["true_root_causes"])}</font>'))
        story += [h2("What was actually broken (hidden from the agent)"), box(broken)]

        said = [P(f'<font name="{MONO}" color="{lime}">{escape(c["component"])}/{escape(c["category"])}</font>'
                  + (f': {escape(c["evidence"])}' if c.get("evidence") else "")) for c in rep.get("root_causes", [])]
        said = said or [P("No root cause reported.", "sub")]
        if rep.get("summary"):
            said.append(P(f"Summary: {escape(rep['summary'])}", "sub"))
        if r["agent_error"]:
            said.append(P(f'<font color="{bad}">Agent error: {escape(r["agent_error"])}</font>'))
        story += [h2(f"{display_name(r['agent'])}'s incident report"), box(said)]

        steps = [["#", "TIME", "TYPE", "TOOL CALL"]]
        acts = []
        for i, e in enumerate(rec.get("audit", []), start=1):
            args = ", ".join(f"{k}={v}" for k, v in e["args"].items())
            kind = "blocked" if e.get("blocked") else e["kind"]
            color = {"act": lime, "blocked": bad, "final": PALETTE["teal"]}.get(kind, PALETTE["dim"])
            if kind == "act":
                acts.append(i)
            steps.append([str(e["step"]), f"{e['t']:.1f}s", P(pill(kind, color), "cell"),
                          P(f'<b>{escape(e["tool"])}</b><font color="{PALETTE["muted"]}">({escape(args)})</font>', "cellmono")])
        tl = table(steps, [width * f for f in (.06, .1, .13, .71)], right_from=9)
        tl.setStyle(TableStyle([("BACKGROUND", (0, i), (-1, i), colors.HexColor("#1a3220")) for i in acts]))
        story += [h2(f"Investigation and actions · {r['tool_calls']} tool calls · {r['actions']} state changes · "
                     f"{r['agent_seconds'] or 0:.1f} s"), tl]

        sr = r["traffic_success_rate"]
        verif = [h2("Independent verification"),
                 tiles([(f"{sr:.0%}" if sr is not None else "–", "user traffic success"),
                        (f"{r['p95_ms']:.0f} ms" if r["p95_ms"] is not None else "–", "p95 latency"),
                        (str(r["collateral_actions"]), "collateral actions"),
                        (f"{r['diagnosis_f1']:.2f}", "diagnosis F1")])]
        if r["verifier_findings"]:
            verif.append(P(f"Findings: {escape(r['verifier_findings'])}", "sub"))
        story.append(KeepTogether(verif))

        advice = recommendations(rec["faults"])
        body = [P("<b>Immediate fix</b> &nbsp;" + (pill("done by the agent", ok) if good else pill("still needed", bad)))]
        body += [P(f"•&nbsp; {escape(x['fix'])}") for x in advice]
        body += [Spacer(1, 2 * mm), P("<b>Prevent a repeat</b>")]
        body += [P(f"•&nbsp; {escape(t)}") for x in advice for t in x["prevent"]]
        if rep.get("recommendations"):
            body += [Spacer(1, 2 * mm), P(f"<b>{escape(display_name(r['agent']))}'s own recommendations</b>")]
            body += [P(f"•&nbsp; {escape(t)}") for t in rep["recommendations"]]
        body += [Spacer(1, 1.5 * mm), P("Fix and prevention advice come from the remediation playbook for the injected "
                                        "fault types, not from the agent.", "sub")]
        story.append(KeepTogether([h2("Recommendations"), box(body, rule=C["lime"])]))

    # ---------------------------------------------------------------- page furniture
    def background(canvas, cover: bool):
        canvas.saveState()
        canvas.setFillColor(C["bg"])
        canvas.rect(0, 0, W, H, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor("#0b3a37"))     # soft glow, top left
        for r_, a in ((150 * mm, .10), (105 * mm, .10), (60 * mm, .08)):
            canvas.setFillAlpha(a)
            canvas.circle(-10 * mm, H + 10 * mm, r_, stroke=0, fill=1)
        if cover:                                           # the glowing slabs, as in the web app hero
            for i, (col, alpha) in enumerate(SLABS):
                canvas.saveState()
                canvas.translate(W - 64 * mm + i * 9 * mm, H - 22 * mm - i * 11 * mm)
                canvas.rotate(-38)
                canvas.setFillColor(colors.HexColor(col))
                canvas.setFillAlpha(alpha * .8)
                canvas.roundRect(-27 * mm, -27 * mm, 54 * mm, 54 * mm, 7 * mm, stroke=0, fill=1)
                canvas.restoreState()
        canvas.setFillAlpha(1)
        canvas.setFont(DISPLAY, 10)
        canvas.setFillColor(C["ink"])
        canvas.drawString(margin, H - 13 * mm, "MEND")
        canvas.setFont(BODY, 7.5)
        canvas.setFillColor(C["muted"])
        canvas.drawString(margin, 10 * mm, f"{title} · {made}")
        canvas.drawRightString(W - margin, 10 * mm, f"page {canvas.getPageNumber()}")
        canvas.setStrokeColor(C["line"])
        canvas.setLineWidth(.5)
        canvas.line(margin, 14 * mm, W - margin, 14 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, title=title, author="Mend · Agentic Recovery benchmark",
                            leftMargin=margin, rightMargin=margin, topMargin=20 * mm, bottomMargin=19 * mm)
    doc.build(story, onFirstPage=lambda c, d: background(c, not single), onLaterPages=lambda c, d: background(c, False))


def incident_title(rec: dict) -> str:
    return f"Mend incident report: {rec['scenario']} · {display_name(rec['agent'])}"


def export(tags: list[str], out: Path, pdf: bool = True, per_incident: bool = False) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written, every = [], []
    for tag in tags:
        recs = load(tag)
        every += recs
        write_csv(recs, out / f"{tag}.csv")
        written.append(out / f"{tag}.csv")
        if pdf:
            write_pdf(recs, out / f"{tag}.pdf", f"Mend incident report: {display_name(recs[0]['agent'])}")
            written.append(out / f"{tag}.pdf")
        if pdf and per_incident:
            (out / tag).mkdir(exist_ok=True)
            for rec in recs:
                f = out / tag / f"{rec['scenario']}{'' if rec['_repeat'] == 0 else '-rep' + str(rec['_repeat'])}.pdf"
                write_pdf([rec], f, incident_title(rec), single=True)
                written.append(f)
    if len(tags) > 1:
        write_csv(every, out / "all_episodes.csv")
        written.append(out / "all_episodes.csv")
    return written
