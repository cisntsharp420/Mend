# Agentic Recovery — project notes for Claude sessions

HUMAIN hackathon, Challenge 1 ("Agentic Recovery of a Failing System"). Owner: Naif (solo, 2 days).
Judging: task performance on held-out cases, robustness, evaluation & iteration (systematic testing,
regression, ablations), technical judgment, engineering quality, communication.

## Layout
- `sandbox/` ShopStack target system (docker compose): gateway(nginx) -> api(Flask) -> postgres/redis, worker, loadgen.
- `recovery/sandbox.py` docker control plane, config versions + change log (`sandbox/.runtime/`).
- `recovery/faults.py` 12 fault types (inject, ground truth, residual check) + noise/red herrings.
- `recovery/verifier.py` independent soak verifier (the agent's opinion never counts).
- `recovery/tools.py` the only interface agents use: 17 tools, guardrails, budgets, audit trail.
- `recovery/agents/` noop, restart_all, rules (dev-tuned runbook), llm (Claude, ablation variants, record/replay).
- `scenarios/dev.yaml` (10) and `scenarios/heldout.yaml` (12, never used for tuning).
- `recovery/harness.py` episode runner; `recovery/scoring.py`; `recovery/report.py`; CLI `python -m recovery`.

## Cloud container gotchas
- Run `scripts/bootstrap_cloud.sh` first (starts dockerd, pulls images from mirror.gcr.io because Docker Hub
  is rate-limited, downloads Alpine wheels because OS package mirrors are blocked).
- Kernel has no netem: no tc latency faults.
- One sandbox per machine: run episodes serially. Don't `pkill -f` with patterns that match your own shell.

## Status / next steps
1. Done: sandbox, faults (all 12 validated break->fix), verifier, toolbox, scenarios, baselines, LLM agent code, 18 unit tests.
2. Done: baselines on all 22 (`make baselines`, ~2h, 66 valid episodes): rules 99.0 dev / 35.4 held-out,
   restart_all 30.0 / 10.3, noop 10.0 / 10.0. docs/results.md, README with architecture diagram.
3. Owner decision: submit WITHOUT an API key. LLM agent is implemented + unit-tested but not evaluated;
   README says so. Do not spend API credit or claim LLM results unless the owner changes this.
4. Remaining (no key needed): pitch/demo script, optional trace viewer over runs/ episode records.
Commit runs/ results as evidence. Never commit .env.
