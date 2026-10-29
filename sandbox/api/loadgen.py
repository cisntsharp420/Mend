"""Synthetic user traffic against the gateway so logs and metrics reflect real load."""
import json
import os
import random
import time
import urllib.error
import urllib.request

BASE = os.environ.get("TARGET", "http://gateway")
RPS = float(os.environ.get("RPS", "8"))


def hit(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        pass


while True:
    r = random.random()
    if r < 0.5:
        hit("GET", "/api/products")
    elif r < 0.8:
        hit("GET", "/api/orders/recent")
    elif r < 0.98:
        hit("POST", "/api/orders", {"product_id": random.randint(1, 50), "qty": random.randint(1, 3)})
    else:
        hit("GET", "/api/legacy/cart")  # stale client hitting a removed endpoint (benign 404 noise)
    time.sleep(1 / RPS)
