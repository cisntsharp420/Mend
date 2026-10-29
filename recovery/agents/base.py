"""Agent interface: an agent gets a toolbox and an alert, and must end with submit_report."""
from __future__ import annotations

from ..tools import Toolbox


class Agent:
    name = "base"

    def run(self, tb: Toolbox, alert: str) -> None:
        raise NotImplementedError

    def meta(self) -> dict:
        return {}
