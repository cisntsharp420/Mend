"""The reasoner offline: parsers, detectors and the act/re-check loop on recorded tool outputs (no docker)."""
from recovery.agents.reasoner import (Evidence, ReasonerAgent, _Context, _plan_rollback, _stray_processes,
                                      detect_bad_config, detect_cpu, detect_partition, detect_stopped)

SERVICES_OK = """service   state       restarts  oom    health   networks             missing_networks
gateway   running     0         False  -        frontend             -
api       running     0         False  -        backend,frontend     -
worker    running     0         False  -        backend              -
postgres  running     0         False  healthy  backend              -
redis     running     0         False  -        backend              -"""
ENDPOINTS_OK = """GET  /healthz             status=200     1.2ms OK
GET  /api/health          status=200    12.2ms OK
GET  /api/products        status=200     3.5ms OK"""
ENDPOINTS_DB = """GET  /healthz             status=200     1.2ms OK
GET  /api/health          status=503    12.2ms FAIL {"checks":{"cache":"ok","database":"error: connection failed"}}
GET  /api/orders/recent   status=503    11.8ms FAIL {"error":"database error"}"""
AUTH_LOG = """2 lines in last 60s.
Top message patterns:
--- last 2 lines ---
2026-10-30T02:36:05 ERROR api db query failed (recent orders): connection failed: FATAL:  password authentication failed for user "shop_app"
2026-10-30T02:36:06 ERROR api POST /api/orders -> 503 (10ms)"""
EMPTY_LOG = "0 lines in last 60s.\nTop message patterns:\n--- last 0 lines ---\n"
TOP_CPU_HOG = """  PID  PPID USER     STAT   VSZ %VSZ CPU %CPU COMMAND
   33    23 root     R    14772   0%   0   3% python /app/tools/reindex_search.py
   36    23 root     R    14772   0%   3   3% python /app/tools/reindex_search.py
    1     0 root     R    74720   0%   2   0% python app.py
   45     0 root     S     1652   0%   0   0% sh -c top -b -n 1 | head -25
   51    45 root     R     1648   0%   3   0% top -b -n 1"""
DIFF_PASSWORD = """api config versions: [1, 2, 3]; live = v3
--- v1
+++ v2
-  password: shop-secret
+  password: shop-s3cret-2026"""
DIFF_TTL = """api config versions: [1, 2, 3]; live = v3
--- v2
+++ v3
-  ttl_s: 30
+  ttl_s: 45"""


class FakeTB:
    """Answers tool calls from a dict; records every call."""

    def __init__(self, answers: dict):
        self.answers, self.calls = answers, []

    def call(self, name, args=None):
        args = args or {}
        self.calls.append((name, args))
        for key in (f"{name} {sorted(args.items())}", f"{name} {args.get('service', '')}", name):
            if key in self.answers:
                v = self.answers[key]
                return v(args) if callable(v) else v
        return ""


def evidence(**over):
    answers = {"list_services": SERVICES_OK, "check_endpoints": ENDPOINTS_OK, "get_recent_changes": "",
               "get_metrics": '{"containers": {}}', "get_logs": EMPTY_LOG}
    answers.update(over)
    tb = FakeTB(answers)
    return Evidence(tb, 60, set()), tb


def test_stray_processes_groups_children_under_their_parent():
    # parent idle and not listed: kill the common parent
    assert _stray_processes(TOP_CPU_HOG) == [(23, "python /app/tools/reindex_search.py", 2)]
    # parent listed with the same command (multiprocessing): kill the root of the tree, not a worker
    with_parent = TOP_CPU_HOG + "\n   23     0 root     S    14772   0%   1   0% python /app/tools/reindex_search.py"
    assert _stray_processes(with_parent) == [(23, "python /app/tools/reindex_search.py", 3)]


def test_stopped_service_and_partition_are_detected():
    ev, _ = evidence(list_services=SERVICES_OK.replace("api       running", "api       exited ")
                     .replace("postgres  running     0         False  healthy  backend              -",
                              "postgres  running     0         False  healthy  -                    backend"))
    stopped = detect_stopped(ev, _Context())
    assert [(h.component, h.category, h.remedy) for h in stopped] == \
        [("api", "service_down", [("start_service", {"service": "api"})])]
    part = detect_partition(ev, _Context())
    assert part[0].remedy == [("reconnect_network", {"service": "postgres", "network": "backend"})]


