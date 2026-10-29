"""Control plane for the ShopStack sandbox: docker ops, live config versions, change log.

Everything the harness, the fault injector and the agent tools do to the system goes
through this class, so there is exactly one place that touches docker.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = ROOT / "sandbox"

# Services the agent is responsible for. loadgen simulates external users and is hidden.
CORE_SERVICES = ["gateway", "api", "worker", "postgres", "redis"]
STATEFUL_SERVICES = {"postgres", "redis"}
NETWORKS = {"frontend", "backend"}
EXPECTED_NETWORKS = {
    "gateway": {"frontend"},
    "api": {"frontend", "backend"},
    "worker": {"backend"},
    "postgres": {"backend"},
    "redis": {"backend"},
}
# Live config file per configurable service, and how a new version is applied.
CONFIG_FILES = {"api": "app.yaml", "gateway": "nginx.conf"}


@dataclass
class ExecResult:
    rc: int
    out: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


class Sandbox:
    def __init__(self, project: str = "shopstack", gateway_port: int = 8080):
        self.project = project
        self.gateway_url = f"http://localhost:{gateway_port}"
        self.runtime = SANDBOX_DIR / ".runtime"
        self.changes_file = self.runtime / "changes.jsonl"

    # ------------------------------------------------------------------ docker plumbing
    def _run(self, args: list[str], timeout: float = 60, check: bool = False) -> ExecResult:
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            res = ExecResult(p.returncode, (p.stdout + p.stderr).strip())
        except subprocess.TimeoutExpired:
            res = ExecResult(124, f"timed out after {timeout}s")
        if check and not res.ok:
            raise RuntimeError(f"{' '.join(args)} failed: {res.out[-2000:]}")
        return res

    def compose(self, *args: str, timeout: float = 180, check: bool = False) -> ExecResult:
        return self._run(["docker", "compose", "-p", self.project, "-f",
                          str(SANDBOX_DIR / "docker-compose.yml"), *args], timeout, check)

    def docker(self, *args: str, timeout: float = 30, check: bool = False) -> ExecResult:
        return self._run(["docker", *args], timeout, check)

    def container(self, service: str) -> str:
        return f"{self.project}-{service}-1"

    def network(self, name: str) -> str:
        return f"{self.project}_{name}"

    def exec(self, service: str, cmd: list[str] | str, detach: bool = False,
             env: dict | None = None, timeout: float = 15, user: str | None = None) -> ExecResult:
        if isinstance(cmd, str):
            cmd = ["sh", "-c", cmd]
        args = ["exec"]
        if detach:
            args.append("-d")
        if user:
            args += ["-u", user]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        return self.docker(*args, self.container(service), *cmd, timeout=timeout)

    def psql(self, sql: str, timeout: float = 10) -> ExecResult:
        return self.exec("postgres", ["psql", "-U", "shop", "-d", "shop", "-At", "-F", " | ", "-c", sql],
                         timeout=timeout)

    # ------------------------------------------------------------------ lifecycle
    def build(self) -> None:
        self.compose("build", "-q", timeout=900, check=True)

    def reset(self) -> None:
        """Return the system to a clean, known-good state (fresh containers, v1 configs)."""
        if self.runtime.exists():
            shutil.rmtree(self.runtime)
        (self.runtime / "config").mkdir(parents=True)
        for service, fname in CONFIG_FILES.items():
            dst = self.runtime / "config" / service
            dst.mkdir()
            shutil.copy(SANDBOX_DIR / "config" / service / fname, dst / fname)
            vdir = self.runtime / "versions" / service
            vdir.mkdir(parents=True)
            shutil.copy(SANDBOX_DIR / "config" / service / fname, vdir / f"v1-{fname}")
        self.changes_file.write_text("")
        self.compose("up", "-d", "--force-recreate", "--renew-anon-volumes", "--remove-orphans", "--wait",
                     timeout=300, check=True)
        self.wait_healthy(timeout=60)

    def down(self) -> None:
        self.compose("down", "-v", "--remove-orphans", timeout=120)

    def wait_healthy(self, timeout: float = 60) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            code, body = self.http("GET", "/api/health", timeout=3)
            if code == 200 and '"status":"ok"' in body.replace(" ", ""):
                return True
            time.sleep(1)
        return False

    # ------------------------------------------------------------------ observation
    def http(self, method: str, path: str, body: dict | None = None, timeout: float = 5):
        req = urllib.request.Request(self.gateway_url + path, method=method,
                                     data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except Exception as e:  # connection refused, timeout, reset
            return 0, f"{type(e).__name__}: {e}"

    def inspect(self, service: str) -> dict | None:
        r = self.docker("inspect", self.container(service))
        if not r.ok:
            return None
        return json.loads(r.out)[0]

    def service_state(self, service: str) -> dict:
        info = self.inspect(service)
        if info is None:
            return {"service": service, "state": "missing"}
        st = info["State"]
        return {
            "service": service,
            "state": st["Status"],  # running | exited | restarting | paused | dead
            "exit_code": st.get("ExitCode"),
            "oom_killed": st.get("OOMKilled"),
            "restart_count": info.get("RestartCount", 0),
            "started_at": st.get("StartedAt"),
            "health": (st.get("Health") or {}).get("Status"),
            "networks": sorted(n.removeprefix(self.project + "_")
                               for n in (info["NetworkSettings"]["Networks"] or {})),
        }

    def logs(self, service: str, since_s: int = 300, tail: int = 200) -> str:
        r = self.docker("logs", "--since", f"{since_s}s", "--tail", str(tail), self.container(service))
        return r.out

    def stats(self) -> dict:
        r = self.docker("stats", "--no-stream", "--format", "{{json .}}", timeout=20)
        out = {}
        for line in r.out.splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = d["Name"].removeprefix(self.project + "-").removesuffix("-1")
            out[name] = {"cpu_pct": d["CPUPerc"], "mem": d["MemUsage"], "mem_pct": d["MemPerc"]}
        return out

    # ------------------------------------------------------------------ config + change log
    def _versions(self, service: str) -> list[Path]:
        vdir = self.runtime / "versions" / service
        return sorted(vdir.glob("v*-*"), key=lambda p: int(p.name[1:].split("-")[0]))

    def config_versions(self, service: str) -> list[int]:
        return [int(p.name[1:].split("-")[0]) for p in self._versions(service)]

    def read_config(self, service: str, version: int | None = None) -> str:
        if version is None:
            return (self.runtime / "config" / service / CONFIG_FILES[service]).read_text()
        for p in self._versions(service):
            if p.name.startswith(f"v{version}-"):
                return p.read_text()
        raise KeyError(f"{service} has no config version {version}")

    def current_version(self, service: str) -> int:
        live = self.read_config(service)
        for p in reversed(self._versions(service)):
            if p.read_text() == live:
                return int(p.name[1:].split("-")[0])
        return -1

    def record_change(self, service: str, summary: str, author: str, **extra) -> None:
        entry = {"ts": time.time(), "service": service, "summary": summary, "author": author, **extra}
        with self.changes_file.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def changes(self) -> list[dict]:
        if not self.changes_file.exists():
            return []
        return [json.loads(l) for l in self.changes_file.read_text().splitlines() if l.strip()]

    def deploy_config(self, service: str, content: str, summary: str, author: str) -> int:
        """Write a new config version and apply it (what a CD pipeline would do)."""
        fname = CONFIG_FILES[service]
        version = max(self.config_versions(service)) + 1
        (self.runtime / "versions" / service / f"v{version}-{fname}").write_text(content)
        (self.runtime / "config" / service / fname).write_text(content)
        self.record_change(service, summary, author, version=version)
        self.apply_config(service)
        return version

    def apply_config(self, service: str) -> ExecResult:
        if service == "gateway":
            return self.exec("gateway", ["nginx", "-s", "reload", "-c", "/etc/nginx/live/nginx.conf"])
        return self.compose("restart", service, timeout=60)

    def restore_config(self, service: str, version: int) -> None:
        content = self.read_config(service, version)
        (self.runtime / "config" / service / CONFIG_FILES[service]).write_text(content)
