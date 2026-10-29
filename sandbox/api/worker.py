"""Background worker: periodically refreshes a sales summary (light, well-behaved DB usage)."""
import time

from common import db_connect, load_config, setup_logging

cfg = load_config()
log = setup_logging("worker")

while True:
    try:
        with db_connect(cfg, "shop-worker") as conn:
            n, total = conn.execute("SELECT count(*), coalesce(sum(total),0) FROM orders").fetchone()
        log.info("sales summary refreshed: orders=%d revenue=%.2f", n, total)
    except Exception as e:
        log.error("summary refresh failed: %s", str(e).strip())
    time.sleep(10)
