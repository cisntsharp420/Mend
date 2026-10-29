"""Independent recovery verifier. The agent's opinion never counts: only these checks do.

A system is "recovered" when, over a soak window, synthetic user journeys succeed with
acceptable latency, every core service is running with no new restarts, the API reports
all dependencies healthy, and each injected fault's residual check passes (the root cause
is actually gone, not just masked by a restart).
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field

from .sandbox import CORE_SERVICES, Sandbox

PROBES = [
    ("GET", "/healthz", None),
    ("GET", "/api/health", None),
    ("GET", "/api/products", None),
    ("GET", "/api/orders/recent", None),
    ("POST", "/api/orders", "order"),
]
SUCCESS_THRESHOLD = 0.97
P95_THRESHOLD_MS = 400


@dataclass
class ProbeResult:
    method: str
    path: str
    status: int
    latency_ms: float
    ok: bool
    detail: str = ""


@dataclass
class VerifyResult:
    passed: bool
    success_rate: float
    p95_ms: float
    failures: list[str] = field(default_factory=list)
    probe_summary: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def run_probes(sb: Sandbox) -> list[ProbeResult]:
    results = []
    for method, path, body in PROBES:
        payload = {"product_id": random.randint(1, 50), "qty": 1} if body == "order" else None
        t0 = time.monotonic()
        status, text = sb.http(method, path, payload, timeout=5)
        ms = (time.monotonic() - t0) * 1000
        ok = 200 <= status < 300
        if ok and path == "/api/health":
            try:
                ok = json.loads(text).get("status") == "ok"
            except json.JSONDecodeError:
                ok = False
        results.append(ProbeResult(method, path, status, round(ms, 1), ok, "" if ok else text[:160]))
    return results


def summarize(results: list[ProbeResult]) -> dict:
    by = {}
    for r in results:
        key = f"{r.method} {r.path}"
        d = by.setdefault(key, {"ok": 0, "fail": 0, "statuses": set(), "last_error": ""})
        d["ok" if r.ok else "fail"] += 1
        d["statuses"].add(r.status)
        if not r.ok:
            d["last_error"] = r.detail
    return {k: {**v, "statuses": sorted(v["statuses"])} for k, v in by.items()}


def soak(sb: Sandbox, duration_s: float = 15, interval_s: float = 1.0,
         faults=None) -> VerifyResult:
    before = {s: sb.service_state(s) for s in CORE_SERVICES}
    results: list[ProbeResult] = []
    deadline = time.time() + duration_s
    while time.time() < deadline:
        results += run_probes(sb)
        time.sleep(interval_s)

    failures = []
    ok_rate = sum(r.ok for r in results) / max(1, len(results))
    lat = sorted(r.latency_ms for r in results)
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0.0
    if ok_rate < SUCCESS_THRESHOLD:
        failures.append(f"probe success {ok_rate:.0%} < {SUCCESS_THRESHOLD:.0%}")
    if p95 > P95_THRESHOLD_MS:
        failures.append(f"probe p95 {p95:.0f}ms > {P95_THRESHOLD_MS}ms")

    for s in CORE_SERVICES:
        after = sb.service_state(s)
        if after["state"] != "running":
            failures.append(f"{s} is {after['state']}")
        elif after.get("restart_count", 0) > before[s].get("restart_count", 0):
            failures.append(f"{s} restarted during soak (crash loop?)")

    for f in faults or []:
        ok, msg = f.residual(sb)
        if not ok:
            failures.append(f"residual[{f.kind}:{f.resolved_target}]: {msg}")

    return VerifyResult(not failures, round(ok_rate, 3), round(p95, 1), failures, summarize(results))
