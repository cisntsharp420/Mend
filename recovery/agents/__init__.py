"""Agent registry. Every agent runs offline: no model API, no key."""


def make_agent(name: str, **kwargs):
    if name == "noop":
        from .simple import NoopAgent
        return NoopAgent()
    if name == "restart_all":
        from .simple import RestartAllAgent
        return RestartAllAgent()
    if name == "rules":
        from .rules import RuleBasedAgent
        return RuleBasedAgent()
    if name == "reasoner":
        from .reasoner import ReasonerAgent
        return ReasonerAgent(**kwargs)
    raise ValueError(f"unknown agent '{name}'; choose from {', '.join(AGENTS)}")


AGENTS = ["noop", "restart_all", "rules", "reasoner"]
