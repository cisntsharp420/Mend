"""Historical report backfill. (Fault injection: leaks DB connections and reconnects if killed.)"""
import time

from common import db_connect, load_config

cfg = load_config()
held = []
while True:
    held = [c for c in held if not c.closed]
    try:
        while len(held) < 40:
            c = db_connect(cfg, "report-backfill")
            c.execute("SELECT count(*) FROM orders")
            held.append(c)
    except Exception:
        pass
    for c in list(held):
        try:
            c.execute("SELECT 1")
        except Exception:
            held.remove(c)
    time.sleep(2)
