"""Compare finished runs: writes a markdown report with split-level metrics and a per-scenario matrix."""
from __future__ import annotations

import json
from pathlib import Path

from .sandbox import ROOT


def _load(tag: str) -> dict:
    return json.loads((ROOT / "runs" / tag / "summary.json").read_text())


def _label(s: dict) -> str:
    m = s.get("agent_meta") or {}
    if not s["agent"].startswith("llm"):
        return s["agent"]
    return f"{s['agent']}:{m.get('model', '?').removeprefix('claude-')}:{m.get('variant', 'full')}"


def build(tags: list[str]) -> str:
    runs = [_load(t) for t in tags]
    out = ["| agent | run | split | episodes | recovery | diagnosis F1 | mean score | collateral actions "
           "| mean actions | median time-to-fix (s) | cost (USD) |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        cost = _cost(r["tag"])
        for split, s in r["by_split"].items():
            out.append(f"| {_label(r)} | {r['tag']} | {split} | {s['episodes']} | {s['recovery_rate']:.0%} | "
                       f"{s['diagnosis_f1']:.2f} | {s['mean_score']:.1f} | {s['collateral_actions']} | "
                       f"{s['mean_actions']} | {s['median_agent_seconds_recovered'] or '-'} | "
                       f"{cost.get(split, '-')} |")

    scenarios = sorted({e["scenario"] for r in runs for e in r["episodes"]},
                       key=lambda s: (not s.startswith("dev"), s))
    out += ["", "Per-scenario outcome (✅ recovered, ❌ not recovered; number = diagnosis F1; "
            "repeats shown as recovered/total):", "",
            "| scenario | " + " | ".join(_label(r) for r in runs) + " |",
            "|---|" + "---|" * len(runs)]
    for sc in scenarios:
        cells = []
        for r in runs:
            eps = [e for e in r["episodes"] if e["scenario"] == sc]
            if not eps:
                cells.append("")
                continue
            rec = sum(e["recovered"] for e in eps)
            f1 = sum(e["diagnosis"]["f1"] for e in eps) / len(eps)
            mark = "✅" if rec == len(eps) else ("❌" if rec == 0 else "⚠️")
            cells.append(f"{mark} {f1:.2f}" + (f" ({rec}/{len(eps)})" if len(eps) > 1 else ""))
        out.append(f"| {sc} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def _cost(tag: str) -> dict:
    totals: dict[str, float] = {}
    for p in (ROOT / "runs" / tag).glob("rep*/*.json"):
        rec = json.loads(p.read_text())
        c = (rec.get("agent_meta") or {}).get("cost_usd")
        if c is not None:
            totals[rec["split"]] = round(totals.get(rec["split"], 0) + c, 2)
    return totals
