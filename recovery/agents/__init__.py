"""Agent registry. The LLM agent is imported lazily so baselines run without an API key."""


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
    if name == "llm":
        from .llm import LLMAgent
        return LLMAgent(**kwargs)
    raise ValueError(f"unknown agent '{name}'; choose from {', '.join(AGENTS)}")


AGENTS = ["noop", "restart_all", "rules", "reasoner", "llm"]

# Names shown to people (reports, web app). Internal ids above stay the same everywhere else.
DISPLAY_NAMES = {"noop": "Idle Agent", "restart_all": "Restart Agent", "rules": "Runbook Agent",
                 "reasoner": "Reasoning Agent", "llm": "Mend AI"}
DESCRIPTIONS = {"noop": "does nothing; the floor every agent must beat",
                "restart_all": "restarts every service, the classic first reflex",
                "rules": "a hand-written runbook built from the dev incidents",
                "reasoner": "forms hypotheses from logs, metrics and diagnostics, fixes the most likely cause, re-checks; "
                            "designed knowing all 12 fault types, never tuned on held-out runs",
                "llm": "Claude, reasoning over the same toolbox"}


def display_name(agent: str) -> str:
    return DISPLAY_NAMES.get(agent, agent)
