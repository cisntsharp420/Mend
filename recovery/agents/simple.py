"""Reference baselines that bracket the problem.

- NoopAgent: does nothing. Confirms every scenario is a real, persistent failure.
- RestartAllAgent: the "turn it off and on again" operator. Shows what blind remediation buys.
"""
from __future__ import annotations

from .base import Agent


class NoopAgent(Agent):
    name = "noop"

    def run(self, tb, alert):
        tb.call("submit_report", {"root_causes": [], "summary": "no action taken", "recovered": False})


class RestartAllAgent(Agent):
    name = "restart_all"

    def run(self, tb, alert):
        for svc in ["postgres", "redis", "api", "worker", "gateway"]:
            tb.call("restart_service", {"service": svc})
        healthy = '"healthy": true' in tb.call("verify_recovery")
        tb.call("submit_report", {"root_causes": [], "summary": "restarted every service",
                                  "recovered": healthy})
