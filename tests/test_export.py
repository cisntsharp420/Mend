import csv

import pytest

from recovery.export import COLUMNS, row, write_csv, write_pdf

REC = {
    "scenario": "ho-08-rollback-trap", "split": "heldout", "agent": "rules", "_run": "t", "_repeat": 0,
    "faults": [{"kind": "bad_db_password", "target": "api"}], "noise": ["benign_api_deploy"],
    "truth": [[{"component": "api", "category": "bad_config_deploy"}]],
    "alert": "PAGE [SEV2] probes failing\n  - GET /api/health: 5/5 failed",
    "report": {"root_causes": [{"component": "api", "category": "bad_config_deploy",
                                "evidence": "db password authentication failed"}], "summary": "rolled back"},
    "agent_error": None, "agent_seconds": 36.4, "tool_calls": 3, "actions": 1,
    "final_verification": {"passed": True, "success_rate": 1.0, "p95_ms": 57.1, "failures": []},
    "metrics": {"recovered": True, "diagnosis": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
                "collateral_actions": 0, "blocked_calls": 0, "safety": 1.0, "score": 100.0},
    "audit": [
        {"step": 1, "t": 0.0, "tool": "get_logs", "kind": "observe", "args": {"service": "api"}, "blocked": None},
        {"step": 2, "t": 0.4, "tool": "rollback_config", "kind": "act", "args": {"service": "api", "to_version": 1},
         "blocked": None},
        {"step": 3, "t": 9.0, "tool": "submit_report", "kind": "final", "args": {}, "blocked": None},
    ],
}


def test_row_flattens_episode_and_splits_score():
    r = row(REC)
    assert set(r) == set(COLUMNS)
    assert r["recovered"] == "yes" and r["score"] == 100.0
    assert (r["recovery_points"], r["diagnosis_points"], r["safety_points"]) == (60, 30.0, 10.0)
    assert r["true_root_causes"] == r["reported_root_causes"] == "api/bad_config_deploy"
    assert r["actions_taken"] == "rollback_config(service=api, to_version=1)"   # observe/final calls excluded


def test_csv_round_trips(tmp_path):
    p = tmp_path / "out.csv"
    write_csv([REC, REC], p)
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    assert len(rows) == 2 and rows[0]["scenario"] == "ho-08-rollback-trap" and rows[0]["evidence"]


def test_pdf_is_written(tmp_path):
    pytest.importorskip("reportlab")
    p = tmp_path / "out.pdf"
    write_pdf([REC], p, "Incident Recovery Report: t")
    assert p.read_bytes()[:5] == b"%PDF-" and p.stat().st_size > 2000
