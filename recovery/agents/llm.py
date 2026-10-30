"""LLM incident-response agent (Claude, manual tool-use loop).

Design choices:
- The model only acts through the shared Toolbox, so guardrails/budgets/audit match the baselines.
- Adaptive thinking with summarized display: the reasoning summary is kept in the trace, which
  makes every decision inspectable after the fact.
- Ablation variants switch off one capability at a time (verification, change awareness,
  diagnostics, the methodology prompt) to measure what each component contributes.
- Record/replay: every model response is saved in the episode record; `replay=<episode.json>`
  re-runs that episode from the recording without an API key (tool calls still execute live).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..faults import CATEGORIES
from ..sandbox import CONFIG_FILES, CORE_SERVICES
from .base import Agent

DEFAULT_MODEL = os.environ.get("RECOVERY_MODEL", "claude-opus-5-5")
# USD per million tokens: input, output, cache read. Cache writes bill at 1.25x input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
MAX_MODEL_CALLS = 40

SYSTEM_PROMPT = f"""You are the on-call SRE agent for ShopStack, a small e-commerce system. You were \
paged because synthetic monitoring is failing. Restore service safely, prove it is restored, and \
report the root cause(s).

System you are responsible for:
- Traffic: users -> gateway (nginx, frontend network) -> api (Python, frontend+backend networks) -> \
postgres (data) and redis (cache, backend network). worker (backend) runs periodic jobs against postgres.
- The api degrades without redis (falls back to postgres) but reports itself unhealthy.
- Managed configs with version history: {", ".join(CONFIG_FILES)}. Deploys are in the change log.
- The api writes to a small /data volume; only files under /data/tmp/ are disposable.

