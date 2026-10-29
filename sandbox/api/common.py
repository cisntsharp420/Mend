"""Shared helpers for the ShopStack services: config loading, logging, DB/cache clients."""
import logging
import os
import sys

import psycopg
import redis
import yaml

CONFIG_PATH = os.environ.get("APP_CONFIG", "/config/app.yaml")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # Fail fast on structurally broken config, like a real service would.
    for section in ("server", "database", "cache", "pricing", "audit"):
        if section not in cfg:
            raise KeyError(f"missing required config section '{section}'")
    return cfg


def setup_logging(service: str, level: str = "INFO") -> logging.Logger:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format=f"%(asctime)s %(levelname)s {service} %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    return logging.getLogger(service)


def db_connect(cfg: dict, application_name: str) -> psycopg.Connection:
    db = cfg["database"]
    return psycopg.connect(
        host=db["host"],
        port=db["port"],
        dbname=db["name"],
        user=db["user"],
        password=db["password"],
        connect_timeout=db.get("connect_timeout_s", 2),
        application_name=application_name,
        options=f"-c statement_timeout={db.get('statement_timeout_ms', 2000)}",
        autocommit=True,
    )


def cache_client(cfg: dict) -> redis.Redis:
    c = cfg["cache"]
    return redis.Redis(
        host=c["host"], port=c["port"], socket_timeout=0.5, socket_connect_timeout=0.5
    )
