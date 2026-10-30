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
- `recovery/agents/` noop, restart_all, rules (dev-tuned runbook), llm (Claude, ablation variants, record/replay),
  llm_openai (OpenAI Chat Completions backend reusing llm's prompt/variants/replay; `make llm-dev AGENT=llm_openai`).
- `scenarios/dev.yaml` (10) and `scenarios/heldout.yaml` (12, never used for tuning).
- `recovery/harness.py` episode runner; `recovery/scoring.py`; `recovery/report.py`; CLI `python -m recovery`.

## Cloud container gotchas
- Run `scripts/bootstrap_cloud.sh` first (starts dockerd, pulls images from mirror.gcr.io because Docker Hub
  is rate-limited, downloads Alpine wheels because OS package mirrors are blocked).
- Kernel has no netem: no tc latency faults.
- One sandbox per machine: run episodes serially. Don't `pkill -f` with patterns that match your own shell.

## Status / next steps
1. Done: sandbox, faults (all 12 validated break->fix), verifier, toolbox, scenarios, baselines, LLM agent code
   (Claude + OpenAI backends), 22 unit tests.
2. Done: baselines in `runs/baseline-{noop,restart_all,rules}` (~2.5h wall clock). Score / recovery rate, dev vs held-out:
   noop 10/0% vs 10/0%; restart_all 30/50% vs 10.3/17% (81 collateral actions); rules 99/100% vs 35.4/25%
   (diagF1 0.97 vs 0.35) -- the dev-tuned runbook overfits, which is the gap the LLM agent should close.
   One noop held-out episode (ho-11) had an unhealthy pre-fault baseline; harness now retries reset once.
3. Next: smoke-test LLM agent on 2-3 dev scenarios (needs ANTHROPIC_API_KEY, or OPENAI_API_KEY with
   --agent llm_openai; env vars only reach sessions started after they are added; OpenAI model via
   RECOVERY_OPENAI_MODEL, default gpt-5.5, and set RECOVERY_OPENAI_PRICES for cost), iterate the prompt on DEV ONLY.
4. Then: LLM dev + held-out x2, ablations, model comparison (sonnet/haiku 5.5; haiku gets no `fallbacks`).
5. Then: docs/results.md via `python -m recovery report ...`, README, architecture diagram, trace viewer, pitch.
Commit runs/ results as evidence. Never commit .env.
