"""Fault library: how each failure is injected, its ground truth, and how to tell it is truly gone.

Ground truth is only ever used by the harness for scoring. Agents never see this module;
they only see symptoms through the tools.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .sandbox import Sandbox

# Root-cause taxonomy agents must report in. Kept small and operational on purpose.
CATEGORIES = [
    "service_down",
    "bad_config_deploy",
    "cpu_exhaustion",
    "memory_exhaustion",
    "disk_full",
    "db_lock_contention",
    "db_connection_exhaustion",
    "network_partition",
]


@dataclass(frozen=True)
class RootCause:
    component: str
    category: str


@dataclass
class FaultSpec:
    kind: str
    description: str
    inject: Callable[[Sandbox, str, dict], None]
    truth: Callable[[str], list[RootCause]]  # first entry is canonical, rest are accepted alternatives
    residual: Callable[[Sandbox, str], tuple[bool, str]]
    default_target: str
    settle_s: float = 8.0


@dataclass
class Fault:
    kind: str
    target: str | None = None
    params: dict = field(default_factory=dict)

    @property
    def spec(self) -> FaultSpec:
        return FAULTS[self.kind]

    @property
    def resolved_target(self) -> str:
        return self.target or self.spec.default_target

    def inject(self, sb: Sandbox) -> None:
        self.spec.inject(sb, self.resolved_target, self.params)

    def truth(self) -> list[RootCause]:
        return self.spec.truth(self.resolved_target)

    def residual(self, sb: Sandbox) -> tuple[bool, str]:
        return self.spec.residual(sb, self.resolved_target)


# ---------------------------------------------------------------------- helpers
def _deploy_edit(sb: Sandbox, service: str, old: str, new: str, summary: str, author: str = "ci-bot"):
    cfg = sb.read_config(service)
    if old not in cfg:
        raise ValueError(f"cannot inject: {old!r} not found in live {service} config")
    sb.deploy_config(service, cfg.replace(old, new, 1), summary, author)


def _config_lacks(marker: str, service: str = "api"):
    def check(sb: Sandbox, _target: str):
        ok = marker not in sb.read_config(service)
        return ok, "faulty setting removed" if ok else f"live {service} config still contains {marker!r}"
    return check


def _running(sb: Sandbox, target: str):
    st = sb.service_state(target)
    return st["state"] == "running", f"{target} is {st['state']}"


def _no_process(service: str, needle: str):
    def check(sb: Sandbox, _target: str):
        r = sb.exec(service, "ps -o args")
        ok = needle not in r.out
        return ok, f"no '{needle}' process" if ok else f"'{needle}' still running in {service}"
    return check


# ---------------------------------------------------------------------- injectors
def inj_service_stopped(sb, target, p):
    sb.compose("stop", target, timeout=60, check=True)


def inj_bad_db_password(sb, target, p):
    _deploy_edit(sb, "api", "password: shop-secret", "password: shop-s3cret-2026",
                 "rotate database credentials (SEC-4411)")


def inj_bad_db_host(sb, target, p):
    _deploy_edit(sb, "api", "host: postgres", "host: postgres-primary.internal",
                 "point api at new primary database endpoint")


def inj_crashloop_config(sb, target, p):
    _deploy_edit(sb, "api", "audit:\n", "auditing:\n", "restructure audit settings")


def inj_bad_tax_rate(sb, target, p):
    _deploy_edit(sb, "api", "tax_rate: 0.15", 'tax_rate: "15%"', "update VAT rate for new fiscal year",
                 author="finance-config-ui")


def inj_memory_leak(sb, target, p):
    _deploy_edit(sb, "api", "local_response_cache: false", "local_response_cache: true",
                 "enable local response cache to reduce redis load")


def inj_gateway_bad_upstream(sb, target, p):
    _deploy_edit(sb, "gateway", "server api:8000;", "server api:8001;",
                 "update api upstream port for v2 release")


def inj_disk_full(sb, target, p):
    sb.exec(target, "mkdir -p /data/tmp && dd if=/dev/zero of=/data/tmp/export-orders-20261029.csv.tmp "
                    "bs=1M count=100 2>/dev/null; sync", timeout=30)


def inj_cpu_hog(sb, target, p):
    sb.exec(target, ["python", "/app/tools/reindex_search.py"], detach=True)


def inj_db_lock(sb, target, p):
    sb.exec("postgres", ["psql", "-U", "shop", "-d", "shop", "-c",
                         "BEGIN; LOCK TABLE orders IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(3600);"],
            detach=True, env={"PGAPPNAME": "migration-runner"})


def inj_conn_exhaustion(sb, target, p):
    sb.exec(target, ["python", "/app/tools/report_backfill.py"], detach=True, env={"PYTHONPATH": "/app"})


def inj_network_partition(sb, target, p):
    sb.docker("network", "disconnect", sb.network("backend"), sb.container(target), check=True)


# ---------------------------------------------------------------------- residual checks
def res_disk(sb, target):
    r = sb.exec(target, "df -P /data | tail -1")
    try:
        used = int(r.out.split()[4].rstrip("%"))
    except (IndexError, ValueError):
        return False, f"could not read disk usage: {r.out}"
    return used < 80, f"/data at {used}%"


def res_db_lock(sb, target):
    r = sb.psql("SELECT count(*) FROM pg_stat_activity WHERE application_name='migration-runner'")
    ok = r.ok and r.out.strip() == "0"
    return ok, "lock holder gone" if ok else f"migration-runner sessions: {r.out}"


def res_conn_exhaustion(sb, target):
    ok_proc, msg = _no_process(target, "report_backfill")(sb, target)
    r = sb.psql("SELECT count(*) FROM pg_stat_activity WHERE application_name='report-backfill'")
    ok_db = r.ok and int(r.out.strip() or 0) == 0
    return ok_proc and ok_db, f"{msg}; backfill connections={r.out.strip()}"


def res_partition(sb, target):
    nets = set(sb.service_state(target).get("networks", []))
    return "backend" in nets, f"{target} networks={sorted(nets)}"


def _one(category, alt=None):
    def truth(target):
        causes = [RootCause(target, category)]
        if alt:
            causes += [RootCause(c, k) for c, k in alt(target)]
        return causes
    return truth


FAULTS: dict[str, FaultSpec] = {s.kind: s for s in [
    FaultSpec("service_stopped", "A core service process is stopped.",
              inj_service_stopped, _one("service_down"), _running, "api", settle_s=6),
    FaultSpec("bad_db_password", "Config deploy with wrong DB password.",
              inj_bad_db_password, lambda t: [RootCause("api", "bad_config_deploy")],
              _config_lacks("shop-s3cret-2026"), "api"),
    FaultSpec("bad_db_host", "Config deploy pointing at a non-existent DB host (DNS failure).",
              inj_bad_db_host, lambda t: [RootCause("api", "bad_config_deploy")],
              _config_lacks("postgres-primary.internal"), "api"),
    FaultSpec("crashloop_config", "Config deploy that makes the API crash on boot.",
              inj_crashloop_config, lambda t: [RootCause("api", "bad_config_deploy"),
                                               RootCause("api", "service_down")],
              _config_lacks("auditing:"), "api", settle_s=10),
    FaultSpec("bad_tax_rate", "Config deploy with an invalid tax rate; only order creation fails.",
              inj_bad_tax_rate, lambda t: [RootCause("api", "bad_config_deploy")],
              _config_lacks('"15%"'), "api"),
    FaultSpec("memory_leak", "Feature flag enabling an unbounded in-process cache (OOM loop).",
              inj_memory_leak, lambda t: [RootCause("api", "bad_config_deploy"),
                                          RootCause("api", "memory_exhaustion")],
              _config_lacks("local_response_cache: true"), "api", settle_s=25),
    FaultSpec("gateway_bad_upstream", "Gateway config deploy with wrong upstream port.",
              inj_gateway_bad_upstream, lambda t: [RootCause("gateway", "bad_config_deploy")],
              _config_lacks("api:8001", "gateway"), "gateway"),
    FaultSpec("disk_full", "A runaway export fills the API data volume.",
              inj_disk_full, _one("disk_full"), res_disk, "api"),
    FaultSpec("cpu_hog", "A runaway search reindex job saturates the API's CPU.",
              inj_cpu_hog, _one("cpu_exhaustion"), _no_process("api", "reindex_search"), "api", settle_s=10),
    FaultSpec("db_lock", "A stuck migration holds an exclusive lock on the orders table.",
              inj_db_lock, lambda t: [RootCause("postgres", "db_lock_contention")],
              res_db_lock, "postgres"),
    FaultSpec("conn_exhaustion", "A backfill job in the worker leaks DB connections (and reconnects).",
              inj_conn_exhaustion, lambda t: [RootCause("worker", "db_connection_exhaustion"),
                                              RootCause("postgres", "db_connection_exhaustion")],
              res_conn_exhaustion, "worker"),
    FaultSpec("network_partition", "A backend service is cut off from the backend network.",
              inj_network_partition, _one("network_partition"), res_partition, "postgres"),
]}


# ---------------------------------------------------------------------- noise (red herrings)
def noise_benign_api_deploy(sb: Sandbox):
    _deploy_edit(sb, "api", "ttl_s: 30", "ttl_s: 45", "tune cache TTL", author="dev-ahmed")


def noise_benign_gateway_deploy(sb: Sandbox):
    _deploy_edit(sb, "gateway", "worker_connections 512;", "worker_connections 1024;",
                 "raise gateway worker connections", author="dev-sara")


def noise_worker_warnings(sb: Sandbox):
    sb.exec("worker", "for i in 1 2 3 4 5; do echo \"$(date -u +%Y-%m-%dT%H:%M:%S) WARNING worker "
                      "deprecated report format v1 requested by legacy client\" > /proc/1/fd/1; done")


NOISE: dict[str, Callable[[Sandbox], None]] = {
    "benign_api_deploy": noise_benign_api_deploy,
    "benign_gateway_deploy": noise_benign_gateway_deploy,
    "worker_warnings": noise_worker_warnings,
}


def inject_all(sb: Sandbox, faults: list[Fault], noise: list[str], noise_first: bool = True) -> float:
    """Inject noise and faults; returns how long to wait for symptoms to develop."""
    if noise_first:
        for n in noise:
            NOISE[n](sb)
    for f in faults:
        f.inject(sb)
        time.sleep(1)
    if not noise_first:
        for n in noise:
            NOISE[n](sb)
    return max(f.spec.settle_s for f in faults)
