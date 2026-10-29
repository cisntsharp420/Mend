"""Command line entry point: python -m recovery <command>."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .agents import AGENTS, make_agent
from .harness import run_episode
from .sandbox import ROOT, Sandbox
from .scenarios import load
from .tools import Policy

RUNS = ROOT / "runs"


def _human_approver(tool: str, args: dict) -> bool:
    ans = input(f"\n[APPROVAL] agent wants to run RISKY action {tool}({json.dumps(args)}). Allow? [y/N] ")
    return ans.strip().lower() == "y"


def cmd_up(a):
    sb = Sandbox()
    print("building images...")
    sb.build()
    print("starting ShopStack...")
    sb.reset()
    print(f"ShopStack is up: {sb.gateway_url}/api/health")


def cmd_down(a):
    Sandbox().down()


def cmd_status(a):
    from .tools import Toolbox
    tb = Toolbox(Sandbox())
    print(tb.call("list_services"))
    print(tb.call("check_endpoints"))


def cmd_inject(a):
    from .faults import inject_all
    sb = Sandbox()
    (sc,) = load(a.scenario)
    sb.reset()
    time.sleep(inject_all(sb, sc.faults, sc.noise, noise_first=not sc.noise_after))
    print(f"injected {sc.id}: {[f.kind for f in sc.faults]} — the system is now broken.")


def _agent_kwargs(a, scenario_id: str) -> dict:
    if a.agent != "llm":
        return {}
    kw = {"model": a.model, "variant": a.variant, "effort": a.effort}
    if a.replay:
        kw["replay"] = Path(a.replay) / f"{scenario_id}.json"
    return kw


def _print_episode(r):
    m = r["metrics"]
    print(f"  {r['scenario']:32s} recovered={'YES' if m['recovered'] else 'no ':3s} "
          f"diagF1={m['diagnosis']['f1']:.2f} collateral={m['collateral_actions']} "
          f"actions={r['actions']:2d} calls={r['tool_calls']:2d} agent={r['agent_seconds']:5.1f}s "
          f"score={m['score']:5.1f}" + ("" if r["fault_effective"] else "  [WARN fault not effective]")
          + (f"  [AGENT ERROR]" if r["agent_error"] else ""), flush=True)


def summarize(records: list[dict]) -> dict:
    n = len(records)
    rec = [r["metrics"]["recovered"] for r in records]
    return {
        "episodes": n,
        "recovery_rate": round(sum(rec) / n, 3) if n else 0,
        "diagnosis_f1": round(statistics.mean(r["metrics"]["diagnosis"]["f1"] for r in records), 3) if n else 0,
        "mean_score": round(statistics.mean(r["metrics"]["score"] for r in records), 1) if n else 0,
        "collateral_actions": sum(r["metrics"]["collateral_actions"] for r in records),
        "mean_actions": round(statistics.mean(r["actions"] for r in records), 1) if n else 0,
        "median_agent_seconds_recovered": round(statistics.median(
            [r["agent_seconds"] for r in records if r["metrics"]["recovered"]]), 1) if any(rec) else None,
        "invalid_episodes": sum(1 for r in records if not r["fault_effective"] or not r["baseline_healthy"]),
        "agent_errors": sum(1 for r in records if r["agent_error"]),
    }


def cmd_run(a):
    sb = Sandbox()
    scenarios = load(a.scenarios)
    tag = a.tag or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{a.agent}"
    out = RUNS / tag
    policy = Policy(max_actions=a.max_actions, dry_run=a.dry_run,
                    approver=_human_approver if a.approve else None)
    records = []
    print(f"run {tag}: agent={a.agent} scenarios={len(scenarios)} repeats={a.repeats}")
    for rep in range(a.repeats):
        for sc in scenarios:
            agent = make_agent(a.agent, **_agent_kwargs(a, sc.id))
            r = run_episode(sb, sc, agent, policy, out / f"rep{rep}", soak_s=a.soak)
            r["repeat"] = rep
            records.append(r)
            _print_episode(r)
    summary = {"tag": tag, "agent": a.agent, "selector": a.scenarios, "repeats": a.repeats,
               "agent_meta": records[0]["agent_meta"] if records else {},
               "overall": summarize(records),
               "by_split": {s: summarize([r for r in records if r["split"] == s])
                            for s in sorted({r["split"] for r in records})},
               "episodes": [{k: r[k] for k in ("scenario", "split", "repeat", "agent_seconds", "actions",
                                                "tool_calls", "fault_effective")} | r["metrics"]
                            for r in records]}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary["by_split"], indent=1))
    print(f"results: {out}")


def cmd_report(a):
    from .report import build
    md = build(a.tags)
    if a.out:
        Path(a.out).write_text(md)
        print(f"wrote {a.out}")
    print(md)


def main(argv=None):
    p = argparse.ArgumentParser(prog="recovery", description="Agentic recovery of a failing system")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="build and start the ShopStack sandbox").set_defaults(fn=cmd_up)
    sub.add_parser("down", help="stop and remove the sandbox").set_defaults(fn=cmd_down)
    sub.add_parser("status", help="show service states and endpoint probes").set_defaults(fn=cmd_status)
    s = sub.add_parser("inject", help="reset and inject one scenario (for manual demos)")
    s.add_argument("scenario")
    s.set_defaults(fn=cmd_inject)
    r = sub.add_parser("run", help="run an agent on scenarios and score it")
    r.add_argument("--agent", choices=AGENTS, default="rules")
    r.add_argument("--scenarios", default="dev", help="dev | heldout | all | comma-separated ids/prefixes")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--tag", help="name of the results folder under runs/")
    r.add_argument("--model", help="LLM model id (llm agent)")
    r.add_argument("--variant", default="full",
                   help="LLM ablation: full | no_verify | no_changes | no_diagnostics | minimal_prompt")
    r.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--replay", help="folder of recorded episodes (e.g. runs/<tag>/rep0): replay the "
                   "LLM's recorded decisions without an API key")
    r.add_argument("--max-actions", type=int, default=12)
    r.add_argument("--soak", type=float, default=15, help="seconds of final verification")
    r.add_argument("--approve", action="store_true", help="ask a human before risky actions")
    r.add_argument("--dry-run", action="store_true", help="agent actions are described, not executed")
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report", help="compare runs: python -m recovery report <tag> [<tag> ...]")
    rp.add_argument("tags", nargs="+")
    rp.add_argument("--out", help="write markdown to this file")
    rp.set_defaults(fn=cmd_report)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
