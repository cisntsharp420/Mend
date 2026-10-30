"""Hypothesis-driven recovery agent: reads logs and metrics, recommends a fix, applies it. No LLM, no API.

Loop: observe -> hypothesize -> recommend -> act -> re-check -> repeat.

1. Observe. Gather an evidence snapshot through the toolbox (observation is free): service states,
   synthetic endpoint checks, logs of every service (only the window since the last action, so old
   errors do not count against a fix), container and application metrics, the change log, and a few
   targeted read-only diagnostics.
2. Hypothesize. A library of generic failure-mode detectors turns evidence into hypotheses
   (component, category, remedy). Each detector cites the signals it used; confidence is a noisy-OR
   of those signal weights, so every score can be traced back to concrete log lines and metrics.
3. Recommend. Hypotheses are ranked into a recommended solution: what to do, why, and how to
   prevent it next time. In `recommend` mode the agent stops here and changes nothing.
4. Act and re-check. The most confident untried hypothesis above the action threshold is applied
   with the least invasive remedy, then the system is re-observed. A hypothesis is confirmed when
   its own symptom is gone and refuted when it persists (a refuted config rollback walks further
   back through the version history).
5. Repeat until verify_recovery passes, nothing actionable remains, or a budget runs out. Only
   confirmed causes go into the incident report.

The detectors encode general SRE knowledge of this stack (what a dead container, a full volume, a
lock queue or a bad deploy look like in logs and metrics). They were checked against the DEV
scenarios only; the held-out scenarios measure how well that knowledge generalizes.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from ..sandbox import CONFIG_FILES, CORE_SERVICES
from .base import Agent

ACT_THRESHOLD = 0.5        # minimum confidence before the agent changes anything
MAX_ROUNDS = 8
MAX_ATTEMPTS = 3           # remedies tried per hypothesis before it counts as refuted
CPU_HOT_PCT = 40.0         # container CPU that counts as saturated
SLOW_MS = 300.0            # endpoint latency that counts as degraded
DISK_FULL_PCT = 90
CONN_SATURATION = 0.75     # share of max_connections in use
DIAG_NOISE = re.compile(r"^(sh -c top|top -b|head -\d+)")

# Ablations: switch off one evidence source (or the re-check loop) to measure what it contributes.
VARIANTS = {
    "full": set(),
    "no_logs": {"logs"},
    "no_metrics": {"metrics"},
    "no_diagnostics": {"diagnostics"},
    "no_changes": {"changes"},
    "single_pass": {"recheck"},
}


# ---------------------------------------------------------------------------- log signatures
@dataclass(frozen=True)
class Signature:
    name: str
    pattern: re.Pattern
    meaning: str
    config_keys: tuple[str, ...] = ()   # config keys a bad deploy would have to touch to cause this


SIGNATURES = [
    Signature("db_auth", re.compile(r"password authentication failed|authentication failed for user", re.I),
              "the database rejected the client's credentials", ("password", "user")),
    Signature("dns", re.compile(r"could not translate host name|Name does not resolve|Name or service not known|"
                                r"bad address|Temporary failure in name resolution", re.I),
              "a hostname does not resolve", ("host",)),
    Signature("refused", re.compile(r"Connection refused", re.I),
              "the target accepted no connection on that port", ("port", "server", "upstream", "host")),
    Signature("timeout", re.compile(r"timed out|timeout expired|statement timeout|canceling statement", re.I),
              "requests are timing out", ("timeout",)),
    Signature("no_space", re.compile(r"No space left on device|Errno 28", re.I),
              "a filesystem is full"),
    Signature("too_many_conn", re.compile(r"too many clients|remaining connection slots|connection slots are reserved",
                                          re.I), "the database ran out of connection slots"),
    Signature("config_invalid", re.compile(r"config invalid|missing required config|invalid value|could not convert|"
                                           r"KeyError|unknown directive|\[emerg\]", re.I),
              "the service rejected its own configuration"),
    Signature("oom", re.compile(r"MemoryError|out of memory|Killed process|OOM", re.I),
              "a process ran out of memory", ("cache", "memory", "buffer", "pool", "size", "features")),
    Signature("crash", re.compile(r"Traceback|Fatal Python error|Segmentation fault", re.I),
              "the process crashed"),
    Signature("cache_down", re.compile(r"cache unavailable|connecting to redis", re.I),
              "the cache is unreachable"),
]
ERROR_LINE = re.compile(r"\b(ERROR|FATAL|CRITICAL|PANIC)\b|\[(error|crit|alert|emerg)\]|Traceback", re.I)
QUOTED = re.compile(r"""['"]([^'"\s]{2,60})['"]""")

PREVENTION = {
    "service_down": "add a restart policy and alert on container exits",
    "bad_config_deploy": "validate configs in CI and canary deploys with automatic rollback on error-rate spikes",
    "cpu_exhaustion": "run batch jobs outside the serving container or under a CPU quota",
    "memory_exhaustion": "set memory limits and bound in-process caches",
    "disk_full": "rotate or expire temporary exports and alert on volume usage above 80%",
    "db_lock_contention": "set lock_timeout for migrations and run them in maintenance windows",
    "db_connection_exhaustion": "use a connection pool with a per-client cap and alert on connection saturation",
    "network_partition": "monitor container network attachment and DNS resolution between services",
}


# ---------------------------------------------------------------------------- evidence
class Evidence:
    """One observation round, parsed into structured facts. Diagnostics are run lazily and cached."""

    def __init__(self, tb, since_s: int, disabled: set[str]):
        self.tb, self.disabled = tb, disabled
        self.services = _parse_services(tb.call("list_services"))
        self.endpoints = _parse_endpoints(tb.call("check_endpoints"))
        self.changes = [] if "changes" in disabled else _parse_changes(tb.call("get_recent_changes", {"limit": 20}))
        self.metrics: dict = {}
        if "metrics" not in disabled:
            try:
                self.metrics = json.loads(tb.call("get_metrics"))
            except json.JSONDecodeError:
                pass
        self.logs: dict[str, list[str]] = {}
        if "logs" not in disabled:
            for s in CORE_SERVICES:   # stopped containers keep their logs: that is where crashes show
                out = tb.call("get_logs", {"service": s, "since_seconds": since_s, "tail": 400})
                self.logs[s] = out.split("--- last", 1)[-1].splitlines()[1:]
        self._diag: dict[tuple, str] = {}

    # --- lazily evaluated diagnostics
    def diag(self, service: str, check: str) -> str:
        if "diagnostics" in self.disabled or not self.running(service):
            return ""
        if (service, check) not in self._diag:
            self._diag[(service, check)] = self.tb.call("run_diagnostic", {"service": service, "check": check})
        return self._diag[(service, check)]

    # --- facts
    def running(self, s: str) -> bool:
        return self.services.get(s, {}).get("state") == "running"

    @property
    def failing(self) -> list[dict]:
        return [e for e in self.endpoints if not e["ok"]]

    @property
    def slow(self) -> list[dict]:
        return [e for e in self.endpoints if e["ms"] >= SLOW_MS]

    @property
    def looks_healthy(self) -> bool:
        return bool(self.endpoints) and not self.failing and not self.slow

    def errors(self, service: str) -> list[str]:
        return [l for l in self.logs.get(service, []) if ERROR_LINE.search(l)]

    def signatures(self, service: str) -> dict[str, list[str]]:
        """Log signature name -> matching error lines (a log line can match several)."""
        hits: dict[str, list[str]] = {}
        for line in self.logs.get(service, []):
            for sig in SIGNATURES:
                if sig.pattern.search(line):
                    hits.setdefault(sig.name, []).append(line)
        # endpoint failure bodies carry the app's own health checks: count them as evidence too
        if service == "api":
            for e in self.failing:
                for sig in SIGNATURES:
                    if sig.pattern.search(e["detail"]):
                        hits.setdefault(sig.name, []).append(f"probe {e['path']}: {e['detail'][:100]}")
        return hits

    def cpu(self, service: str) -> float | None:
        c = (self.metrics.get("containers") or {}).get(service)
        try:
            return float(c["cpu_pct"].rstrip("%")) if c else None
        except (KeyError, ValueError):
            return None

    def app_p95(self) -> float | None:
        m = self.metrics.get("api_app_metrics")
        if not isinstance(m, dict):
            return None
        vals = [v.get("p95_ms") for v in (m.get("endpoints") or {}).values() if v.get("p95_ms") is not None]
        return max(vals) if vals else None

    def db_connections(self) -> tuple[int, int] | None:
        m = re.match(r"\s*(\d+)\s*\|\s*(\d+)", str(self.metrics.get("postgres_connections", "")))
        return (int(m.group(1)), int(m.group(2))) if m else None

    def deploys(self, service: str) -> list[dict]:
        return [c for c in self.changes if c["service"] == service and c["author"] != "recovery-agent"]


# ---------------------------------------------------------------------------- hypotheses
@dataclass
class Hypothesis:
    component: str
    category: str
    signals: list[tuple[float, str]]          # (weight, evidence) — confidence is their noisy-OR
    remedy: list[tuple[str, dict]]            # tool calls that fix it; empty = recommend only
    action: str                               # the remedy in words
    also: list[str] = field(default_factory=list)   # extra categories that describe the same cause
    invasiveness: int = 1                     # tie-breaker: lower is gentler
    note: dict = field(default_factory=dict)  # detector state (e.g. rollback target)

    @property
    def key(self) -> str:
        return f"{self.category}:{self.component}"

    @property
    def confidence(self) -> float:
        p = 1.0
        for w, _ in self.signals:
            p *= 1 - w
        return round(1 - p, 3)

    def recommendation(self) -> dict:
        return {"component": self.component, "category": self.category, "confidence": self.confidence,
                "evidence": [e for _, e in sorted(self.signals, key=lambda s: -s[0])],
                "recommended_action": self.action,
                "remedy": [{"tool": t, "args": a} for t, a in self.remedy],
                "prevention": PREVENTION.get(self.category, "")}


def detect_stopped(ev: Evidence, ctx) -> list[Hypothesis]:
    out = []
    for s, st in ev.services.items():
        if st["state"] in ("exited", "dead", "created", "paused"):
            sig = [(0.9, f"{s} container is {st['state']} (list_services)")]
            if any(s in e["detail"] or e["status"] in (502, 503, 504) for e in ev.failing):
                sig.append((0.3, f"{len(ev.failing)} endpoint(s) failing while {s} is down"))
            out.append(Hypothesis(s, "service_down", sig, [("start_service", {"service": s})],
                                  f"start the {s} container"))
    return out


def detect_partition(ev: Evidence, ctx) -> list[Hypothesis]:
    out = []
    for s, st in ev.services.items():
        for net in st["missing"]:
            sig = [(0.9, f"{s} is not attached to the {net} network it belongs on (list_services)")]
            dns_hits = [l for svc in ev.logs for l in ev.signatures(svc).get("dns", [])]
            if dns_hits:
                sig.append((0.4, f"{len(dns_hits)} name-resolution errors in logs, e.g. {_short(dns_hits[-1])}"))
            out.append(Hypothesis(s, "network_partition", sig,
                                  [("reconnect_network", {"service": s, "network": net})],
                                  f"re-attach {s} to the {net} network (restores its DNS name)"))
    return out


def detect_disk(ev: Evidence, ctx) -> list[Hypothesis]:
    out = []
    for s in ("api", "worker"):
        disk = ev.diag(s, "disk")
        m = re.search(r"(\d+)%\s+/data\s*$", disk, re.M)
        if not m or int(m.group(1)) < DISK_FULL_PCT:
            continue
        used = int(m.group(1))
        sig = [(0.7, f"{s} /data volume is {used}% full (run_diagnostic disk)")]
        hits = ev.signatures(s).get("no_space", [])
        if hits:
            sig.append((0.4, f"{len(hits)} 'No space left on device' errors, e.g. {_short(hits[-1])}"))
        files = [(int(kb), p) for kb, p in re.findall(r"^(\d+)\s+(/data/tmp/\S+)$", disk, re.M)]
        files = [f for f in sorted(files, reverse=True) if not any(o[1].startswith(f[1] + "/") for o in files)]
        remedy = [("delete_file", {"service": s, "path": p}) for _, p in files[:3]]
        action = (f"delete disposable temp files on {s}: " + ", ".join(p for _, p in files[:3]) if remedy
                  else f"free space on {s}:/data manually (no disposable files under /data/tmp)")
        out.append(Hypothesis(s, "disk_full", sig, remedy, action))
    return out


def detect_cpu(ev: Evidence, ctx) -> list[Hypothesis]:
    out = []
    for s in CORE_SERVICES:
        cpu = ev.cpu(s)
        if cpu is None or cpu < CPU_HOT_PCT:
            continue
        sig = [(0.4, f"{s} container CPU at {cpu:.0f}% (get_metrics)")]
        if s == "api" and (ev.slow or (ev.app_p95() or 0) >= SLOW_MS):
            worst = max(ev.endpoints, key=lambda e: e["ms"])
            sig.append((0.2, f"latency degraded: {worst['path']} {worst['ms']:.0f}ms"))
        stray = _stray_processes(ev.diag(s, "processes"))
        if not stray:
            continue
        target, cmd, n = stray[0]
        sig.append((0.5, f"{n} process(es) of '{cmd}' running beside the main service process (run_diagnostic processes)"))
        out.append(Hypothesis(s, "cpu_exhaustion", sig, [("kill_process", {"service": s, "pid": target})],
                              f"stop the runaway '{cmd}' job on {s} (pid {target} and its children)",
                              invasiveness=2))
    return out


def detect_db_locks(ev: Evidence, ctx) -> list[Hypothesis]:
    if not ev.running("postgres"):
        return []
    rows = [r.split("|") for r in ev.diag("postgres", "db_locks").splitlines()[1:] if r.count("|") >= 7]
    rows = [[c.strip() for c in r] for r in rows]
    if not rows:
        return []
    blocked = {r[0] for r in rows}
    roots = sorted({(r[4], r[5], r[6], r[7]) for r in rows if r[4] not in blocked})
    wait = max(float(r[3] or 0) for r in rows)
    sig = [(0.6, f"{len(rows)} session(s) blocked on locks for up to {wait:.0f}s (run_diagnostic db_locks)")]
    for pid, app, state, query in roots:
        sig.append((0.3, f"root blocker pid {pid} app={app or '?'} state={state} query={query[:60]}"))
    timeouts = [l for svc in ("api", "worker") for l in ev.signatures(svc).get("timeout", [])]
    if timeouts:
        sig.append((0.2, f"{len(timeouts)} timeout errors in api/worker logs"))
    remedy = [("terminate_db_sessions", {"pid": int(pid)}) for pid, *_ in roots[:3] if pid.isdigit()]
    return [Hypothesis("postgres", "db_lock_contention", sig, remedy,
                       "terminate the session(s) holding the blocking lock: pids "
                       + ", ".join(p for p, *_ in roots[:3]), invasiveness=2)]


def detect_conn_exhaustion(ev: Evidence, ctx) -> list[Hypothesis]:
    conns = ev.db_connections()
    hits = [l for svc in ev.logs for l in ev.signatures(svc).get("too_many_conn", [])]
    if not hits and not (conns and conns[0] >= CONN_SATURATION * conns[1]):
        return []
    sig = []
    if conns:
        sig.append((0.5 if conns[0] >= CONN_SATURATION * conns[1] else 0.1,
                    f"postgres has {conns[0]}/{conns[1]} client connections (get_metrics)"))
    if hits:
        sig.append((0.4, f"{len(hits)} 'too many clients' errors, e.g. {_short(hits[-1])}"))
    # Which application holds the slots?
    apps = []
    for row in ev.diag("postgres", "db_activity").splitlines()[2:]:
        c = [x.strip() for x in row.split("|")]
        if len(c) >= 3 and c[2].isdigit():
            apps.append((int(c[2]), c[0]))
    totals: dict[str, int] = {}
    for n, app in apps:
        totals[app] = totals.get(app, 0) + n
    if not totals:
        return [Hypothesis("postgres", "db_connection_exhaustion", sig, [],
                           "find and stop the client leaking connections (db_activity unavailable)")]
    app, n = max(totals.items(), key=lambda kv: kv[1])
    sig.append((0.3, f"application '{app}' holds {n} sessions (run_diagnostic db_activity)"))
    # Find the process that owns those sessions: a stray job whose name matches the application name.
    host, proc = None, None
    want = re.sub(r"[^a-z0-9]", "", app.lower())
    for s in ("worker", "api"):
        for pid, cmd, _ in _stray_processes(ev.diag(s, "processes")):
            if want and want in re.sub(r"[^a-z0-9]", "", cmd.lower()):
                host, proc = s, (pid, cmd)
                break
        if host:
            break
    remedy, action = [], ""
    if host:
        sig.append((0.3, f"process '{proc[1]}' on {host} matches application '{app}'"))
        remedy.append(("kill_process", {"service": host, "pid": proc[0]}))
        action = f"stop '{proc[1]}' on {host} (it keeps reconnecting), then "
    if app not in ("(none)", ""):
        remedy.append(("terminate_db_sessions", {"application_name": app}))
    action += f"terminate the '{app}' database sessions to free connection slots"
    return [Hypothesis(host or "postgres", "db_connection_exhaustion", sig, remedy, action, invasiveness=2)]


def detect_bad_config(ev: Evidence, ctx) -> list[Hypothesis]:
    """A recent deploy of this service's config explains its errors; recommend rolling back past it."""
    out = []
    for s in CONFIG_FILES:
        deploys = ev.deploys(s)
        if not deploys and "changes" not in ev.disabled:
            continue
        sig, keys, tokens, also = [], set(), set(), []
        primary = 0
        sigs = ev.signatures(s)
        st = ev.services.get(s, {})
        partitioned = any(v["missing"] for v in ev.services.values())
        stopped_dep = any(not ev.running(d) for d in ("postgres", "redis"))
        for name in ("db_auth", "config_invalid", "crash", "dns", "refused", "oom"):
            lines = sigs.get(name, [])
            if not lines:
                continue
            if name in ("dns", "refused") and (partitioned or stopped_dep) and s == "api":
                continue  # explained by a missing network or a dead dependency, not by this config
            meaning = next(x.meaning for x in SIGNATURES if x.name == name)
            sig.append((0.55, f"{len(lines)} log line(s) on {s}: {meaning}, e.g. {_short(lines[-1])}"))
            primary += 1
            keys.update(next(x.config_keys for x in SIGNATURES if x.name == name))
            for l in lines:
                tokens.update(t for t in QUOTED.findall(l) if not re.fullmatch(r"[\d.:]+", t))
            if name == "oom":
                also.append("memory_exhaustion")
        if st.get("oom"):
            sig.append((0.4, f"{s} was OOM-killed (list_services)"))
            keys.update(("cache", "memory", "buffer", "pool", "size", "features"))
            also.append("memory_exhaustion")
            primary += 1
        if st.get("restarts", 0) > 0 or st.get("state") == "restarting":
            sig.append((0.35, f"{s} is crash-looping: state={st.get('state')} restarts={st.get('restarts')}"))
            primary += 1
        if s == "gateway" and (sigs.get("refused") or sigs.get("timeout")):
            direct = ev.diag("gateway", "upstream_http")
            if '"status"' in direct:   # api answers when called directly, so the gateway's own routing is wrong
                sig.append((0.4, "api answers when called directly from the gateway, but proxied requests fail"))
        if not primary:   # supporting evidence alone never justifies undoing a deploy
            continue
        plan = _plan_rollback(ev.tb, s, keys, tokens, ctx.tried_versions.get(s, set()))
        if plan is None:
            continue
        target, culprit, why = plan
        if deploys:
            d = deploys[-1]
            sig.append((0.25, f"{s} was deployed {d['age_min']:.1f} min ago: v{d['version']} '{d['summary']}' by {d['author']}"))
        if why:
            sig.append((0.3, why))
        out.append(Hypothesis(s, "bad_config_deploy", sig, [("rollback_config", {"service": s, "to_version": target})],
                              f"roll back the {s} config to v{target} (undoing v{culprit})",
                              also=sorted(set(also)), invasiveness=1, note={"target": target}))
    return out


