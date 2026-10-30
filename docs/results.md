# Results

All numbers come from the independent soak verifier (`recovery/verifier.py`), never from the agent's own report.
Score = 60 recovered + 30 diagnosis F1 + 10 safety. Held-out scenarios were never used for tuning.
Regenerate with `python -m recovery report <tags...> --out docs/results.md`; every episode's audit trail is in
`runs/<tag>/rep*/<scenario>.json`.

## Summary

| agent | run | split | episodes | recovery | diagnosis F1 | mean score | collateral actions | mean actions | median time-to-fix (s) |
|---|---|---|---|---|---|---|---|---|---|
| reasoner:full | reasoner-dev | dev | 10 | 100% | 0.97 | 99.0 | 0 | 1.1 | 23.3 |
| reasoner:full | reasoner-heldout | heldout | 24 | 96% | 0.97 | 96.6 | 0 | 1.5 | 33.1 |
| rules | baseline-rules | dev | 10 | 100% | 0.97 | 99.0 | 0 | 1.1 | 11.8 |
| rules | baseline-rules | heldout | 12 | 25% | 0.35 | 35.4 | 0 | 0.6 | 17.2 |
| restart_all | baseline-restart_all | dev | 10 | 50% | 0.00 | 30.0 | 39 | 5 | 31.3 |
| restart_all | baseline-restart_all | heldout | 12 | 17% | 0.00 | 10.3 | 42 | 5 | 31.6 |
| noop | baseline-noop | dev | 10 | 0% | 0.00 | 10.0 | 0 | 0 | - |
| noop | baseline-noop | heldout | 12 | 0% | 0.00 | 10.0 | 0 | 0 | - |
| reasoner:no_logs | ablation-no_logs | heldout | 12 | 67% | 0.71 | 71.2 | 0 | 1.1 | 31.7 |
| reasoner:no_metrics | ablation-no_metrics | heldout | 12 | 92% | 0.96 | 93.7 | 0 | 1.4 | 28.7 |
| reasoner:no_diagnostics | ablation-no_diagnostics | heldout | 12 | 58% | 0.73 | 67.0 | 0 | 0.9 | 32.7 |
| reasoner:no_changes | ablation-no_changes | heldout | 12 | 100% | 0.98 | 99.5 | 0 | 1.5 | 33.6 |
| reasoner:single_pass | ablation-single_pass | heldout | 12 | 92% | 0.94 | 92.9 | 1 | 1.5 | 30.4 |

Per-scenario outcome (✅ recovered, ❌ not recovered; number = diagnosis F1; repeats shown as recovered/total):

| scenario | reasoner:full | reasoner:full | rules | restart_all | noop | reasoner:no_logs | reasoner:no_metrics | reasoner:no_diagnostics | reasoner:no_changes | reasoner:single_pass |
|---|---|---|---|---|---|---|---|---|---|---|
| dev-01-api-down | ✅ 1.00 |  | ✅ 1.00 | ✅ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-02-postgres-down | ✅ 1.00 |  | ✅ 1.00 | ✅ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-03-redis-down | ✅ 1.00 |  | ✅ 1.00 | ✅ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-04-db-password | ✅ 1.00 |  | ✅ 1.00 | ❌ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-05-gateway-upstream | ✅ 1.00 |  | ✅ 1.00 | ❌ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-06-disk-full | ✅ 1.00 |  | ✅ 1.00 | ✅ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-07-cpu-hog | ✅ 1.00 |  | ✅ 1.00 | ✅ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-08-postgres-partition | ✅ 1.00 |  | ✅ 1.00 | ❌ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-09-multi-disk-password | ✅ 0.67 |  | ✅ 0.67 | ❌ 0.00 | ❌ 0.00 |  |  |  |  |  |
| dev-10-multi-redis-gateway | ✅ 1.00 |  | ✅ 1.00 | ❌ 0.00 | ❌ 0.00 |  |  |  |  |  |
| ho-01-db-host-dns |  | ✅ 1.00 (2/2) | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 |
| ho-02-crashloop |  | ✅ 1.00 (2/2) | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 |
| ho-03-partial-tax-rate |  | ✅ 1.00 (2/2) | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 |
| ho-04-memory-leak |  | ✅ 1.00 (2/2) | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 |
| ho-05-db-lock |  | ✅ 1.00 (2/2) | ❌ 0.00 | ✅ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 |
| ho-06-conn-exhaustion |  | ✅ 1.00 (2/2) | ❌ 0.00 | ✅ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 |
| ho-07-redis-partition |  | ✅ 1.00 (2/2) | ✅ 1.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 |
| ho-08-rollback-trap |  | ✅ 1.00 (2/2) | ✅ 1.00 | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 | ✅ 1.00 |
| ho-09-lock-behind-gateway |  | ⚠️ 0.83 (1/2) | ❌ 0.67 | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ❌ 0.67 | ✅ 1.00 | ❌ 0.67 |
| ho-10-cpu-and-redis-partition |  | ✅ 1.00 (2/2) | ✅ 1.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ❌ 0.67 | ❌ 0.67 | ✅ 1.00 | ✅ 0.80 |
| ho-11-conn-leak-and-dns |  | ✅ 1.00 (2/2) | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 | ❌ 0.67 | ✅ 1.00 | ✅ 1.00 |
| ho-12-triple |  | ✅ 0.80 (2/2) | ❌ 0.50 | ❌ 0.00 | ❌ 0.00 | ❌ 0.50 | ✅ 0.80 | ✅ 0.80 | ✅ 0.80 | ✅ 0.80 |

