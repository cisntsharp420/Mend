"""Exercise the OpenAI agent loop offline with scripted recordings (no API key, no docker)."""
import json
from unittest.mock import MagicMock

import pytest

from recovery.agents.openai_agent import OpenAIAgent
from recovery.tools import Policy, Toolbox


def turn(*calls, text=None):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [{"id": f"c{i}", "type": "function",
                              "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}}
                             for i, (n, a) in enumerate(calls)]
    return {"stop_reason": "tool_calls" if calls else "stop", "model": "gpt-5.5", "message": msg}


def write_recording(tmp_path, turns, variant="full"):
    p = tmp_path / "episode.json"
    p.write_text(json.dumps({"agent_meta": {"model": "gpt-5.5", "variant": variant, "recording": turns}}))
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
    agent, tb = OpenAIAgent(replay=rec), make_tb()
    agent.run(tb, "PAGE: api down")
    assert tb.finished and tb.report["root_causes"][0]["component"] == "api"
    assert [e.tool for e in tb.audit] == ["get_recent_changes", "start_service", "submit_report"]
    assert agent.meta()["stop"] == "submitted" and agent.meta()["model"] == "gpt-5.5"
    assert agent.transcript[0]["text"] == "Checking changes."


def test_agent_is_nudged_then_auto_reports(tmp_path):
    rec = write_recording(tmp_path, [turn(text="I think it is fine."), turn(text="Still fine.")])
    agent, tb = OpenAIAgent(replay=rec), make_tb()
    agent.run(tb, "PAGE")
    assert tb.finished and tb.report["recovered"] is False
    assert agent.meta()["stop"] == "no_report"


def test_ablation_hides_tools_and_bad_json_is_reported(tmp_path):
    rec = write_recording(tmp_path, [
        turn(("verify_recovery", {}), ("get_recent_changes", "{not json")),
        turn(("submit_report", {"root_causes": [], "summary": "x", "recovered": False})),
    ], variant="no_verify")
    agent, tb = OpenAIAgent(replay=rec), make_tb()
    agent.run(tb, "PAGE")
    assert [e.tool for e in tb.audit] == ["submit_report"]  # hidden tool and malformed call never execute


def test_live_call_shape_and_cost(monkeypatch):
    """Non-replay path: request kwargs, response parsing and cost accounting with real SDK types."""
    pytest.importorskip("openai")
    from openai.types.chat import ChatCompletion

    monkeypatch.setenv("RECOVERY_OPENAI_PRICES", "1,10,0.1")
    monkeypatch.setattr(OpenAIAgent, "_make_client", lambda self: MagicMock())
    agent, tb = OpenAIAgent(), make_tb()
    agent.client.chat.completions.create.return_value = ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "gpt-5.5",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": [{"id": "c0", "type": "function", "function": {
                "name": "submit_report",
                "arguments": json.dumps({"root_causes": [], "summary": "x", "recovered": False})}}]}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
                  "prompt_tokens_details": {"cached_tokens": 400}},
    })
    agent.run(tb, "PAGE")
    kw = agent.client.chat.completions.create.call_args.kwargs
    assert kw["messages"][0]["role"] == "system" and kw["reasoning_effort"] == "high"
    assert {t["function"]["name"] for t in kw["tools"]} >= {"submit_report", "verify_recovery"}
    assert tb.finished and agent.meta()["stop"] == "submitted"
    assert agent.usage["input"] == 600 and agent.usage["cache_read"] == 400
    assert agent.cost_usd() == round((600 * 1 + 100 * 10 + 400 * 0.1) / 1e6, 4)