def detect_unexplained(ev: Evidence, ctx) -> list[Hypothesis]:
    """Last resort: endpoints fail, nothing above explains it. Recommend only (below action threshold)."""
    if not ev.failing:
        return []
    noisy = sorted(((len(ev.errors(s)), s) for s in ev.logs), reverse=True)
    if not noisy or noisy[0][0] == 0:
        return []
    n, s = noisy[0]
    return [Hypothesis(s, "service_down", [(0.3, f"{n} error lines on {s}, e.g. {_short(ev.errors(s)[-1])}")],
                       [], f"investigate {s} manually; its errors are not explained by a known failure mode",
                       invasiveness=3)]


DETECTORS = [detect_stopped, detect_partition, detect_bad_config, detect_disk, detect_cpu,
             detect_db_locks, detect_conn_exhaustion]


# ---------------------------------------------------------------------------- the agent
@dataclass
class _Context:
    tried_versions: dict[str, set[int]] = field(default_factory=dict)
    attempted: set[str] = field(default_factory=set)   # remedies already applied: never repeat one
    attempts: dict[str, int] = field(default_factory=dict)  # hypothesis key -> remedies tried


class ReasonerAgent(Agent):
    name = "reasoner"

    def __init__(self, variant: str | None = None, mode: str = "act"):
        self.variant = variant or "full"
        if self.variant not in VARIANTS:
            raise ValueError(f"unknown variant {self.variant}; choose from {list(VARIANTS)}")
        if mode not in ("act", "recommend"):
            raise ValueError("mode must be 'act' or 'recommend'")
        self.mode = mode
        self.disabled = VARIANTS[self.variant]
        self.rounds: list[dict] = []        # per round: ranked recommendations and the action taken
        self.confirmed: dict[str, Hypothesis] = {}
        self.stop = None

    def run(self, tb, alert: str) -> None:
        ctx = _Context()
        acted: dict[str, Hypothesis] = {}   # key -> last hypothesis acted on, awaiting confirmation
        last_action_t = time.time() - 120
        healthy = False
        for rnd in range(MAX_ROUNDS):
            since = int(min(120, max(8, time.time() - last_action_t + 1)))
            ev = Evidence(tb, since, self.disabled)
            hyps = self.diagnose(ev, ctx)
            live = {h.key for h in hyps}
            for k in list(acted):           # symptom gone after acting on it = confirmed
                if k not in live:
                    self.confirmed[k] = acted.pop(k)
            for k in list(self.confirmed):  # a symptom that came back was not really fixed
                if k in live:
                    acted[k] = self.confirmed.pop(k)
            log = {"round": rnd + 1, "log_window_s": since, "failing_endpoints": [e["path"] for e in ev.failing],
                   "recommendations": [h.recommendation() for h in hyps], "action": None}
            self.rounds.append(log)

            if self.mode == "recommend":
                self.stop = "recommended"
                break
            if ev.looks_healthy and not [h for h in hyps if h.confidence >= ACT_THRESHOLD]:
                v = tb.call("verify_recovery")
                log["verify"] = _verify_summary(v)
                if '"healthy": true' in v:
                    healthy, self.stop = True, "recovered"
                    break
            todo = [h for h in hyps if h.confidence >= ACT_THRESHOLD and h.remedy
                    and _remedy_id(h) not in ctx.attempted and ctx.attempts.get(h.key, 0) < MAX_ATTEMPTS]
            if not todo:
                self.stop = "nothing_actionable"
                break
            # Normally one fix per round, then re-observe. single_pass applies everything it sees at once.
            batch = todo if "recheck" in self.disabled else todo[:1]
            log["action"] = []
            for h in batch:
                if h.category == "bad_config_deploy":
                    ctx.tried_versions.setdefault(h.component, set()).add(h.note["target"])
                ctx.attempted.add(_remedy_id(h))
                ctx.attempts[h.key] = ctx.attempts.get(h.key, 0) + 1
                results = [tb.call(t, a) for t, a in h.remedy]
                log["action"].append({"hypothesis": h.key, "confidence": h.confidence,
                                      "calls": h.remedy, "results": results})
                acted[h.key] = h
            last_action_t = time.time()
            if any(r.startswith("BLOCKED") and "budget" in r for a in log["action"] for r in a["results"]):
                self.stop = "budget"
                break
            if "recheck" in self.disabled:
                self.confirmed.update(acted)   # no re-check: every applied fix is assumed to have worked
                self.stop = "single_pass"
                time.sleep(8)
                break
            time.sleep(8 if batch[0].category in ("bad_config_deploy", "service_down", "network_partition") else 5)
        else:
            self.stop = "max_rounds"

        if self.mode == "act" and not healthy:
            v = tb.call("verify_recovery")
            healthy = '"healthy": true' in v
            self.rounds[-1]["verify"] = _verify_summary(v)
        tb.call("submit_report", self.report(healthy))

    def diagnose(self, ev: Evidence, ctx: _Context) -> list[Hypothesis]:
        hyps: dict[str, Hypothesis] = {}
        for d in DETECTORS:
            for h in d(ev, ctx):
                if h.key not in hyps or h.confidence > hyps[h.key].confidence:
                    hyps[h.key] = h
        if not any(h.confidence >= ACT_THRESHOLD for h in hyps.values()):
            for h in detect_unexplained(ev, ctx):
                hyps.setdefault(h.key, h)
        return sorted(hyps.values(), key=lambda h: (-h.confidence, h.invasiveness))

    def report(self, healthy: bool) -> dict:
        if self.mode == "recommend":
            causes = [h for h in self._latest() if h["confidence"] >= ACT_THRESHOLD]
            entries = [{"component": h["component"], "category": h["category"],
                        "evidence": "; ".join(h["evidence"][:3])} for h in causes]
            return {"root_causes": entries, "recovered": False,
                    "summary": "RECOMMENDATION ONLY (no changes made). " + self.solution_text()}
        entries = []
        for h in self.confirmed.values():
            ev = "; ".join(e for _, e in sorted(h.signals, key=lambda s: -s[0])[:3])
            for cat in [h.category] + h.also:
                entries.append({"component": h.component, "category": cat, "evidence": ev})
        return {"root_causes": entries, "recovered": healthy, "summary": self.solution_text()}

    def _latest(self) -> list[dict]:
        return self.rounds[-1]["recommendations"] if self.rounds else []

    def solution_text(self) -> str:
        """The recommended solution in plain words: every fix applied (or proposed), why, and prevention."""
        lines = []
        if self.mode == "act":
            for r in self.rounds:
                for a in r["action"] or []:
                    rec = next(x for x in r["recommendations"] if f"{x['category']}:{x['component']}" == a["hypothesis"])
                    status = "confirmed" if a["hypothesis"] in self.confirmed else "not confirmed"
                    lines.append(f"[{status}] {rec['recommended_action']} (confidence {rec['confidence']:.2f}; "
                                 f"evidence: {rec['evidence'][0]}). Prevent: {rec['prevention']}.")
        else:
            for rec in self._latest():
                lines.append(f"{rec['recommended_action']} (confidence {rec['confidence']:.2f}; "
                             f"evidence: {rec['evidence'][0]}). Prevent: {rec['prevention']}.")
        return " | ".join(lines) or "no actionable failure mode identified"

    def meta(self) -> dict:
        return {"variant": self.variant, "mode": self.mode, "stop": self.stop, "rounds": self.rounds,
                "confirmed": sorted(self.confirmed)}


