"""Build docs/replay.html: a self-contained incident replay viewer over recorded runs.

Usage: python scripts/build_replay.py [--raw PATH] [tag ...]   (default: the three baseline tags)
  --raw PATH  also write the page body without the html/head wrapper (for publishing as an artifact)

The page embeds a compact copy of each episode record (alert, faults, every tool call with a
trimmed result, the agent's report, the verifier's verdict, the score), so it opens in any
browser with nothing installed and nothing running. It also embeds each run's CSV and PDF
incident report (the same files `python -m recovery export` writes) for its download buttons.
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from recovery import export  # noqa: E402
from recovery.agents import DESCRIPTIONS, display_name  # noqa: E402
from recovery.faults import FAULTS  # noqa: E402
from recovery.playbook import recommendations  # noqa: E402
from recovery.scoring import WEIGHTS  # noqa: E402

DEFAULT_TAGS = ["baseline-noop", "baseline-restart_all", "baseline-rules"]
RESULT_CHARS = 900


def episode(rec: dict) -> dict:
    fv = rec.get("final_verification") or {}
    return {
        "alert": rec["alert"],
        "report": rec.get("report"),
        "error": (rec.get("agent_error") or "")[:400] or None,
        "seconds": rec.get("agent_seconds"),
        "actions": rec.get("actions"),
        "calls": rec.get("tool_calls"),
        "metrics": rec["metrics"],
        "verify": {"passed": fv.get("passed"), "success": fv.get("success_rate"), "p95": fv.get("p95_ms"),
                   "failures": fv.get("failures", [])[:6]},
        "steps": [{"n": e["step"], "t": e["t"], "tool": e["tool"], "kind": e["kind"], "args": e["args"],
                   "ok": e["ok"], "blocked": e["blocked"], "risky": e.get("risky", False),
                   "result": str(e.get("result", ""))[:RESULT_CHARS]} for e in rec.get("audit", [])],
    }


def build(tags: list[str]) -> dict:
    scenarios: dict[str, dict] = {}
    agents = []
    for tag in tags:
        files = sorted((ROOT / "runs" / tag / "rep0").glob("*.json"))
        if not files:
            raise SystemExit(f"no episodes under runs/{tag}/rep0")
        for f in files:
            rec = json.loads(f.read_text())
            agent = rec["agent"]
            if agent not in agents:
                agents.append(agent)
            sc = scenarios.setdefault(rec["scenario"], {
                "id": rec["scenario"], "split": rec["split"], "noise": rec.get("noise", []),
                "faults": [{**fl, "about": FAULTS[fl["kind"]].description} for fl in rec["faults"]],
                "truth": rec["truth"], "advice": recommendations(rec["faults"]), "runs": {}})
            sc["runs"][agent] = episode(rec)
    order = sorted(scenarios.values(), key=lambda s: (s["split"] != "dev", s["id"]))
    return {"agents": agents, "weights": WEIGHTS, "scenarios": order, "reports": reports(tags),
            "names": {a: display_name(a) for a in agents}, "notes": {a: DESCRIPTIONS.get(a, "") for a in agents}}


def reports(tags: list[str]) -> dict:
    """The same CSV and PDF files `python -m recovery export` writes, embedded for the download buttons."""
    out: dict = {"runs": {}}
    with tempfile.TemporaryDirectory() as tmp:
        every = []
        for tag in tags:
            recs = export.load(tag)
            every += recs
            csv_path, pdf_path = Path(tmp) / f"{tag}.csv", Path(tmp) / f"{tag}.pdf"
            export.write_csv(recs, csv_path)
            entry = {"tag": tag, "csv": csv_path.read_text(encoding="utf-8-sig")}
            try:
                export.write_pdf(recs, pdf_path, f"Mend incident report: {display_name(recs[0]['agent'])}")
                entry["pdf"] = base64.b64encode(pdf_path.read_bytes()).decode()
                entry["incidents"] = {}
                for rec in recs:   # the short one-incident reports behind "Download this incident"
                    one = Path(tmp) / f"{tag}-{rec['scenario']}.pdf"
                    export.write_pdf([rec], one, export.incident_title(rec), single=True)
                    entry["incidents"][rec["scenario"]] = base64.b64encode(one.read_bytes()).decode()
            except SystemExit:   # reportlab not installed: ship the CSV only
                pass
            out["runs"][recs[0]["agent"]] = entry
        all_path = Path(tmp) / "all.csv"
        export.write_csv(every, all_path)
        out["all_csv"] = all_path.read_text(encoding="utf-8-sig")
    return out


def main() -> None:
    args = sys.argv[1:]
    raw = None
    if args[:1] == ["--raw"]:
        raw, args = Path(args[1]), args[2:]
    data = json.dumps(build(args or DEFAULT_TAGS), separators=(",", ":")).replace("</", "<\\/")
    page = (ROOT / "scripts" / "replay_template.html").read_text().replace("/*__DATA__*/null", data)
    if raw:
        raw.write_text(page)
    out = ROOT / "docs" / "replay.html"
    out.write_text('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                   '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                   '<style>body{margin:0}[hidden]{display:none!important}</style>\n</head>\n<body>\n'
                   + page + "\n</body>\n</html>\n")
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
