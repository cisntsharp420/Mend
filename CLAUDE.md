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
- `recovery/agents/` noop, restart_all, rules (dev-tuned runbook), reasoner (the main agent: offline,
  hypothesis-driven over logs/metrics/changes/diagnostics, recommends + applies fixes, ablation variants).
- `python -m recovery diagnose`: read-only recommended solution for the live system.
- `scenarios/dev.yaml` (10) and `scenarios/heldout.yaml` (12, never used for tuning).
- `recovery/harness.py` episode runner; `recovery/scoring.py`; `recovery/report.py`; CLI `python -m recovery`.

## Cloud container gotchas
- Run `scripts/bootstrap_cloud.sh` first (starts dockerd, pulls images from mirror.gcr.io because Docker Hub
  is rate-limited, downloads Alpine wheels because OS package mirrors are blocked).
- Kernel has no netem: no tc latency faults.
- NO API: owner decided the project must run without any LLM/API. Do not add model API calls.
- /data in api is tmpfs: an api restart (e.g. a config deploy) wipes it, so dev-09's disk fault self-heals.
- One sandbox per machine: run episodes serially. Don't `pkill -f` with patterns that match your own shell.

## Status / next steps
1. Done: sandbox, faults, verifier, toolbox, scenarios, baselines, reasoner agent (10/10 dev recovered), tests.
2. Running/next: reasoner dev + held-out x2, baselines on all, ablations (`make ablations`).
3. Then: docs/results.md via `python -m recovery report ...`, architecture diagram, pitch.
Never tune the reasoner on held-out results. Commit runs/ results as evidence. Never commit .env.