How to work:
- Investigate before acting. Form explicit hypotheses and confirm them with evidence \
(logs, metrics, diagnostics, config diffs, change log). Call several read-only tools at once when useful.
- More than one independent fault may be present, and fixing one can reveal another that was \
masked. Keep going until verify_recovery reports healthy.
- Fix root causes with the least invasive, reversible action. Restarting does not fix bad config, \
missing networks, external load, or locks held by another session; it only hides symptoms briefly.
- Recent deploys are prime suspects, but not every recent change is guilty: check the diff. \
When rolling back, choose the last version that is actually good, which may be more than one step back.
- You have a limited action budget; observation is free. Never stop services or kill main processes \
unless it is the only way to contain damage.
- Finish with submit_report. Categories: {", ".join(CATEGORIES)}. Report one entry per distinct \
root cause, naming the component where the cause lives (e.g. the service whose config or process \
is at fault), not every service that showed symptoms. Add up to three short recommendations: \
anything still needed to fix the incident, and how to prevent it from happening again."""

MINIMAL_PROMPT = ("You are an SRE agent. The ShopStack system is failing. Use the tools to fix it, "
                  "then call submit_report.")

# Ablation variants: which tools to hide and which prompt to use.
VARIANTS = {
    "full": {"hide": set(), "prompt": SYSTEM_PROMPT},
    "no_verify": {"hide": {"verify_recovery"}, "prompt": SYSTEM_PROMPT.replace(
        " Keep going until verify_recovery reports healthy.", "")},
    "no_changes": {"hide": {"get_recent_changes", "get_config"}, "prompt": SYSTEM_PROMPT},
    "no_diagnostics": {"hide": {"run_diagnostic"}, "prompt": SYSTEM_PROMPT},
    "minimal_prompt": {"hide": set(), "prompt": MINIMAL_PROMPT},
}


class LLMAgent(Agent):
    name = "llm"

    def __init__(self, model: str | None = None, variant: str | None = None, effort: str = "high",
                 replay: str | Path | None = None):
        self.model = model or DEFAULT_MODEL
        self.variant = variant or "full"
        if self.variant not in VARIANTS:
            raise ValueError(f"unknown variant {self.variant}; choose from {list(VARIANTS)}")
        self.effort = effort
        self.replay = None
        if replay:
            recorded = json.loads(Path(replay).read_text())["agent_meta"]
            self.replay = recorded["recording"]
            self.model, self.variant = recorded["model"], recorded["variant"]
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "calls": 0}
        self.transcript: list[dict] = []   # reasoning + text per model turn (for the trace viewer)
        self.recording: list[dict] = []    # raw responses (for replay)
        self.stop = None
        if not self.replay:
            import anthropic
            self.client = anthropic.Anthropic(max_retries=4)

    # ------------------------------------------------------------------ model call
    def _call(self, system: str, tools: list, messages: list) -> dict:
        if self.replay is not None:
            if self.usage["calls"] >= len(self.replay):
                raise RuntimeError("replay exhausted: the live run diverged from the recording")
            resp = self.replay[self.usage["calls"]]
        else:
            r = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": self.effort},
                cache_control={"type": "ephemeral"},     # caches the growing conversation prefix
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",                     # retry on a fallback model if declined
            )
            u = r.usage
            self.usage["input"] += u.input_tokens or 0
            self.usage["output"] += u.output_tokens or 0
            self.usage["cache_read"] += u.cache_read_input_tokens or 0
            self.usage["cache_write"] += u.cache_creation_input_tokens or 0
            resp = {"stop_reason": r.stop_reason, "model": r.model,
                    "content": [b.model_dump(mode="json", exclude_none=True) for b in r.content]}
        self.usage["calls"] += 1
        self.recording.append(resp)
        return resp

    # ------------------------------------------------------------------ loop
    def run(self, tb, alert: str) -> None:
        spec = VARIANTS[self.variant]
        tools = [s for s in tb.schemas() if s["name"] not in spec["hide"]]
        allowed = {t["name"] for t in tools}
        messages = [{"role": "user", "content": alert}]
        nudged = False

        while not tb.finished and self.usage["calls"] < MAX_MODEL_CALLS:
            resp = self._call(spec["prompt"], tools, messages)
            content = resp["content"]
            messages.append({"role": "assistant", "content": content})
            self._log_turn(tb, resp)

            if resp["stop_reason"] == "refusal":
                self.stop = "refusal"
                break
            tool_uses = [b for b in content if b["type"] == "tool_use"]
            if not tool_uses:
                if nudged:
                    self.stop = "no_report"
                    break
                nudged = True
                messages.append({"role": "user", "content": "You have not called submit_report yet. "
                                 "Continue the investigation or submit your report."})
                continue

            results = []
            for b in tool_uses:
                if b["name"] not in allowed:
                    out, err = f"tool {b['name']} is not available", True
                else:
                    out = tb.call(b["name"], b.get("input") or {})
                    err = out.startswith(("BLOCKED", "ERROR"))
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": out,
                                **({"is_error": True} if err else {})})
            elapsed = time.time() - tb.t0
            results.append({"type": "text", "text": f"[budget] actions used {tb.actions_used}/"
                            f"{tb.policy.max_actions}, elapsed {elapsed:.0f}s/{tb.policy.time_budget_s:.0f}s"})
            messages.append({"role": "user", "content": results})

        if not tb.finished:
            self.stop = self.stop or "max_calls"
            tb.call("submit_report", {"root_causes": [], "recovered": False,
                                      "summary": f"agent ended without a report ({self.stop})"})
        self.stop = self.stop or "submitted"

    def _log_turn(self, tb, resp: dict) -> None:
        turn = {"call": self.usage["calls"], "t": round(time.time() - tb.t0, 1), "thinking": "", "text": "",
                "tool_calls": []}
        for b in resp["content"]:
            if b["type"] == "thinking":
                turn["thinking"] += b.get("thinking", "")
            elif b["type"] == "text":
                turn["text"] += b["text"]
            elif b["type"] == "tool_use":
                turn["tool_calls"].append({"name": b["name"], "input": b.get("input")})
        self.transcript.append(turn)

    # ------------------------------------------------------------------ metadata
    def cost_usd(self) -> float | None:
        p = PRICES.get(self.model)
        if not p or self.replay is not None:
            return None
        u = self.usage
        return round((u["input"] * p[0] + u["output"] * p[1] + u["cache_read"] * p[2]
                      + u["cache_write"] * p[0] * 1.25) / 1e6, 4)

    def meta(self) -> dict:
        return {"model": self.model, "variant": self.variant, "effort": self.effort,
                "replayed": self.replay is not None, "stop": self.stop, "usage": self.usage,
                "cost_usd": self.cost_usd(), "transcript": self.transcript, "recording": self.recording}
