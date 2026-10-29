"""Rule-based runbook agent: the strongest non-LLM baseline we could write from the DEV scenarios.

It encodes what an SRE runbook would say for the failures seen during development. Its
held-out performance shows how far hand-written rules generalize to unseen failures.
"""
from __future__ import annotations

import re

from .base import Agent


class RuleBasedAgent(Agent):
    name = "rules"

    def run(self, tb, alert):
        causes: dict[tuple, str] = {}

        def act(tool, args, cause=None, evidence=""):
            tb.call(tool, args)
            if cause:
                causes[cause] = evidence

        for _ in range(3):  # a few passes: fixing one fault can reveal the next
            # 1. Dead services and missing networks.
            for line in tb.call("list_services").splitlines()[1:]:
                cols = line.split()
                svc, state, missing = cols[0], cols[1], cols[-1]
                if state in ("exited", "dead", "created"):
                    act("start_service", {"service": svc}, (svc, "service_down"), f"{svc} was {state}")
                if missing != "-":
                    for net in missing.split(","):
                        act("reconnect_network", {"service": svc, "network": net},
                            (svc, "network_partition"), f"{svc} missing from {net}")

            endpoints = tb.call("check_endpoints")
            slow = any(float(ms) > 400 for ms in re.findall(r"([\d.]+)ms", endpoints))
            if "FAIL" not in endpoints and not slow:
                break

            # 2. Gateway cannot reach its upstream right after a gateway deploy.
            if endpoints.count("status=502") >= 3:
                glog = tb.call("get_logs", {"service": "gateway", "since_seconds": 120, "grep": "upstream"})
                changes = tb.call("get_recent_changes")
                if "Connection refused" in glog and re.search(r"\bgateway\s+v\d", changes):
                    act("rollback_config", {"service": "gateway"}, ("gateway", "bad_config_deploy"),
                        "upstream connection refused after gateway deploy")

            # 3. Database auth failures after an api deploy.
            alog = tb.call("get_logs", {"service": "api", "since_seconds": 120})
            if "password authentication failed" in alog:
                act("rollback_config", {"service": "api"}, ("api", "bad_config_deploy"),
                    "db password authentication failed")

            # 4. Full data volume.
            disk = tb.call("run_diagnostic", {"service": "api", "check": "disk"})
            m = re.search(r"(\d+)%\s+/data", disk)
            if m and int(m.group(1)) >= 90:
                for size, path in re.findall(r"^(\d+)\s+(/data/tmp/\S+)$", disk, re.M):
                    act("delete_file", {"service": "api", "path": path}, ("api", "disk_full"),
                        f"/data at {m.group(1)}%")

            # 5. CPU saturation from a stray process.
            metrics = tb.call("get_metrics", {"service": "api"})
            cpu = re.search(r'"api": \{\s*"cpu_pct": "([\d.]+)%', metrics)
            if cpu and float(cpu.group(1)) > 40:
                procs = tb.call("run_diagnostic", {"service": "api", "check": "processes"})
                for pid, ppid, cmd in re.findall(r"^\s*(\d+)\s+(\d+)\s+.*?\d+%\s+(python \S+.*)$", procs, re.M):
                    if pid != "1" and ppid in ("0", "1") and "app.py" not in cmd:
                        act("kill_process", {"service": "api", "pid": int(pid)}, ("api", "cpu_exhaustion"),
                            f"{cmd} hogging CPU")
                        break

        healthy = '"healthy": true' in tb.call("verify_recovery")
        tb.call("submit_report", {
            "root_causes": [{"component": c, "category": k, "evidence": e} for (c, k), e in causes.items()],
            "summary": f"runbook applied {len(causes)} fix(es)", "recovered": healthy})
