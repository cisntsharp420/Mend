# Agentic Recovery of a Failing System

An agent that **identifies, diagnoses and recovers** a failing system by reading its **logs and metrics**,
and explains every fix as a **recommended solution** with the evidence behind it.
It runs fully offline: **no LLM, no API key, no network calls.**

Built for the HUMAIN hackathon, Challenge 1.

## What it does

```
page ──► observe ──► hypothesize ──► recommend ──► act ──► re-observe ──► confirmed? ──► verify ──► report
           ▲                                                    │ no: refute, try next fix
           └────────────────────────────────────────────────────┘
```

1. **Observe**: service states, synthetic endpoint checks, the logs of every service (only the window since
   the last action, so old errors never count against a fix), container and application metrics, the
   deployment change log, and targeted read-only diagnostics (disk, processes, DB locks and sessions, DNS).
2. **Hypothesize**: a library of failure-mode detectors turns that evidence into hypotheses
   (component, category, remedy). Each one cites the log lines and metrics it relies on, and its confidence
   is a noisy-OR of those signal weights, so every number can be traced back to evidence.
3. **Recommend**: hypotheses are ranked into a recommended solution: what to do, why, and how to prevent it.
4. **Act and re-check**: the most confident hypothesis is fixed with the least invasive remedy, then the system
   is observed again. A hypothesis is *confirmed* only when its own symptom is gone. A config rollback that
   does not clear the errors walks further back through the version history.
5. **Verify and report**: an independent soak test decides whether the system recovered (the agent's own
   opinion never counts), and only confirmed root causes are reported.

| Failure mode | Evidence it reads | Recommended fix |
|---|---|---|
| service down | container state, failing endpoints | start the container |
| network partition | missing network attachment, "Name does not resolve" in logs | re-attach the network |
| bad config deploy | error signatures in logs (auth failures, DNS, refused connections, config errors, crashes, OOM) + change log + config diff that touches the implicated setting | roll back to the version before the culprit deploy |
| disk full | `/data` usage, "No space left on device" | delete disposable temp files |
| CPU exhaustion | container CPU, endpoint latency, stray processes beside the main process | stop the runaway job (root of its process tree) |
| DB lock contention | blocked sessions and their root blocker, timeouts in logs | terminate the blocking session |
| DB connection exhaustion | connections vs `max_connections`, "too many clients", per-app session counts, matching process | stop the leaking job, then free its sessions |

## Quick start

```bash
make install          # or scripts/bootstrap_cloud.sh in a fresh cloud container
make up               # start the ShopStack sandbox (docker compose)
python -m recovery inject dev-04-db-password    # break it
python -m recovery diagnose                     # read-only: print the recommended solution
python -m recovery run --agent reasoner --scenarios dev-04   # diagnose + fix + verify + score
```

Example `diagnose` output (bad credentials deploy):

```
1. bad_config_deploy on api  (confidence 0.76)
     evidence: 18 log line(s) on api: the database rejected the client's credentials, e.g. ... password authentication failed for user "shop_app"
     evidence: v2 changed password (get_config diff), matching the errors
     evidence: api was deployed 0.3 min ago: v2 'rotate database credentials (SEC-4411)' by ci-bot
   RECOMMENDED: roll back the api config to v1 (undoing v2)
     -> rollback_config({"service": "api", "to_version": 1})
   PREVENT: validate configs in CI and canary deploys with automatic rollback on error-rate spikes
```

## How it is evaluated

- **Target system** (`sandbox/`): ShopStack, i.e. nginx gateway → Flask API → Postgres + Redis, plus a worker
  and a load generator.
- **12 fault types** (`recovery/faults.py`), each with an injector, ground truth and a residual check, plus
  red herrings (benign deploys, noisy warnings).
- **Scenarios**: `scenarios/dev.yaml` (10, used while building the agent) and `scenarios/heldout.yaml` (12,
  never looked at during development: unseen fault types, a rollback trap, masked and triple faults).
- **Independent verifier** (`recovery/verifier.py`): a soak test after the agent finishes.
- **Scoring** (`recovery/scoring.py`): 60 recovered + 30 diagnosis F1 + 10 safety (penalises actions on
  components that were not at fault).
- **Baselines**: `noop`, `restart_all`, and `rules` (a runbook hand-tuned on dev).
- **Ablations**: the reasoner with one evidence source switched off (`no_logs`, `no_metrics`,
  `no_diagnostics`, `no_changes`) or without the re-check loop (`single_pass`).

```bash
make test                         # offline unit tests (no docker)
make reasoner-dev reasoner-heldout baselines ablations
python -m recovery report reasoner-dev reasoner-heldout baseline-rules baseline-restart_all baseline-noop --out docs/results.md
```

Results: see [`docs/results.md`](docs/results.md). Every episode's full audit trail, evidence and per-round
recommendations are in `runs/<tag>/rep*/<scenario>.json`.

## Safety

The agent only acts through `recovery/tools.py`: 17 typed tools with guardrails (no killing PID 1, deletes
limited to `/data/tmp/`, exact-name DB session termination), an action budget, a time budget, an optional
human approver for risky actions (`--approve`), `--dry-run`, and a full audit log. Its action threshold
(confidence ≥ 0.5) means weak evidence produces a recommendation, never a change.
