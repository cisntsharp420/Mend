"""OpenAI backend for the LLM incident-response agent (Chat Completions, manual tool-use loop).

Same system prompt, ablation variants, toolbox, budgets and record/replay as the Claude agent, so the
two backends are scored identically; only the wire format differs. Chat Completions does not return
reasoning summaries, so the transcript keeps the model's visible text and tool calls only.
"""
from __future__ import annotations

import json
import os
import time

from .llm import MAX_MODEL_CALLS, VARIANTS, LLMAgent

DEFAULT_MODEL = os.environ.get("RECOVERY_OPENAI_MODEL", "gpt-5.5")


def _prices() -> tuple[float, float, float] | None:
    """USD per million tokens (input, output, cached input) from RECOVERY_OPENAI_PRICES="in,out,cached"."""
    raw = os.environ.get("RECOVERY_OPENAI_PRICES")
    if not raw:
        return None
    i, o, c = (float(x) for x in raw.split(","))
    return i, o, c


class OpenAIAgent(LLMAgent):
    name = "llm_openai"

    def __init__(self, model: str | None = None, **kwargs):
        super().__init__(model=model or DEFAULT_MODEL, **kwargs)

    def _make_client(self):
        import openai
        return openai.OpenAI(max_retries=4)

    # ------------------------------------------------------------------ model call
    def _call(self, tools: list, messages: list) -> dict:
        if self.replay is not None:
            if self.usage["calls"] >= len(self.replay):
                raise RuntimeError("replay exhausted: the live run diverged from the recording")
            resp = self.replay[self.usage["calls"]]
        else:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                reasoning_effort=self.effort,
                max_completion_tokens=16000,
                prompt_cache_key=f"agentic-recovery-{self.variant}",  # route turns to the same prompt cache
            )
            u = r.usage
            cached = (u.prompt_tokens_details.cached_tokens or 0) if u.prompt_tokens_details else 0
            self.usage["input"] += (u.prompt_tokens or 0) - cached
            self.usage["output"] += u.completion_tokens or 0
            self.usage["cache_read"] += cached
            choice = r.choices[0]
            resp = {"stop_reason": choice.finish_reason, "model": r.model,
                    "message": choice.message.model_dump(mode="json", exclude_none=True)}
        self.usage["calls"] += 1
        self.recording.append(resp)
        return resp

    # ------------------------------------------------------------------ loop
    def run(self, tb, alert: str) -> None:
        spec = VARIANTS[self.variant]
        tools = [{"type": "function", "function": {"name": s["name"], "description": s["description"],
                                                   "parameters": s["input_schema"]}}
                 for s in tb.schemas() if s["name"] not in spec["hide"]]
        allowed = {t["function"]["name"] for t in tools}
        messages = [{"role": "system", "content": spec["prompt"]}, {"role": "user", "content": alert}]
        nudged = False

        while not tb.finished and self.usage["calls"] < MAX_MODEL_CALLS:
            resp = self._call(tools, messages)
            msg = resp["message"]
            messages.append(msg)
            self._log_turn(tb, msg)

            if msg.get("refusal"):
                self.stop = "refusal"
                break
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                if nudged:
                    self.stop = "no_report"
                    break
                nudged = True
                messages.append({"role": "user", "content": "You have not called submit_report yet. "
                                 "Continue the investigation or submit your report."})
                continue

            for c in tool_calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError as e:
                    out = f"ERROR: arguments are not valid JSON ({e})"
                else:
                    out = tb.call(name, args) if name in allowed else f"ERROR: tool {name} is not available"
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            elapsed = time.time() - tb.t0
            messages.append({"role": "user", "content": f"[budget] actions used {tb.actions_used}/"
                             f"{tb.policy.max_actions}, elapsed {elapsed:.0f}s/{tb.policy.time_budget_s:.0f}s"})

        if not tb.finished:
            self.stop = self.stop or "max_calls"
            tb.call("submit_report", {"root_causes": [], "recovered": False,
                                      "summary": f"agent ended without a report ({self.stop})"})
        self.stop = self.stop or "submitted"

    def _log_turn(self, tb, msg: dict) -> None:
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = c["function"].get("arguments")
            calls.append({"name": c["function"]["name"], "input": args})
        self.transcript.append({"call": self.usage["calls"], "t": round(time.time() - tb.t0, 1), "thinking": "",
                                "text": msg.get("content") or "", "tool_calls": calls})

    # ------------------------------------------------------------------ metadata
    def cost_usd(self) -> float | None:
        p = _prices()
        if not p or self.replay is not None:
            return None
        u = self.usage
        return round((u["input"] * p[0] + u["output"] * p[1] + u["cache_read"] * p[2]) / 1e6, 4)