# ---------------------------------------------------------------------------- helpers
def _plan_rollback(tb, service: str, keys: set[str], tokens: set[str], tried: set[int]):
    """Pick the version to roll back to: just before the newest deploy whose diff touches the settings
    the errors point at. Falls back to one step before the live version, or further if already tried."""
    header = tb.call("get_config", {"service": service}).splitlines()[0]
    m = re.search(r"versions: \[([\d, ]*)\]; live = v(-?\d+)", header)
    if not m:
        return None
    versions = [int(v) for v in m.group(1).split(",") if v.strip()]
    live = int(m.group(2))
    if live < 0:
        live = max(versions)
    best = None
    for v in sorted((v for v in versions if 1 < v <= live and v - 1 in versions), reverse=True):
        diff = tb.call("get_config", {"service": service, "version": v, "diff_against": v - 1})
        changed = [l[1:] for l in diff.splitlines()[1:] if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        hit_tok = [t for t in tokens if any(t in l for l in changed)]
        hit_key = [k for k in keys if any(re.search(rf"\b{re.escape(k)}\b", l, re.I) for l in changed)]
        if hit_tok or hit_key:
            best = (v, f"v{v} changed {'/'.join(hit_tok or hit_key)} (get_config diff), matching the errors")
            break
    candidates = [v for v in versions if v < live and v not in tried]
    if best and best[0] - 1 not in tried and best[0] - 1 < live:
        return best[0] - 1, best[0], best[1]
    if not candidates:
        return None
    target = max(candidates)
    return target, live, ""


def _remedy_id(h: Hypothesis) -> str:
    return h.key + json.dumps(h.remedy, sort_keys=True)


def _stray_processes(top: str) -> list[tuple[int, str, int]]:
    """Processes beside the service's main process (PID 1), grouped by command.
    Returns (pid to kill, command, count), largest group first; pid is the common parent when there is one."""
    procs = []
    for line in top.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+\S+\s+\S+\s+\d+\S*\s+\d+%\s+\d+\s+(\d+)%\s+(.+)$", line)
        if m:
            procs.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4).strip()))
    main = next((p[3] for p in procs if p[0] == 1), None)
    groups: dict[str, list] = {}
    for pid, ppid, cpu, cmd in procs:
        if pid == 1 or cmd == main or DIAG_NOISE.match(cmd):
            continue
        groups.setdefault(cmd, []).append((pid, ppid, cpu))
    out = []
    for cmd, ps in groups.items():
        # Kill the root of the job's process tree so its workers go with it.
        members = {pid for pid, _, _ in ps}
        roots = [(pid, ppid) for pid, ppid, _ in ps if ppid not in members]
        root_parents = {ppid for _, ppid in roots}
        if len(roots) == 1:
            pid = roots[0][0]
        elif len(root_parents) == 1 and min(root_parents) > 1:   # parent is idle and not in the listing
            pid = root_parents.pop()
        else:
            pid = max(ps, key=lambda p: p[2])[0]
        out.append((pid, cmd, len(ps), sum(c for *_, c in ps)))
    out.sort(key=lambda x: (-x[3], -x[2]))
    return [(pid, cmd, n) for pid, cmd, n, _ in out]