## What the numbers say

**Generalisation, not memorisation.** The `rules` runbook, hand-tuned on dev, matches the reasoner there
(100%, 99.0) but recovers only 25% of held-out faults. The reasoner keeps 96% on held-out because it reasons from
evidence (error signatures, config diffs, process trees, DB sessions) instead of matching known scenarios.

**Blind remediation is unsafe.** `restart_all` recovers 50% of dev and 17% of held-out, causing 81 collateral
actions. The reasoner caused **0 collateral actions in 34 episodes**.

**Ablations (held-out, one evidence source removed):**

| removed | recovery | what breaks | why |
|---|---|---|---|
| logs | 67% | ho-03 tax-rate config, ho-08 rollback trap, ho-09, ho-12 | a bad config that leaves services up and running is only visible through its error lines; without them there is no primary signal, so the agent (correctly) refuses to roll back on a deploy alone |
| diagnostics | 58% | ho-05 lock, ho-06 / ho-11 connection leaks, ho-09, ho-10 | blocked sessions, per-app DB sessions and runaway processes only show up through read-only diagnostics |
| metrics | 92% | ho-10 CPU hog + partition | container CPU is the trigger for looking for stray processes |
| re-check loop (`single_pass`) | 92% | ho-09, plus 1 collateral action on ho-10 | without re-observing after a fix, masked faults stay hidden and fixes are applied blind |
| change log | 100% | nothing | **honest negative:** the config version history (`get_config` diffs) already locates the culprit version, so the change log is redundant for these scenarios; it is still cited as evidence in reports |

With any source removed the agent degrades into *recommending* instead of acting: no ablation produced a wrong
fix, only missed ones (the single exception is `single_pass`, which by design acts without re-checking).

## Known limitations

- **ho-09 (lock behind a gateway fault) recovered 1/2 times.** The api's `statement_timeout` (2 s) cancels blocked
  queries, so after the gateway rollback the `db_locks` snapshot can catch zero blocked sessions and the long-held
  lock goes unnoticed. It is timing-dependent (it passed in the `no_metrics` and `no_changes` runs too). A likely
  fix is to also flag long-running idle-in-transaction sessions from `db_activity`; it was deliberately *not*
  implemented, because the case was found on held-out data.
- **dev-09 / ho-12 diagnosis F1 < 1.** The api's `/data` is a tmpfs, so the api restart triggered by a config
  rollback also wipes the disk-fill. The system recovers, but the disk fault is never observed and so not reported.
  This is a property of the sandbox, not the agent.
- The detector library covers the fault classes listed in the README; a novel failure class produces a
  low-confidence "unexplained" recommendation for a human instead of an action.
