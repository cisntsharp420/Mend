"""ShopStack API: a small order service backed by Postgres (data) and Redis (cache)."""
import collections
import hashlib
import json
import os
import threading
import time

from flask import Flask, g, jsonify, request
from waitress import serve

from common import cache_client, db_connect, load_config, setup_logging

cfg = load_config()
log = setup_logging("api", cfg.get("logging", {}).get("level", "INFO"))
app = Flask(__name__)
cache = cache_client(cfg)

# Rolling request window for /metrics: (timestamp, endpoint, status, latency_ms)
WINDOW_S = 60
_requests = collections.deque(maxlen=20000)
_counters = collections.Counter()
_lock = threading.Lock()
# Unbounded per-process response cache; only active when the feature flag is on.
_local_cache = []


def _cpu_work(payload: str) -> str:
    # Simulates request-time CPU work (serialization, pricing rules).
    h = payload.encode()
    for _ in range(1500):
        h = hashlib.sha256(h).digest()
    return h.hex()


@app.before_request
def _start():
    g.t0 = time.monotonic()


@app.after_request
def _record(resp):
    ms = (time.monotonic() - g.t0) * 1000
    endpoint = request.url_rule.rule if request.url_rule else "unmatched"
    with _lock:
        _requests.append((time.time(), endpoint, resp.status_code, ms))
    if resp.status_code >= 500:
        log.error("%s %s -> %d (%.0fms)", request.method, request.path, resp.status_code, ms)
    if cfg.get("features", {}).get("local_response_cache"):
        _local_cache.append(bytearray(2 * 1024 * 1024))
    return resp


def _db():
    return db_connect(cfg, "shop-api")


def _cache_get(key):
    if not cfg["cache"].get("enabled", True):
        return None
    try:
        v = cache.get(key)
        return json.loads(v) if v else None
    except Exception as e:
        _counters["cache_errors"] += 1
        log.warning("cache unavailable, falling back to database: %s", e)
        return None


def _cache_set(key, value):
    try:
        cache.setex(key, cfg["cache"].get("ttl_s", 30), json.dumps(value))
    except Exception as e:
        _counters["cache_errors"] += 1
        log.warning("cache write failed: %s", e)


@app.get("/api/products")
def products():
    data = _cache_get("products")
    if data is None:
        try:
            with _db() as conn:
                rows = conn.execute("SELECT id, name, price FROM products ORDER BY id").fetchall()
        except Exception as e:
            _counters["db_errors"] += 1
            log.error("db query failed (products): %s", str(e).strip())
            return jsonify(error="database unavailable"), 503
        data = [{"id": r[0], "name": r[1], "price": float(r[2])} for r in rows]
        _cache_set("products", data)
    _cpu_work(str(len(data)))
    return jsonify(products=data)


@app.get("/api/orders/recent")
def recent_orders():
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT id, product_id, qty, total, created_at FROM orders ORDER BY id DESC LIMIT 20"
            ).fetchall()
    except Exception as e:
        _counters["db_errors"] += 1
        log.error("db query failed (recent orders): %s", str(e).strip())
        return jsonify(error="database error"), 503
    _cpu_work(str(len(rows)))
    return jsonify(orders=[{"id": r[0], "product_id": r[1], "qty": r[2], "total": float(r[3])} for r in rows])


@app.post("/api/orders")
def create_order():
    body = request.get_json(silent=True) or {}
    product_id, qty = int(body.get("product_id", 1)), int(body.get("qty", 1))
    try:
        tax_rate = float(cfg["pricing"]["tax_rate"])
        if not 0 <= tax_rate < 1:
            raise ValueError(f"tax_rate out of range: {tax_rate}")
    except (ValueError, TypeError) as e:
        log.error("pricing config invalid: %s", e)
        return jsonify(error="pricing error"), 500
    try:
        with _db() as conn:
            price = conn.execute("SELECT price FROM products WHERE id=%s", (product_id,)).fetchone()
            if not price:
                return jsonify(error="unknown product"), 404
            total = round(float(price[0]) * qty * (1 + tax_rate), 2)
            oid = conn.execute(
                "INSERT INTO orders (product_id, qty, total) VALUES (%s, %s, %s) RETURNING id",
                (product_id, qty, total),
            ).fetchone()[0]
    except Exception as e:
        _counters["db_errors"] += 1
        log.error("db write failed (create order): %s", str(e).strip())
        return jsonify(error="database error"), 503
    try:
        with open(cfg["audit"]["path"], "a") as f:
            f.write(json.dumps({"ts": time.time(), "order": oid, "total": total}) + "\n")
    except OSError as e:
        log.error("audit log write failed: %s", e)
        return jsonify(error="audit failure", order=oid), 500
    _cpu_work(str(oid))
    return jsonify(id=oid, total=total), 201


@app.get("/api/health")
def health():
    checks = {}
    try:
        with _db() as conn:
            conn.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e).strip()[:120]}"
    try:
        cache.ping()
        checks["cache"] = "ok"
    except Exception as e:
        checks["cache"] = f"error: {e}"
    try:
        # Write a realistic-size scratch file: a nearly full volume fails here first.
        probe = os.path.join(os.path.dirname(cfg["audit"]["path"]), f".health-{threading.get_ident()}")
        with open(probe, "wb") as f:
            f.write(b"\0" * 65536)
        os.remove(probe)
        checks["disk"] = "ok"
    except OSError as e:
        checks["disk"] = f"error: {e}"
    healthy = all(v == "ok" for v in checks.values())
    status = "ok" if healthy else ("degraded" if checks["database"] == "ok" else "down")
    return jsonify(status=status, checks=checks), (200 if status != "down" else 503)


@app.get("/metrics")
def metrics():
    now = time.time()
    with _lock:
        recent = [r for r in _requests if r[0] >= now - WINDOW_S]
    by_ep = collections.defaultdict(list)
    for _, ep, status, ms in recent:
        by_ep[ep].append((status, ms))

    def pct(vals, p):
        vals = sorted(vals)
        return round(vals[min(len(vals) - 1, int(len(vals) * p))], 1) if vals else None

    endpoints = {
        ep: {
            "requests": len(v),
            "errors_5xx": sum(1 for s, _ in v if s >= 500),
            "p50_ms": pct([m for _, m in v], 0.5),
            "p95_ms": pct([m for _, m in v], 0.95),
        }
        for ep, v in by_ep.items()
    }
    with open("/proc/self/status") as f:
        rss_kb = next(int(l.split()[1]) for l in f if l.startswith("VmRSS"))
    return jsonify(
        window_s=WINDOW_S,
        endpoints=endpoints,
        db_errors_total=_counters["db_errors"],
        cache_errors_total=_counters["cache_errors"],
        process_rss_mb=round(rss_kb / 1024, 1),
        uptime_s=round(time.monotonic() - START, 1),
    )


START = time.monotonic()

if __name__ == "__main__":
    os.makedirs(os.path.dirname(cfg["audit"]["path"]), exist_ok=True)
    log.info("starting shop-api on :%d (db=%s:%s cache=%s:%s)", cfg["server"]["port"],
             cfg["database"]["host"], cfg["database"]["port"], cfg["cache"]["host"], cfg["cache"]["port"])
    serve(app, host="0.0.0.0", port=cfg["server"]["port"], threads=cfg["server"].get("threads", 16),
          channel_timeout=10)
