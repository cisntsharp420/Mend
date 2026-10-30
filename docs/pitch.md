# Pitch: Mend (5 minutes)

**Mend: agents that bring failing systems back.** Built for the HUMAIN hackathon, Challenge 1.

## Before you go on stage
- Open the Mend web app at **https://cisntsharp420.github.io/Mend/docs/mend.html** (public, so
  judges can open it too). Keep a copy of `docs/mend.html` on your laptop as a backup: it opens in
  any browser, offline.
- Have the web app open at the top of the page, and one incident PDF already downloaded
  (`mend-ho-05-db-lock-mend-ai.pdf`) in case downloads are blocked on the venue Wi-Fi.
- Optional: the live terminal demo (section 6) needs Docker. Use it only if the machine is ready.

## 1. The problem (30 s)
When production breaks at 3 a.m., someone has to find out *what* broke, *why*, and fix it
without making it worse. Everyone wants AI agents to do this. But how do you know an agent
really fixed the system, and didn't just restart things until the dashboard turned green?

## 2. What I built (45 s)
Mend is an agent that recovers failing systems, and a test bench that proves it.
- **A real system to break:** a five-service shop (gateway, API, Postgres, Redis, worker) under
  live traffic, with 12 realistic fault types and planted red herrings.
- **Mend AI:** reads logs, metrics and diagnostics, turns them into ranked hypotheses with
  confidence scores, applies the gentlest fix for the most likely cause, re-checks, and keeps
  going until the system is healthy. It runs offline, with no API key and no cost.
- **A guarded toolbox:** 17 tools are the only way any agent can touch the system, with budgets,
  safety guardrails, optional human approval, and a full audit trail.
- **An independent verifier:** the agent's opinion never counts. Real user traffic must succeed,
  and a check must prove the root cause is gone, not hidden by a restart.

## 3. Demo in the Mend web app (2 min)
**Open the page.** Point at the hero numbers: 22 incidents, 12 fault types, 12 never-seen tests,
100 recorded runs. *"Every run on this page really happened."*

**Click "Watch a recovery".** It opens `ho-11-conn-leak-and-dns` with **Mend AI** and plays it.
- Two faults at once: a background job leaking database connections, and a bad deploy pointing
  the API at a host that doesn't exist. The challenge calls this out: multiple issues at once.
- Watch the steps: Mend AI sees the database at 38 of 40 connections with "too many clients"
  errors, stops the leaking `report-backfill` job, then sees hostname errors from the bad deploy
  and rolls the config back.
- Verdict card: **100/100**, both root causes named, zero collateral damage, in 42 seconds.
- Point at the agent buttons: **Runbook 10, Restart 3, Idle 10.** Only Mend AI fixed it.

**Open `ho-08-rollback-trap`** (a bad deploy hidden under a harmless one) and click **Restart Agent**.
- It restarts all five services. Nothing is fixed: **0/100**, and 4 of those restarts hit
  services that were never broken.
- *"This is why the verifier matters. A restart can turn the dashboard green for a moment, but it
  doesn't fix anything, and Mend catches that."*

**Pick `ho-05-db-lock`** (a stuck migration locks the orders table).
- **Runbook Agent:** fails, 10/100. Its Recommendations card shows the fix as **Still needed**.
- **Mend AI:** finds the session holding the lock, ends only that session, and scores **100/100**.
- Click **Download this incident**: a two-page incident report an on-call engineer could hand
  to their team the next morning, with the fix and three ways to prevent a repeat.

## 4. The finding (45 s)
Scroll up to **Results**.

| Agent | Dev incidents | Never-seen incidents |
|---|---|---|
| Idle Agent (does nothing) | 10 | 10 |
| Restart Agent | 30 | 10.3, and 42 restarts of healthy services |
| Runbook Agent | 99 | 35 |
| **Mend AI** | **99** | **96.6: 23 of 24 recovered, zero collateral** |

- Restarting everything is no better than doing nothing on new faults, and it causes damage.
- A hand-written runbook collapses on what it wasn't written for: 99 → 35.
- **Mend AI holds up: 99 → 96.6.** An independent re-run in a fresh environment recovered 5 of 5.
- Be upfront: Mend AI never sees the answers, but it was designed knowing the 12 fault types, so
  the never-seen incidents test new situations, not unheard-of faults.

## 5. What's next (30 s)
- **Ablations** are built in: switch off logs, metrics, diagnostics, change history or the
  re-check loop, one at a time, to prove what each part is worth. They run free and offline.
- **Mend AI (Claude)**, a language-model version on the same toolbox, is built and unit-tested;
  it needs an API key to be scored.
- Every run produces the same outputs judges saw today: the web replay, PDF reports and a CSV.

## 6. Backup: live terminal demo (only if Docker is ready)
```bash
python -m recovery inject dev-04-db-password   # a bad config deploy breaks the API
python -m recovery status                       # 503 database errors: orders fail, cached products still load
python -m recovery run --agent reasoner --scenarios dev-04 --tag demo
```
Mend AI rolls back the bad deploy in about 30 seconds with one action, and `status` shows every
endpoint back to 200. For a diagnosis without any change, run `python -m recovery diagnose`
instead of the last command.

## Likely questions
- **Why not trust the agent when it says it fixed it?** Agents over-claim. Only the verifier's
  soak test and root-cause checks count.
- **How do you avoid overfitting?** The dev/never-seen split. The Runbook Agent's 99 → 35 drop
  shows the split works; Mend AI keeps 96.6 on it.
- **Is it safe to let an agent act on production?** Every action goes through guardrails, budgets
  and the audit log, and approval mode puts a human in the loop for risky actions.
- **Where do the recommendations come from?** A remediation playbook for each fault type, labelled
  as such in every report. Mend AI also writes the fix it applied and how to prevent a repeat into
  its own report summary.
- **Is Mend AI a language model?** No. It is a reasoning engine: evidence in, ranked hypotheses
  with confidence scores out, every decision traceable to a log line or metric. That makes it
  explainable, offline, free and reproducible. A Claude-based version on the same toolbox is built
  and tested, and needs only an API key to be scored.
- **Did Mend AI see the held-out answers?** No: it sees only what the toolbox shows. It was
  designed knowing the 12 fault types, so the held-out set tests new combinations, red herrings
  and traps rather than unheard-of faults.
- **Can I see the raw data?** Every episode record is in `runs/`; the CSV download has one row per
  run with every number shown on stage.
