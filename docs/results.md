| agent | run | split | episodes | recovery | diagnosis F1 | mean score | collateral actions | mean actions | median time-to-fix (s) | cost (USD) |
|---|---|---|---|---|---|---|---|---|---|---|
| noop | baseline-noop | dev | 10 | 0% | 0.00 | 10.0 | 0 | 0 | - | - |
| noop | baseline-noop | heldout | 12 | 0% | 0.00 | 10.0 | 0 | 0 | - | - |
| restart_all | baseline-restart_all | dev | 10 | 50% | 0.00 | 30.0 | 39 | 5 | 31.9 | - |
| restart_all | baseline-restart_all | heldout | 12 | 17% | 0.00 | 10.3 | 42 | 5 | 32.2 | - |
| rules | baseline-rules | dev | 10 | 100% | 0.97 | 99.0 | 0 | 1.1 | 12.4 | - |
| rules | baseline-rules | heldout | 12 | 25% | 0.35 | 35.4 | 0 | 0.6 | 19.7 | - |
| reasoner:full | reasoner-dev | dev | 10 | 100% | 0.97 | 99.0 | 0 | 1.1 | 23.3 | - |
| reasoner:full | reasoner-heldout | heldout | 24 | 96% | 0.97 | 96.6 | 0 | 1.5 | 33.1 | - |
| reasoner:full | reasoner-heldout-rerun | heldout | 5 | 100% | 0.96 | 98.8 | 0 | 1.4 | 35.3 | - |

Per-scenario outcome (✅ recovered, ❌ not recovered; number = diagnosis F1; repeats shown as recovered/total):

| scenario | noop | restart_all | rules | reasoner:full | reasoner:full | reasoner:full |
|---|---|---|---|---|---|---|
| dev-01-api-down | ❌ 0.00 | ✅ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-02-postgres-down | ❌ 0.00 | ✅ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-03-redis-down | ❌ 0.00 | ✅ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-04-db-password | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-05-gateway-upstream | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-06-disk-full | ❌ 0.00 | ✅ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-07-cpu-hog | ❌ 0.00 | ✅ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-08-postgres-partition | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| dev-09-multi-disk-password | ❌ 0.00 | ❌ 0.00 | ✅ 0.67 | ✅ 0.67 |  |  |
| dev-10-multi-redis-gateway | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 | ✅ 1.00 |  |  |
| ho-01-db-host-dns | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 |  | ✅ 1.00 (2/2) |  |
| ho-02-crashloop | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 |  | ✅ 1.00 (2/2) |  |
| ho-03-partial-tax-rate | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 |  | ✅ 1.00 (2/2) | ✅ 1.00 |
| ho-04-memory-leak | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 |  | ✅ 1.00 (2/2) | ✅ 1.00 |
| ho-05-db-lock | ❌ 0.00 | ✅ 0.00 | ❌ 0.00 |  | ✅ 1.00 (2/2) | ✅ 1.00 |
| ho-06-conn-exhaustion | ❌ 0.00 | ✅ 0.00 | ❌ 0.00 |  | ✅ 1.00 (2/2) |  |
| ho-07-redis-partition | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 |  | ✅ 1.00 (2/2) |  |
| ho-08-rollback-trap | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 |  | ✅ 1.00 (2/2) |  |
| ho-09-lock-behind-gateway | ❌ 0.00 | ❌ 0.00 | ❌ 0.67 |  | ⚠️ 0.83 (1/2) | ✅ 1.00 |
| ho-10-cpu-and-redis-partition | ❌ 0.00 | ❌ 0.00 | ✅ 1.00 |  | ✅ 1.00 (2/2) |  |
| ho-11-conn-leak-and-dns | ❌ 0.00 | ❌ 0.00 | ❌ 0.00 |  | ✅ 1.00 (2/2) |  |
| ho-12-triple | ❌ 0.00 | ❌ 0.00 | ❌ 0.50 |  | ✅ 0.80 (2/2) | ✅ 0.80 |
