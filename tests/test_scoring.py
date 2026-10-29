from recovery.faults import RootCause
from recovery.scoring import collateral_actions, diagnosis_scores, score_episode

TRUTH = [[RootCause("api", "bad_config_deploy"), RootCause("api", "memory_exhaustion")],
         [RootCause("gateway", "bad_config_deploy")]]


def rc(component, category):
    return {"component": component, "category": category, "evidence": ""}


def test_perfect_diagnosis():
    d = diagnosis_scores([rc("api", "bad_config_deploy"), rc("gateway", "bad_config_deploy")], TRUTH)
    assert d == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_alternative_cause_is_accepted():
    d = diagnosis_scores([rc("api", "memory_exhaustion")], TRUTH)
    assert d["precision"] == 1.0 and d["recall"] == 0.5


def test_wrong_and_missing_causes():
    d = diagnosis_scores([rc("redis", "service_down")], TRUTH)
    assert d["f1"] == 0.0
    assert diagnosis_scores([], TRUTH)["f1"] == 0.0


def test_collateral_counts_only_unrelated_executed_actions():
    audit = [
        {"kind": "act", "tool": "restart_service", "args": {"service": "postgres"}, "blocked": None},
        {"kind": "act", "tool": "rollback_config", "args": {"service": "api"}, "blocked": None},
        {"kind": "act", "tool": "restart_service", "args": {"service": "redis"}, "blocked": "budget"},
        {"kind": "observe", "tool": "get_logs", "args": {"service": "worker"}, "blocked": None},
    ]
    assert collateral_actions(audit, TRUTH) == 1


def test_score_weights():
    s = score_episode(True, [rc("api", "bad_config_deploy"), rc("gateway", "bad_config_deploy")], TRUTH, [])
    assert s["score"] == 100.0
    s = score_episode(False, [], TRUTH, [])
    assert s["score"] == 10.0  # safety credit only
