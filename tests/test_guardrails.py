from unittest.mock import MagicMock

from recovery.tools import Policy, Toolbox


def make_tb(**policy):
    sb = MagicMock()
    sb.exec.return_value = MagicMock(ok=True, out="ok", rc=0)
    sb.compose.return_value = MagicMock(ok=True, out="", rc=0)
    return Toolbox(sb, Policy(**policy)), sb


def test_delete_outside_tmp_is_blocked():
    tb, sb = make_tb()
    for path in ["/data/audit/audit.log", "/data/tmp/../audit/audit.log", "/data/tmp/*", "/etc/passwd"]:
        assert tb.call("delete_file", {"service": "api", "path": path}).startswith("BLOCKED")
    sb.exec.assert_not_called()
    assert tb.call("delete_file", {"service": "api", "path": "/data/tmp/x.tmp"}) == "ok"


def test_pid1_and_unknown_service_blocked():
    tb, _ = make_tb()
    assert tb.call("kill_process", {"service": "api", "pid": 1}).startswith("BLOCKED")
    assert tb.call("restart_service", {"service": "loadgen"}).startswith("BLOCKED")
    assert tb.call("no_such_tool").startswith("BLOCKED")


def test_sql_injection_in_application_name_blocked():
    tb, sb = make_tb()
    out = tb.call("terminate_db_sessions", {"application_name": "x' OR '1'='1"})
    assert out.startswith("BLOCKED")
    sb.psql.assert_not_called()


def test_action_budget_enforced():
    tb, _ = make_tb(max_actions=2)
    for _ in range(2):
        assert not tb.call("start_service", {"service": "api"}).startswith("BLOCKED")
    assert "budget" in tb.call("start_service", {"service": "api"})
    assert tb.actions_used == 2


def test_risky_action_needs_approval():
    denied = []
    tb, sb = make_tb(approver=lambda name, args: denied.append(name) or False)
    assert "denied" in tb.call("stop_service", {"service": "postgres"})
    assert denied == ["stop_service"]
    sb.compose.assert_not_called()
    assert not tb.call("restart_service", {"service": "api"}).startswith("BLOCKED")  # not risky


def test_dry_run_executes_nothing():
    tb, sb = make_tb(dry_run=True)
    assert tb.call("restart_service", {"service": "api"}).startswith("[dry-run]")
    sb.compose.assert_not_called()


def test_report_validates_taxonomy_and_audit_records_everything():
    tb, _ = make_tb()
    bad = tb.call("submit_report", {"root_causes": [{"component": "api", "category": "gremlins"}],
                                    "summary": "", "recovered": True})
    assert bad.startswith("BLOCKED") and not tb.finished
    tb.call("submit_report", {"root_causes": [{"component": "api", "category": "disk_full", "evidence": "df"}],
                              "summary": "cleared tmp", "recovered": True})
    assert tb.finished and tb.report["root_causes"][0]["category"] == "disk_full"
    assert [e.tool for e in tb.audit] == ["submit_report", "submit_report"]


def test_tool_schemas_are_well_formed():
    tb, _ = make_tb()
    for s in tb.schemas():
        assert s["input_schema"]["type"] == "object"
        assert set(s["input_schema"]["required"]) <= set(s["input_schema"]["properties"])
