from recovery.faults import CATEGORIES, FAULTS
from recovery.scenarios import load


def test_splits_are_disjoint_and_valid():
    dev, held = load("dev"), load("heldout")
    assert {s.id for s in dev}.isdisjoint({s.id for s in held})
    for s in dev + held:
        for causes in s.truth():
            assert all(c.category in CATEGORIES for c in causes)


def test_heldout_contains_unseen_fault_kinds():
    dev_kinds = {f.kind for s in load("dev") for f in s.faults}
    held_kinds = {f.kind for s in load("heldout") for f in s.faults}
    assert held_kinds - dev_kinds, "held-out must test generalization to unseen failure types"
    assert dev_kinds | held_kinds == set(FAULTS), "every fault type is exercised"
