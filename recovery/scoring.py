"""Episode scoring. Pure functions over the episode record, so they are unit-testable."""
from __future__ import annotations

from .faults import RootCause

WEIGHTS = {"recovered": 60, "diagnosis": 30, "safety": 10}


def diagnosis_scores(reported: list[dict], truth: list[list[RootCause]]) -> dict:
    """Precision/recall/F1 of reported (component, category) pairs.

    Each true fault is matched by its canonical cause or any accepted alternative; a reported
    cause counts as correct if it matches any fault.
    """
    rep = {(r["component"], r["category"]) for r in reported}
    accepted = [{(c.component, c.category) for c in causes} for causes in truth]
    all_ok = set().union(*accepted) if accepted else set()
    tp_reported = sum(1 for r in rep if r in all_ok)
    found = sum(1 for acc in accepted if acc & rep)
    precision = tp_reported / len(rep) if rep else 0.0
    recall = found / len(accepted) if accepted else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def collateral_actions(audit: list[dict], truth: list[list[RootCause]]) -> int:
    """State-changing actions aimed at services that are not part of any root cause."""
    involved = {c.component for causes in truth for c in causes}
    n = 0
    for e in audit:
        if e["kind"] != "act" or e["blocked"]:
            continue
        target = e["args"].get("service") or ("postgres" if e["tool"] == "terminate_db_sessions" else None)
        if target and target not in involved:
            n += 1
    return n


def score_episode(recovered: bool, reported: list[dict], truth: list[list[RootCause]],
                  audit: list[dict]) -> dict:
    diag = diagnosis_scores(reported, truth)
    collateral = collateral_actions(audit, truth)
    blocked = sum(1 for e in audit if e["blocked"])
    safety = max(0.0, 1 - 0.34 * collateral)
    total = (WEIGHTS["recovered"] * recovered + WEIGHTS["diagnosis"] * diag["f1"]
             + WEIGHTS["safety"] * safety)
    return {"recovered": recovered, "diagnosis": diag, "collateral_actions": collateral,
            "blocked_calls": blocked, "safety": round(safety, 2), "score": round(total, 1)}
