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
    if name == "llm":
        from .llm import LLMAgent
        return LLMAgent(**kwargs)
    raise ValueError(f"unknown agent '{name}'; choose from noop, restart_all, rules, llm")


AGENTS = ["noop", "restart_all", "rules", "llm"]
