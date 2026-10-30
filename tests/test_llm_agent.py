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


# ---------------------------------------------------------------- OpenAI backend (fake client)
def oa_response(*calls, text=None, finish="tool_calls"):
    tcs = [MagicMock(id=f"c{i}", function=MagicMock(arguments=json.dumps(a))) for i, (n, a) in enumerate(calls)]
    for tc, (n, _) in zip(tcs, calls):
        tc.function.name = n   # `name` is reserved by MagicMock's constructor
    msg = MagicMock(content=text, tool_calls=tcs or None, refusal=None)
    usage = MagicMock(prompt_tokens=100, completion_tokens=20, prompt_tokens_details=MagicMock(cached_tokens=40))
    return MagicMock(choices=[MagicMock(message=msg, finish_reason=finish)], model="gpt-5", usage=usage)


def test_openai_backend_translates_loop(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")   # client is constructed, then replaced by a fake
    agent = LLMAgent(model="gpt-5", effort="max")
    agent.client = MagicMock()
    agent.client.chat.completions.create.side_effect = [
        oa_response(("get_recent_changes", {}), text="Looking."),
        oa_response(("submit_report", {"root_causes": [], "summary": "ok", "recovered": True})),
    ]
    tb = make_tb()
    agent.run(tb, "PAGE")
    assert tb.finished and agent.meta()["stop"] == "submitted" and agent.provider == "openai"
    second = agent.client.chat.completions.create.call_args_list[1].kwargs
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"]   # budget note follows tool result
    assert second["messages"][2]["tool_calls"][0]["function"]["name"] == "get_recent_changes"
    assert second["messages"][3]["tool_call_id"] == "c0"
    assert second["reasoning_effort"] == "high"
    assert second["tools"][0]["type"] == "function"
    assert agent.usage == {"input": 120, "output": 40, "cache_read": 80, "cache_write": 0, "calls": 2}
    assert agent.recording[0]["content"][1]["type"] == "tool_use"   # recorded in provider-neutral form


def test_openai_recording_replays(tmp_path):
    rec = tmp_path / "episode.json"
    rec.write_text(json.dumps({"agent_meta": {"model": "gpt-5", "variant": "full", "recording": [
        {"stop_reason": "tool_use", "model": "gpt-5", "content": [
            {"type": "tool_use", "id": "c0", "name": "submit_report",
             "input": {"root_causes": [], "summary": "x", "recovered": False}}]}]}}))
    agent, tb = LLMAgent(replay=rec), make_tb()
    agent.run(tb, "PAGE")
    assert tb.finished and agent.provider == "openai" and agent.cost_usd() is None
