# Pitch: Mend (5 minutes)

**Mend: agents that bring failing systems back.** Built for the HUMAIN hackathon, Challenge 1.

## Before you go on stage
- Open the Mend web app link and use its **Share** menu so judges can open it too. Keep a copy of
  `docs/replay.html` on your laptop as a backup: it opens in any browser, offline.
- Have the web app open at the top of the page, and one incident PDF already downloaded
  (`mend-ho-05-db-lock-runbook-agent.pdf`) in case downloads are blocked on the venue Wi-Fi.
- Optional: the live terminal demo (section 6) needs Docker. Use it only if the machine is ready.

## 1. The problem (30 s)
When production breaks at 3 a.m., someone has to find out *what* broke, *why*, and fix it
without making it worse. Everyone wants AI agents to do this. But how do you know an agent
really fixed the system, and didn't just restart things until the dashboard turned green?

## 2. What I built (45 s)
Mend is a test bench that answers that question honestly.
- **A real system to break:** a five-service shop (gateway, API, Postgres, Redis, worker) under
  live traffic.
- **12 realistic faults:** bad config deploys, DNS errors, crash loops, memory leaks, full disks,
  runaway CPU, database locks, connection leaks, network cuts, plus planted red herrings.
- **A guarded toolbox:** 17 tools are the only way an agent can touch the system, with budgets,
  safety guardrails, optional human approval, and a full audit trail.
- **An independent verifier:** the agent's opinion never counts. Real user traffic must succeed,
  and a check must prove the root cause is gone, not hidden by a restart.

## 3. Demo in the Mend web app (2 min)
**Open the page.** Point at the hero numbers: 22 incidents, 12 fault types, 12 never-seen tests,
66 recorded runs. *"Every run on this page really happened."*

**Click "Watch a recovery".** It opens `ho-08-rollback-trap` with the **Runbook Agent** and plays it.
- The trap: a bad deploy, then a harmless deploy on top of it, so "undo the last change" is not
  enough.
- Watch the steps: it checks services and logs, rolls back once, checks the endpoints again,
  sees it is still broken, rolls back one more version, confirms with the verifier, and reports
  `api/bad_config_deploy` with the evidence "db password authentication failed".
- Verdict card: **100/100**, two actions, zero collateral damage.

**Switch to the Restart Agent** on the same incident.
- It restarts all five services. Nothing is fixed: **0/100**, and 4 of those restarts hit
  services that were never broken.
- *"This is why the verifier matters. A restart can turn the dashboard green for a moment, but it
  doesn't fix anything, and Mend catches that."*

**Pick `ho-05-db-lock`** (a stuck migration locks the orders table) with the Runbook Agent.
- It fails: 10/100, no root cause. The runbook has never seen this fault.
- Scroll to **Recommendations**: the immediate fix is marked **Still needed** ("terminate the
  migration-runner session holding the lock"), with three ways to prevent a repeat.
- Click **Download this incident**: a two-page incident report an on-call engineer could hand
  to their team the next morning.

## 4. The finding (45 s)
Scroll up to **Results**.

| Agent | Dev incidents | Never-seen incidents |
|---|---|---|
| Idle Agent (does nothing) | 10 | 10 |
| Restart Agent | 30 | 10.3, and 42 restarts of healthy services |
| Runbook Agent | **99** | **35** |

- Restarting everything is no better than doing nothing on new faults, and it causes damage.
- A hand-written runbook is nearly perfect on what it was written for and collapses on what it
  wasn't: 99 → 35.
- That gap, **handling failures nobody wrote a rule for**, is exactly what an AI agent has to
  close, and Mend measures it on incidents that were never used for tuning.

## 5. What's next (30 s)
- **Mend AI**, the Claude agent, is built and unit-tested: same toolbox, step-by-step reasoning
  kept in the trace, every decision recorded and replayable, and ablation variants to measure
  what each capability adds. It writes its own recommendations into the report.
- Running it is one command. Because the never-seen incidents were never used for tuning,
  whatever it scores will be an honest number.
- Every run produces the same outputs judges saw today: the web replay, PDF reports and a CSV.

## 6. Backup: live terminal demo (only if Docker is ready)
```bash
python -m recovery inject dev-04-db-password   # a bad config deploy breaks the API
python -m recovery status                       # 503 database errors: orders fail, cached products still load
python -m recovery run --agent rules --scenarios dev-04 --tag demo
```
The Runbook Agent rolls back the bad deploy in about 20 seconds with one action, and `status`
shows every endpoint back to 200.

## Likely questions
- **Why not trust the agent when it says it fixed it?** Agents over-claim. Only the verifier's
  soak test and root-cause checks count.
- **How do you avoid overfitting?** The dev/never-seen split. The Runbook Agent's 99 → 35 drop
  shows the split works.
- **Is it safe to let an agent act on production?** Every action goes through guardrails, budgets
  and the audit log, and approval mode puts a human in the loop for risky actions.
- **Where do the recommendations come from?** A remediation playbook for each fault type, labelled
  as such in every report. Mend AI adds its own advice alongside it.
- **Why is there no Mend AI score yet?** There was no API access during the build. The agent code
  and its replay tests are in `recovery/agents/llm.py` and `tests/test_llm_agent.py`.
- **Can I see the raw data?** Every episode record is in `runs/`; the CSV download has one row per
  run with every number shown on stage.