def test_rollback_skips_benign_newer_deploy():
    """Errors point at the password; v3 only touched a TTL, so roll back past v2 (the culprit) to v1."""
    tb = FakeTB({"get_config [('service', 'api')]": DIFF_PASSWORD.splitlines()[0],
                 "get_config [('diff_against', 2), ('service', 'api'), ('version', 3)]": DIFF_TTL,
                 "get_config [('diff_against', 1), ('service', 'api'), ('version', 2)]": DIFF_PASSWORD})
    target, culprit, why = _plan_rollback(tb, "api", {"password", "user"}, set(), set())
    assert (target, culprit) == (1, 2) and "password" in why


def test_rollback_walks_further_back_when_a_target_was_tried():
    tb = FakeTB({"get_config [('service', 'api')]": "api config versions: [1, 2, 3]; live = v2"})
    assert _plan_rollback(tb, "api", set(), set(), tried={2})[0] == 1


def test_bad_config_needs_errors_not_just_a_deploy():
    changes = "  0.3 min ago  api      v2  by dev-ahmed          tune cache TTL"
    cfg = {"get_config [('service', 'api')]": "api config versions: [1, 2]; live = v2"}
    quiet, _ = evidence(get_recent_changes=changes, **cfg)
    assert detect_bad_config(quiet, _Context()) == []          # a benign deploy alone is not a cause
    noisy, _ = evidence(get_recent_changes=changes, check_endpoints=ENDPOINTS_DB,
                        **{"get_logs api": AUTH_LOG}, **cfg)
    (h,) = detect_bad_config(noisy, _Context())
    assert (h.component, h.category, h.confidence >= 0.5) == ("api", "bad_config_deploy", True)


def test_cpu_hog_is_killed_by_parent_pid():
    ev, _ = evidence(get_metrics='{"containers": {"api": {"cpu_pct": "52.25%"}}}',
                     **{"run_diagnostic [('check', 'processes'), ('service', 'api')]": TOP_CPU_HOG})
    (h,) = detect_cpu(ev, _Context())
    assert h.remedy == [("kill_process", {"service": "api", "pid": 23})] and h.confidence >= 0.5


def test_loop_acts_rechecks_confirms_and_reports():
    state = {"api": "exited "}
    services = lambda a: SERVICES_OK.replace("api       running", f"api       {state['api']}")

    def start(a):
        state["api"] = "running"
        return "started api: ok"

    tb = FakeTB({"list_services": services, "check_endpoints": lambda a: ENDPOINTS_OK if state["api"] == "running"
                 else ENDPOINTS_DB, "get_logs": EMPTY_LOG, "get_metrics": '{"containers": {}}',
                 "start_service": start, "verify_recovery": '{"healthy": true, "problems": []}',
                 "submit_report": lambda a: tb.__dict__.setdefault("report", a) and "ok"})
    agent = ReasonerAgent()
    import recovery.agents.reasoner as r
    r.time.sleep, orig = (lambda s: None), r.time.sleep
    try:
        agent.run(tb, "PAGE")
    finally:
        r.time.sleep = orig
    assert ("start_service", {"service": "api"}) in tb.calls
    assert tb.report["recovered"] is True
    assert tb.report["root_causes"][0]["component"] == "api"
    assert agent.stop == "recovered" and "confirmed" in tb.report["summary"]


def test_recommend_mode_changes_nothing():
    tb = FakeTB({"list_services": SERVICES_OK.replace("api       running", "api       exited "),
                 "check_endpoints": ENDPOINTS_DB, "get_logs": EMPTY_LOG, "get_metrics": '{"containers": {}}',
                 "submit_report": lambda a: tb.__dict__.setdefault("report", a) and "ok"})
    ReasonerAgent(mode="recommend").run(tb, "PAGE")
    assert not [c for c in tb.calls if c[0] in ("start_service", "rollback_config", "kill_process")]
    assert tb.report["recovered"] is False and "RECOMMENDATION ONLY" in tb.report["summary"]
    assert tb.report["root_causes"][0]["category"] == "service_down"
