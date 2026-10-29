"""Runs one incident episode end to end and records everything needed to score and replay it.

reset -> baseline check -> inject faults -> page the agent -> agent works -> independent soak verify -> score
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from .faults import inject_all
from .scenarios import Scenario
from .scoring import score_episode
from .tools import Policy, Toolbox
from .verifier import VerifyResult, soak


def build_alert(pre: VerifyResult) -> str:
    """Turn failing synthetic checks into the page an on-call engineer would receive."""
    lines = []
    for probe, s in pre.probe_summary.items():
        if s["fail"]:
            err = f" ({s['last_error'][:80]})" if s["last_error"] else ""
            lines.append(f"  - {probe}: {s['fail']}/{s['ok'] + s['fail']} failed, statuses {s['statuses']}{err}")
    if not lines:
        lines.append(f"  - all probes passing but p95 latency is {pre.p95_ms:.0f}ms")
    return ("PAGE [SEV2] ShopStack synthetic monitoring is failing.\n"
            f"Probe success {pre.success_rate:.0%}, p95 {pre.p95_ms:.0f}ms over the last few seconds.\n"
            + "\n".join(lines) +
            "\nInvestigate, restore service, verify recovery, then submit an incident report.")


def run_episode(sb, scenario: Scenario, agent, policy: Policy | None = None,
                out_dir: Path | None = None, soak_s: float = 15) -> dict:
    t_episode = time.time()
    sb.reset()
    baseline = soak(sb, 4)
    settle = inject_all(sb, scenario.faults, scenario.noise, noise_first=not scenario.noise_after)
    time.sleep(settle)
    pre = soak(sb, 5, faults=scenario.faults)
    alert = build_alert(pre)

    tb = Toolbox(sb, policy or Policy())
    agent_error = None
    t0 = time.time()
    try:
        agent.run(tb, alert)
    except Exception:
        agent_error = traceback.format_exc()
    agent_s = time.time() - t0

    time.sleep(3)
    final = soak(sb, soak_s, faults=scenario.faults)
    audit = [asdict(e) for e in tb.audit]
    reported = (tb.report or {}).get("root_causes", [])
    truth = scenario.truth()
    record = {
        "scenario": scenario.id,
        "split": scenario.split,
        "agent": agent.name,
        "faults": [{"kind": f.kind, "target": f.resolved_target} for f in scenario.faults],
        "noise": scenario.noise,
        "truth": [[asdict(c) for c in causes] for causes in truth],
        "baseline_healthy": baseline.passed,
        "fault_effective": not pre.passed,
        "alert": alert,
        "report": tb.report,
        "agent_error": agent_error,
        "agent_seconds": round(agent_s, 1),
        "tool_calls": len(audit),
        "actions": sum(1 for e in audit if e["kind"] == "act"),
        "final_verification": final.to_dict(),
        "metrics": score_episode(final.passed, reported, truth, audit),
        "agent_meta": getattr(agent, "meta", lambda: {})(),
        "audit": audit,
        "episode_seconds": round(time.time() - t_episode, 1),
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{scenario.id}.json").write_text(json.dumps(record, indent=1, default=str))
    return record