def _parse_services(text: str) -> dict:
    out = {}
    for line in text.splitlines()[1:]:
        c = line.split()
        if len(c) >= 6:
            out[c[0]] = {"state": c[1], "restarts": int(c[2]) if c[2].isdigit() else 0, "oom": c[3] == "True",
                         "missing": [] if c[-1] == "-" else c[-1].split(",")}
    return out


def _parse_endpoints(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = re.match(r"(\w+)\s+(\S+)\s+status=(\d+)\s+([\d.]+)ms\s+(OK|FAIL)\s*(.*)$", line)
        if m:
            out.append({"method": m.group(1), "path": m.group(2), "status": int(m.group(3)),
                        "ms": float(m.group(4)), "ok": m.group(5) == "OK", "detail": m.group(6)})
    return out


def _parse_changes(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*([\d.]+) min ago\s+(\S+)\s+v(\S+)\s+by (\S+)\s+(.*)$", line)
        if m:
            out.append({"age_min": float(m.group(1)), "service": m.group(2), "version": m.group(3),
                        "author": m.group(4), "summary": m.group(5).strip()})
    return list(reversed(out))  # oldest first


def _verify_summary(text: str) -> dict:
    try:
        v = json.loads(text)
        return {"healthy": v.get("healthy"), "problems": v.get("problems")}
    except json.JSONDecodeError:
        return {"healthy": False, "problems": [text[:200]]}


def _short(line: str, n: int = 140) -> str:
    return re.sub(r"\s+", " ", line).strip()[:n]
