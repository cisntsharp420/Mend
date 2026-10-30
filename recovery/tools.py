"""The agent's hands and eyes: a typed tool registry with guardrails and a full audit trail.

Every agent (naive, rule-based, reasoner) acts on the system only through Toolbox.call(), so
guardrails, budgets and the audit log apply uniformly and runs are directly comparable.
"""
from __future__ import annotations

import collections
import difflib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import verifier
from .faults import CATEGORIES
from .sandbox import CONFIG_FILES, CORE_SERVICES, EXPECTED_NETWORKS, NETWORKS, STATEFUL_SERVICES, Sandbox

MAX_RESULT_CHARS = 6000
DELETABLE_PREFIXES = ("/data/tmp/",)
DIAGNOSTICS = {
    "processes": "Top processes by CPU in the service container (busybox top).",
    "disk": "Filesystem usage, plus the largest files under /data (api/worker only).",
    "dns": "Resolve the names of the other services from inside this container.",
    "connectivity": "TCP reachability from this container to its dependencies.",
    "db_activity": "Postgres sessions grouped by application/state, vs max_connections (postgres only).",
    "db_locks": "Postgres sessions that are blocked and the sessions blocking them (postgres only).",
    "redis_info": "Redis clients, memory and keyspace summary (redis only).",
    "upstream_http": "HTTP GET to the api health endpoint directly from the gateway (gateway only).",
    "gateway_config_test": "Validate the live nginx config syntax (gateway only).",
}
DEPENDENCIES = {
    "gateway": [("api", 8000)],
    "api": [("postgres", 5432), ("redis", 6379)],
    "worker": [("postgres", 5432)],
    "postgres": [],
    "redis": [],
}


class ToolError(Exception):
    """Raised for invalid or disallowed tool calls; reported back to the agent, not raised to it."""


@dataclass
class Policy:
    max_actions: int = 12              # state-changing calls per episode
    time_budget_s: float = 420         # wall clock per episode
    dry_run: bool = False              # describe actions instead of executing them
    # Called for risky actions; return False to deny. None = autonomous mode (allow, but audit).
    approver: Callable[[str, dict], bool] | None = None


@dataclass
class Tool:
    name: str
    kind: str  # observe | act | final
    description: str
    params: dict
    required: list[str]
    fn: Callable[..., str]
    risky: Callable[[dict], bool] = lambda args: False

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.params, "required": self.required}}


@dataclass
class AuditEntry:
    step: int
    t: float
    tool: str
    kind: str
    args: dict
    ok: bool
    risky: bool
    blocked: str | None
    duration_s: float
    result: str


SERVICE = {"type": "string", "enum": CORE_SERVICES, "description": "Target service."}


