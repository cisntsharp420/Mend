"""Exercise the LLM agent loop offline with a scripted recording (no API key, no docker)."""
import json
from unittest.mock import MagicMock

from recovery.agents.llm import LLMAgent
from recovery.tools import Policy, Toolbox


def turn(*calls, text=""):
    content = [{"type": "thinking", "thinking": "reasoning summary", "signature": "sig"}]
    if text:
        content.append({"type": "text", "text": text})
    content += [{"type": "tool_use", "id": f"t{i}", "name": n, "input": a} for i, (n, a) in enumerate(calls)]
    return {"stop_reason": "tool_use" if calls else "end_turn", "model": "claude-opus-5-5", "content": content}


def write_recording(tmp_path, turns, variant="full"):
    p = tmp_path / "episode.json"
    p.write_text(json.dumps({"agent_meta": {"model": "claude-opus-5-5", "variant": variant, "recording": turns}}))
    return p


def make_tb():
    sb = MagicMock()
    sb.compose.return_value = MagicMock(ok=True, out="", rc=0)
    sb.changes.return_value = []
    return Toolbox(sb, Policy())


def test_replay_runs_tools_and_submits(tmp_path):
    rec = write_recording(tmp_path, [
        turn(("get_recent_changes", {}), ("start_service", {"service": "api"}), text="Checking changes."),
        turn(("submit_report", {"root_causes": [{"component": "api", "category": "service_down",
                                                 "evidence": "api exited"}],
                                "summary": "started api", "recovered": True})),
    ])
    agent, tb = LLMAgent(replay=rec), make_tb()
    agent.run(tb, "PAGE: api down")
    assert tb.finished and tb.report["root_causes"][0]["component"] == "api"
    assert [e.tool for e in tb.audit] == ["get_recent_changes", "start_service", "submit_report"]
    assert agent.meta()["stop"] == "submitted"
    assert agent.transcript[0]["text"] == "Checking changes."


def test_agent_is_nudged_then_auto_reports(tmp_path):
    rec = write_recording(tmp_path, [turn(text="I think it is fine."), turn(text="Still fine.")])
    agent, tb = LLMAgent(replay=rec), make_tb()
    agent.run(tb, "PAGE")
    assert tb.finished and tb.report["recovered"] is False
    assert agent.meta()["stop"] == "no_report"


def test_ablation_hides_tools(tmp_path):
    rec = write_recording(tmp_path, [
        turn(("verify_recovery", {})),
        turn(("submit_report", {"root_causes": [], "summary": "x", "recovered": False})),
    ], variant="no_verify")
    agent, tb = LLMAgent(replay=rec), make_tb()
    agent.run(tb, "PAGE")
    assert "verify_recovery" not in [e.tool for e in tb.audit]  # hidden tool is never executed
