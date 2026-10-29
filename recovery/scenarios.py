"""Scenario definitions loaded from scenarios/*.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .faults import FAULTS, NOISE, Fault, RootCause

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"


@dataclass
class Scenario:
    id: str
    split: str
    faults: list[Fault]
    noise: list[str] = field(default_factory=list)
    noise_after: bool = False

    def truth(self) -> list[list[RootCause]]:
        """One entry per fault: [canonical cause, *accepted alternatives]."""
        return [f.truth() for f in self.faults]


def load_split(split: str) -> list[Scenario]:
    data = yaml.safe_load((SCENARIO_DIR / f"{split}.yaml").read_text())
    out = []
    for d in data:
        faults = [Fault(f["kind"], f.get("target")) for f in d["faults"]]
        for f in faults:
            if f.kind not in FAULTS:
                raise ValueError(f"{d['id']}: unknown fault kind {f.kind}")
        for n in d.get("noise", []):
            if n not in NOISE:
                raise ValueError(f"{d['id']}: unknown noise {n}")
        out.append(Scenario(d["id"], split, faults, d.get("noise", []), d.get("noise_after", False)))
    return out


def load(selector: str) -> list[Scenario]:
    """'dev', 'heldout', 'all', or a comma-separated list of scenario ids (prefixes allowed)."""
    everything = load_split("dev") + load_split("heldout")
    if selector in ("dev", "heldout"):
        return load_split(selector)
    if selector == "all":
        return everything
    wanted = selector.split(",")
    picked = [s for s in everything if any(s.id == w or s.id.startswith(w) for w in wanted)]
    if not picked:
        raise ValueError(f"no scenarios match {selector!r}")
    return picked