class Toolbox:
    def __init__(self, sb: Sandbox, policy: Policy | None = None):
        self.sb = sb
        self.policy = policy or Policy()
        self.audit: list[AuditEntry] = []
        self.report: dict | None = None
        self.t0 = time.time()
        self.actions_used = 0
        self.tools: dict[str, Tool] = {t.name: t for t in self._build()}

    # ------------------------------------------------------------------ dispatch
    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools.values()]

    def call(self, name: str, args: dict | None = None) -> str:
        args = dict(args or {})
        tool = self.tools.get(name)
        start = time.time()
        blocked, risky, ok = None, False, True
        try:
            if tool is None:
                raise ToolError(f"unknown tool '{name}'")
            risky = tool.risky(args)
            if time.time() - self.t0 > self.policy.time_budget_s:
                raise ToolError("time budget exhausted: submit your report now")
            if tool.kind == "act":
                if self.actions_used >= self.policy.max_actions:
                    raise ToolError(f"action budget of {self.policy.max_actions} exhausted")
                if risky and self.policy.approver and not self.policy.approver(name, args):
                    raise ToolError("risky action denied by human approver")
                self.actions_used += 1
                if self.policy.dry_run:
                    result = f"[dry-run] would execute {name}({json.dumps(args)})"
                else:
                    result = tool.fn(**args)
            else:
                result = tool.fn(**args)
        except ToolError as e:
            blocked, ok, result = str(e), False, f"BLOCKED: {e}"
        except TypeError as e:
            ok, result = False, f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:  # tool failures are information for the agent, not crashes
            ok, result = False, f"ERROR: {type(e).__name__}: {e}"
        result = _truncate(str(result))
        self.audit.append(AuditEntry(len(self.audit) + 1, round(start - self.t0, 2), name,
                                     tool.kind if tool else "unknown", args, ok, risky, blocked,
                                     round(time.time() - start, 2), result))
        return result

    @property
    def finished(self) -> bool:
        return self.report is not None

    # ------------------------------------------------------------------ validation helpers
    @staticmethod
    def _svc(service: str) -> str:
        if service not in CORE_SERVICES:
            raise ToolError(f"unknown or out-of-scope service '{service}'; valid: {CORE_SERVICES}")
        return service

    # ------------------------------------------------------------------ observe
    def list_services(self) -> str:
        rows = ["service   state       restarts  oom    health   networks             missing_networks"]
        for s in CORE_SERVICES:
            st = self.sb.service_state(s)
            nets = st.get("networks", [])
            missing = sorted(EXPECTED_NETWORKS[s] - set(nets))
            rows.append(f"{s:9s} {st['state']:11s} {st.get('restart_count', 0):<9} "
                        f"{str(st.get('oom_killed', '-')):6s} {str(st.get('health') or '-'):8s} "
                        f"{','.join(nets) or '-':20s} {','.join(missing) or '-'}")
        return "\n".join(rows)

    def check_endpoints(self) -> str:
        res = verifier.run_probes(self.sb)
        return "\n".join(f"{r.method:4s} {r.path:20s} status={r.status:<3d} {r.latency_ms:7.1f}ms "
                         f"{'OK' if r.ok else 'FAIL ' + _compact(r.detail)}" for r in res)

    def get_logs(self, service: str, since_seconds: int = 300, tail: int = 60, grep: str | None = None) -> str:
        raw = self.sb.logs(self._svc(service), since_s=int(since_seconds), tail=2000)
        lines = raw.splitlines()
        if grep:
            rx = re.compile(grep, re.I)
            lines = [l for l in lines if rx.search(l)]
        patterns = collections.Counter(_normalize(l) for l in lines)
        top = "\n".join(f"  {n:5d}x {p[:180]}" for p, n in patterns.most_common(8))
        body = "\n".join(l[:300] for l in lines[-int(tail):])
        return (f"{len(lines)} lines in last {since_seconds}s"
                f"{' matching ' + repr(grep) if grep else ''}.\nTop message patterns:\n{top}\n"
                f"--- last {min(len(lines), int(tail))} lines ---\n{body}")

    def get_metrics(self, service: str | None = None) -> str:
        out: dict[str, Any] = {"containers": {k: v for k, v in self.sb.stats().items() if k in CORE_SERVICES}}
        if service in (None, "api"):
            r = self.sb.exec("api", "wget -qO- -T 3 http://localhost:8000/metrics")
            out["api_app_metrics"] = json.loads(r.out) if r.ok and r.out.startswith("{") else f"unavailable: {r.out[:200]}"
        if service in (None, "postgres"):
            r = self.sb.psql("SELECT count(*), (SELECT setting FROM pg_settings WHERE name='max_connections') "
                             "FROM pg_stat_activity WHERE backend_type='client backend'")
            out["postgres_connections"] = r.out if r.ok else f"unavailable: {r.out[:200]}"
        return json.dumps(out, indent=1)

    def get_recent_changes(self, limit: int = 10) -> str:
        now = time.time()
        rows = [f"{(now - c['ts']) / 60:5.1f} min ago  {c['service']:8s} v{c.get('version', '?')}  "
                f"by {c['author']:18s} {c['summary']}" for c in self.sb.changes()[-int(limit):]]
        return "\n".join(reversed(rows)) or "no changes recorded"

    def get_config(self, service: str, version: int | None = None, diff_against: int | None = None) -> str:
        if service not in CONFIG_FILES:
            raise ToolError(f"no managed config for '{service}'; configurable: {list(CONFIG_FILES)}")
        versions = self.sb.config_versions(service)
        header = f"{service} config versions: {versions}; live = v{self.sb.current_version(service)}\n"
        text = self.sb.read_config(service, version)
        if diff_against is not None:
            old = self.sb.read_config(service, diff_against)
            diff = difflib.unified_diff(old.splitlines(), text.splitlines(), f"v{diff_against}",
                                        f"v{version}" if version else "live", lineterm="")
            return header + ("\n".join(diff) or "(no differences)")
        return header + text

    def run_diagnostic(self, service: str, check: str) -> str:
        self._svc(service)
        if check not in DIAGNOSTICS:
            raise ToolError(f"unknown check '{check}'; valid: {list(DIAGNOSTICS)}")
        sb = self.sb
        if check == "processes":
            r = sb.exec(service, "top -b -n 1 | head -25")
        elif check == "disk":
            cmd = "df -h"
            if service in ("api", "worker"):
                cmd += "; echo '--- largest under /data (KB) ---'; du -a /data 2>/dev/null | sort -rn | head -12"
            r = sb.exec(service, cmd)
        elif check == "dns":
            hosts = " ".join(s for s in CORE_SERVICES if s != service)
            r = sb.exec(service, f"for h in {hosts}; do printf '%-9s ' $h; getent hosts $h || echo 'NOT RESOLVABLE'; done")
        elif check == "connectivity":
            deps = DEPENDENCIES[service]
            if not deps:
                return f"{service} has no outbound dependencies"
            cmd = "; ".join(f"printf '{h}:{p} '; nc -z -w 2 {h} {p} 2>&1 && echo open || echo 'UNREACHABLE'"
                            for h, p in deps)
            r = sb.exec(service, cmd)
        elif check in ("db_activity", "db_locks"):
            if service != "postgres":
                raise ToolError(f"{check} only runs on postgres")
            if check == "db_activity":
                r = sb.psql("SELECT coalesce(nullif(application_name,''),'(none)') app, state, count(*), "
                            "max(round(extract(epoch from now()-state_change))) AS max_age_s, "
                            "string_agg(pid::text, ',') AS pids "
                            "FROM pg_stat_activity WHERE backend_type='client backend' AND pid <> pg_backend_pid() "
                            "GROUP BY 1,2 ORDER BY 3 DESC")
                mc = sb.psql("SHOW max_connections")
                return f"max_connections={mc.out}\napp | state | count | max_age_s | pids\n{r.out}"
            r = sb.psql("SELECT a.pid AS blocked_pid, a.application_name, left(a.query,60), "
                        "round(extract(epoch from now()-a.query_start)) AS waiting_s, b.pid AS blocking_pid, "
                        "b.application_name AS blocking_app, b.state, left(b.query,80) AS blocking_query "
                        "FROM pg_stat_activity a JOIN LATERAL unnest(pg_blocking_pids(a.pid)) bp(pid) ON true "
                        "JOIN pg_stat_activity b ON b.pid = bp.pid")
            return ("blocked_pid | app | query | waiting_s | blocking_pid | blocking_app | state | blocking_query\n"
                    + (r.out or "(no blocked sessions)"))
        elif check == "redis_info":
            if service != "redis":
                raise ToolError("redis_info only runs on redis")
            r = sb.exec("redis", "redis-cli info clients | grep -E 'connected|blocked'; "
                                 "redis-cli info memory | grep -E 'used_memory_human|maxmemory_human'; "
                                 "redis-cli info keyspace")
        elif check == "upstream_http":
            if service != "gateway":
                raise ToolError("upstream_http only runs on gateway")
            r = sb.exec("gateway", "wget -qO- -T 3 http://api:8000/api/health 2>&1; echo; "
                                   "grep -n 'server ' /etc/nginx/live/nginx.conf")
        else:  # gateway_config_test
            if service != "gateway":
                raise ToolError("gateway_config_test only runs on gateway")
            r = sb.exec("gateway", "nginx -t -c /etc/nginx/live/nginx.conf")
        return r.out or "(no output)"

    def verify_recovery(self) -> str:
        res = verifier.soak(self.sb, duration_s=8, interval_s=1)
        return json.dumps({"healthy": res.passed, "probe_success_rate": res.success_rate,
                           "probe_p95_ms": res.p95_ms, "problems": res.failures,
                           "probes": res.probe_summary}, indent=1)

    # ------------------------------------------------------------------ act
    def restart_service(self, service: str) -> str:
        r = self.sb.compose("restart", self._svc(service), timeout=90)
        return f"restarted {service}: {'ok' if r.ok else r.out[-300:]}"

    def start_service(self, service: str) -> str:
        r = self.sb.compose("start", self._svc(service), timeout=90)
        return f"started {service}: {'ok' if r.ok else r.out[-300:]}"

    def stop_service(self, service: str) -> str:
        r = self.sb.compose("stop", self._svc(service), timeout=90)
        return f"stopped {service}: {'ok' if r.ok else r.out[-300:]}"

    def rollback_config(self, service: str, to_version: int | None = None) -> str:
        if service not in CONFIG_FILES:
            raise ToolError(f"no managed config for '{service}'")
        versions = self.sb.config_versions(service)
        current = self.sb.current_version(service)
        if to_version is None:
            older = [v for v in versions if v < current] if current > 0 else versions[:-1]
            if not older:
                raise ToolError(f"{service} is already at its oldest version v{versions[0]}")
            to_version = older[-1]
        if to_version not in versions:
            raise ToolError(f"{service} has no version v{to_version}; available: {versions}")
        self.sb.restore_config(service, int(to_version))
        self.sb.record_change(service, f"rollback to v{to_version}", "recovery-agent", version=to_version)
        r = self.sb.apply_config(service)
        return f"{service} config rolled back v{current} -> v{to_version}; applied: {'ok' if r.ok else r.out[-300:]}"

    def kill_process(self, service: str, pid: int) -> str:
        pid = int(pid)
        if pid <= 1:
            raise ToolError("refusing to kill PID 1 (the service's main process); use restart_service")
        r = self.sb.exec(self._svc(service), f"kids=$(pgrep -P {pid}); kill -TERM {pid} $kids && "
                                             f"echo killed {pid} and children: $kids")
        return r.out or f"kill returned rc={r.rc}"

    def delete_file(self, service: str, path: str) -> str:
        if ".." in path or any(c in path for c in "*?[]{};&|$` ") or not path.startswith(DELETABLE_PREFIXES):
            raise ToolError(f"path not allowed; only single files under {DELETABLE_PREFIXES} may be deleted")
        r = self.sb.exec(self._svc(service), f"ls -la '{path}' && rm -f '{path}' && echo deleted")
        return r.out

    def terminate_db_sessions(self, pid: int | None = None, application_name: str | None = None) -> str:
        if pid is None and not application_name:
            raise ToolError("give a pid or an application_name")
        if pid is not None:
            where = f"pid = {int(pid)}"
        else:
            if not re.fullmatch(r"[\w.-]+", application_name):
                raise ToolError("application_name must be an exact name (no wildcards)")
            where = f"application_name = '{application_name}'"
        r = self.sb.psql(f"SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                         f"WHERE {where} AND pid <> pg_backend_pid()")
        return f"terminated sessions: {r.out}" if r.ok else f"failed: {r.out}"

    def reconnect_network(self, service: str, network: str) -> str:
        self._svc(service)
        if network not in NETWORKS or network not in EXPECTED_NETWORKS[service]:
            raise ToolError(f"{service} does not belong on network '{network}'")
        r = self.sb.docker("network", "connect", "--alias", service, self.sb.network(network),
                           self.sb.container(service))
        return f"connected {service} to {network}: {'ok' if r.ok else r.out}"

    # ------------------------------------------------------------------ final
    def submit_report(self, root_causes: list, summary: str, recovered: bool) -> str:
        clean = []
        for rc in root_causes or []:
            if rc.get("component") not in CORE_SERVICES or rc.get("category") not in CATEGORIES:
                raise ToolError(f"invalid root cause {rc}; component in {CORE_SERVICES}, category in {CATEGORIES}")
            clean.append({"component": rc["component"], "category": rc["category"],
                          "evidence": str(rc.get("evidence", ""))[:500]})
        self.report = {"root_causes": clean, "summary": summary, "recovered": bool(recovered)}
        return "report submitted"

    # ------------------------------------------------------------------ registry
    def _build(self) -> list[Tool]:
        int_ = {"type": "integer"}
        return [
            Tool("list_services", "observe", "State of every core service: running/exited/restarting, "
                 "restart count, OOM-kill flag, attached networks and any missing expected networks.",
                 {}, [], self.list_services),
            Tool("check_endpoints", "observe", "Run one pass of synthetic user requests through the gateway "
                 "and report status code and latency for each endpoint.", {}, [], self.check_endpoints),
            Tool("get_logs", "observe", "Recent logs of a service with the most frequent message patterns "
                 "summarized first. Optional case-insensitive regex filter.",
                 {"service": SERVICE, "since_seconds": {**int_, "default": 300}, "tail": {**int_, "default": 60},
                  "grep": {"type": "string"}}, ["service"], self.get_logs),
            Tool("get_metrics", "observe", "Container CPU/memory for all services, plus api application "
                 "metrics (per-endpoint p50/p95 latency, 5xx, process RSS) and postgres connection count.",
                 {"service": {"type": "string", "enum": ["api", "postgres"],
                              "description": "Limit app-level metrics to one service (optional)."}},
                 [], self.get_metrics),
            Tool("get_recent_changes", "observe", "Deployment / configuration change log, newest first.",
                 {"limit": {**int_, "default": 10}}, [], self.get_recent_changes),
            Tool("get_config", "observe", "Show a service's managed config (live or a given version), or a "
                 "unified diff of it against another version. Configurable services: api, gateway.",
                 {"service": {"type": "string", "enum": list(CONFIG_FILES)},
                  "version": {**int_, "description": "Version to show; omit for the live config."},
                  "diff_against": {**int_, "description": "Show a diff from this version to `version`/live."}},
                 ["service"], self.get_config),
            Tool("run_diagnostic", "observe", "Run a predefined read-only diagnostic inside a service. Checks: "
                 + "; ".join(f"{k}: {v}" for k, v in DIAGNOSTICS.items()),
                 {"service": SERVICE, "check": {"type": "string", "enum": list(DIAGNOSTICS)}},
                 ["service", "check"], self.run_diagnostic),
            Tool("verify_recovery", "observe", "Run synthetic checks for ~8s and report whether the system "
                 "looks healthy (probe success, latency, services running, no restarts).",
                 {}, [], self.verify_recovery),
            Tool("restart_service", "act", "Restart a service container. Clears in-process state; does NOT "
                 "fix bad config, network attachment, or problems in other services.",
                 {"service": SERVICE}, ["service"], self.restart_service,
                 risky=lambda a: a.get("service") in STATEFUL_SERVICES),
            Tool("start_service", "act", "Start a stopped service container.",
                 {"service": SERVICE}, ["service"], self.start_service),
            Tool("stop_service", "act", "Stop a service container. Usually harmful; only to contain damage.",
                 {"service": SERVICE}, ["service"], self.stop_service, risky=lambda a: True),
            Tool("rollback_config", "act", "Restore a previous config version and apply it (api restarts, "
                 "gateway reloads). Defaults to the version before the live one.",
                 {"service": {"type": "string", "enum": list(CONFIG_FILES)}, "to_version": int_},
                 ["service"], self.rollback_config),
            Tool("kill_process", "act", "Send SIGTERM to a non-main process (and its children) in a service.",
                 {"service": SERVICE, "pid": int_}, ["service", "pid"], self.kill_process),
            Tool("delete_file", "act", "Delete one file. Only paths under /data/tmp/ are permitted.",
                 {"service": SERVICE, "path": {"type": "string"}}, ["service", "path"], self.delete_file),
            Tool("terminate_db_sessions", "act", "Terminate Postgres sessions by pid or exact application_name.",
                 {"pid": int_, "application_name": {"type": "string"}}, [], self.terminate_db_sessions,
                 risky=lambda a: bool(a.get("application_name"))),
            Tool("reconnect_network", "act", "Re-attach a service to a docker network it should be on "
                 "(restores its DNS alias).",
                 {"service": SERVICE, "network": {"type": "string", "enum": sorted(NETWORKS)}},
                 ["service", "network"], self.reconnect_network),
            Tool("submit_report", "final", "Finish the incident: report root cause(s), what you did, and "
                 "whether you believe the system recovered. Call exactly once, at the end.",
                 {"root_causes": {"type": "array", "items": {"type": "object", "properties": {
                     "component": {"type": "string", "enum": CORE_SERVICES},
                     "category": {"type": "string", "enum": CATEGORIES},
                     "evidence": {"type": "string"}}, "required": ["component", "category", "evidence"]}},
                  "summary": {"type": "string"}, "recovered": {"type": "boolean"}},
                 ["root_causes", "summary", "recovered"], self.submit_report),
        ]


_NUM = re.compile(r"\b\d[\d.:\-T]*\b|0x[0-9a-f]+")


def _normalize(line: str) -> str:
    """Collapse a log line to a pattern (numbers/timestamps masked) for frequency counting."""
    line = re.sub(r"^\S+\s+", "", line, count=1) if re.match(r"^\d{4}-\d\d-\d\dT", line) else line
    return _NUM.sub("#", line).strip()


def _compact(text: str) -> str:
    """Strip HTML and collapse whitespace so error bodies stay short."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:120]


def _truncate(s: str) -> str:
    if len(s) <= MAX_RESULT_CHARS:
        return s
    half = MAX_RESULT_CHARS // 2
    return s[:half] + f"\n... [{len(s) - MAX_RESULT_CHARS} chars truncated] ...\n" + s[-half:]
