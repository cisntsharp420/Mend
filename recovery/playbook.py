"""Remediation playbook: the immediate fix and the prevention advice for each fault type.

Used to add a Recommendations section to incident reports. This is fixed reference advice written
for ShopStack, keyed by the injected fault (known after the episode), not something an agent
inferred; an agent's own advice travels separately in its report's `recommendations` field.
"""
from __future__ import annotations

from .faults import FAULTS

PLAYBOOK: dict[str, dict] = {
    "service_stopped": {
        "fix": "Start the {target} service (start_service), then confirm the endpoints recover.",
        "prevent": ["Set a restart policy (restart: unless-stopped) so a stopped container comes back on its own.",
                    "Alert on service state and container exits, not only on failing user traffic.",
                    "Record who stops production services and require a change ticket for manual stops."],
    },
    "bad_db_password": {
        "fix": "Roll back the api config to the last version with the working database password.",
        "prevent": ["Rotate credentials through a secrets manager in step with the database, never by editing app config.",
                    "Run a pre-deploy check that the new config can authenticate to the database.",
                    "Deploy config as a canary and roll back automatically when health checks fail."],
    },
    "bad_db_host": {
        "fix": "Roll back the api config to the last version that points at the reachable database host (postgres).",
        "prevent": ["Validate that every hostname in a config change resolves from inside the target environment before deploying.",
                    "Change database endpoints behind a stable DNS alias, not by editing each service's config.",
                    "Roll back automatically when the dependency health check fails right after a deploy."],
    },
    "crashloop_config": {
        "fix": "Roll back the api config to the last version that boots, then confirm the service stays up with no new restarts.",
        "prevent": ["Validate config against a schema in CI so unknown or renamed sections are rejected before deploy.",
                    "Alert on restart loops (restart count rising) separately from plain downtime.",
                    "Make the app fail with a clear config error message instead of crashing without one."],
    },
    "bad_tax_rate": {
        "fix": "Roll back the api config to the last version with a numeric tax rate, then confirm order creation works.",
        "prevent": ["Type-check business settings (tax rate must be a number between 0 and 1) in the config UI and in CI.",
                    "Monitor each user journey separately: here only order creation failed while health checks looked fine.",
                    "Require review for finance-owned config changes that reach production."],
    },
    "memory_leak": {
        "fix": "Roll back the config change that enabled the unbounded local cache, then confirm memory stays flat and OOM kills stop.",
        "prevent": ["Give every in-process cache a size limit and eviction policy.",
                    "Roll out feature flags gradually, watching memory, before enabling them everywhere.",
                    "Alert on OOM kills and on memory growth trends, not only on outages."],
    },
    "gateway_bad_upstream": {
        "fix": "Roll back the gateway config to the last version with the correct api upstream port (api:8000).",
        "prevent": ["Run nginx -t and an upstream connectivity check as part of every gateway deploy.",
                    "Keep upstream addresses in one shared service registry instead of hand-edited configs.",
                    "Deploy gateway changes with automatic rollback when 5xx rates jump."],
    },
    "disk_full": {
        "fix": "Delete the runaway temporary export under /data/tmp/ on api, then confirm /data is below 80%.",
        "prevent": ["Alert when the data volume passes 80% so it is caught before writes fail.",
                    "Write exports to object storage or a separate volume with a quota, not to the app's data volume.",
                    "Clean up temporary files automatically (TTL) and cap export sizes."],
    },
    "cpu_hog": {
        "fix": "Stop the runaway reindex_search job on api (kill_process), then confirm latency returns to normal.",
        "prevent": ["Run batch jobs like search reindexing on a worker or a schedule, never inside the serving api container.",
                    "Set CPU limits per container so one job cannot starve request handling.",
                    "Alert on sustained high CPU together with rising p95 latency."],
    },
    "db_lock": {
        "fix": "Terminate the migration-runner session holding the exclusive lock on orders (terminate_db_sessions).",
        "prevent": ["Set lock_timeout and statement_timeout for migrations so they fail instead of blocking traffic.",
                    "Run schema migrations with online, non-blocking patterns during low-traffic windows.",
                    "Alert on sessions blocked by locks for more than a few seconds."],
    },
    "conn_exhaustion": {
        "fix": "Stop the leaking report_backfill job in the worker and terminate its database sessions.",
        "prevent": ["Use a bounded connection pool in every job, and close connections in finally blocks.",
                    "Give each application its own connection limit (per-role CONNECTION LIMIT or a pooler such as PgBouncer).",
                    "Alert when database connections pass 80% of max_connections."],
    },
    "network_partition": {
        "fix": "Reconnect {target} to the backend network (reconnect_network), then confirm its dependents recover.",
        "prevent": ["Manage network attachments only through docker compose or infrastructure code, never by hand.",
                    "Add connectivity checks between dependent services to monitoring.",
                    "Alert on dependency health (database/cache unreachable) with the exact component named."],
    },
}


def recommendations(faults: list[dict]) -> list[dict]:
    """Playbook entries for an episode's injected faults, with the fault's target filled in."""
    out = []
    for f in faults:
        entry = PLAYBOOK.get(f["kind"])
        if entry:
            target = f.get("target") or FAULTS[f["kind"]].default_target
            out.append({"fault": f["kind"], "target": target, "fix": entry["fix"].format(target=target),
                        "prevent": list(entry["prevent"])})
    return out
