# Pitch: Agentic Recovery (5 minutes)

## 1. The problem (30 s)
When production breaks at 3 a.m., someone has to find out *what* broke, *why*, and fix it
without making it worse. People want AI agents to do this. But how do you know an agent
actually fixed the system, and didn't just restart things until the dashboard turned green?

## 2. What I built (60 s)
A benchmark that answers that question honestly.
- **ShopStack**: a real 5-service shop (nginx, Flask API, Postgres, Redis, worker) under load.
- **12 realistic faults**: bad config deploys, DNS errors, crash loops, memory leaks, disk full,
  runaway CPU, DB locks, connection leaks, network partitions, plus red herrings.
- **A guarded toolbox** of 17 tools. It is the only way any agent can touch the system: budgets,
  guardrails, human approval for risky actions, and a full audit trail.
- **An independent verifier**: the agent's opinion never counts. Real user traffic must succeed
  over a soak window, and a residual check must prove the root cause is gone, not masked.

## 3. Live demo (90 s)
```bash
python -m recovery inject dev-04-db-password   # a bad config deploy breaks the API
python -m recovery status                       # 503 database errors: orders fail, cached products still load
python -m recovery run --agent rules --scenarios dev-04 --tag demo
```
Point out: the agent reads the change log, sees the bad deploy, rolls back exactly that change,
names the root cause, and the verifier confirms recovery: one action, zero collateral, ~20 s.

## 4. The finding (60 s)
Show the results table from the README.
- **Restarting everything** fixes half the easy faults and scores no better than doing nothing on
  unseen ones, while touching 42 services that were never broken.
- **A hand-written runbook** scores 99/100 on the faults it was written for and **35** on unseen
  ones.
- The benchmark exposes exactly the gap that matters: **generalizing to failures you haven't
  seen before**. That gap is what an LLM agent is for.

## 5. What's next (30 s)
- The Claude agent is built: same toolbox, adaptive thinking, every decision recorded and
  replayable, and ablations to measure what each capability contributes. Running it is one command.
- The held-out split was never used for tuning, so whatever it scores will be an honest number.

## Likely questions
- **Why not just use the LLM's own "fixed it" claim?** Agents over-claim. Only the verifier's
  soak + residual checks count.
- **How do you prevent overfitting?** A dev/held-out split. The rules agent's 99 → 35 drop is the
  proof that the split works.
- **Is it safe to let an agent act on production?** Every action goes through the guardrails,
  budgets and audit log, and `--approve` puts a human in the loop for risky actions.
- **Why is there no LLM number?** There was no API access during the build. The agent code and
  its replay tests are in `recovery/agents/llm.py` and `tests/test_llm_agent.py`.
