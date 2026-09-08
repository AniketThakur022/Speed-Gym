"""The production compose files must not expose a data service.

These render the REAL config with `docker compose config` rather than reading
YAML, because the defect they guard against is a merge-semantics one: compose
MERGES port sequences across files, so `ports: []` in an override looks like it
unpublishes a port while the base file's 0.0.0.0 binding quietly survives. Only
the rendered result tells the truth.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
DOCKER_BIN_HINT = "/Applications/Docker.app/Contents/Resources/bin"
DATA_SERVICES = {"postgres", "neo4j", "redis", "pgbouncer"}
PUBLIC_HOST_IPS = {None, "", "0.0.0.0", "::"}

# Interpolation values only; every one is a required `${VAR:?}` in the prod file.
FAKE_SECRETS = {
    "JWT_SECRET": "t", "OFFLINE_TOKEN_SECRET": "t", "INTERNAL_API_KEY": "t",
    "POSTGRES_PASSWORD": "t", "NEO4J_PASSWORD": "t", "TRUSTED_PROXIES": "10.0.0.2",
}


def _docker() -> str | None:
    found = shutil.which("docker") or shutil.which("docker", path=DOCKER_BIN_HINT)
    return found


pytestmark = pytest.mark.skipif(_docker() is None, reason="docker CLI not available")


def _render(extra_files: list[str], profile: bool, extra_env: dict[str, str] | None = None) -> dict:
    """`docker compose config` for the given overlay. Creates an EMPTY .env only
    if the repo has none — the prod file declares `env_file: .env`, and a real
    one must never be touched."""
    env = {**os.environ, **FAKE_SECRETS, **(extra_env or {})}
    env["PATH"] = f"{DOCKER_BIN_HINT}:{env.get('PATH', '')}"
    dotenv = REPO / ".env"
    created = False
    if not dotenv.exists():
        dotenv.write_text("")
        created = True
    try:
        cmd = [_docker(), "compose", "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml"]
        for f in extra_files:
            cmd += ["-f", f]
        if profile:
            cmd += ["--profile", "app"]
        cmd.append("config")
        out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
        assert out.returncode == 0, out.stderr[-2000:]
        return yaml.safe_load(out.stdout)
    finally:
        if created:
            dotenv.unlink(missing_ok=True)


def _published(config: dict) -> list[tuple[str, object, object]]:
    rows = []
    for name, svc in (config.get("services") or {}).items():
        for port in svc.get("ports") or []:
            rows.append((name, port.get("host_ip"), str(port.get("published"))))
    return rows


def test_single_host_prod_publishes_no_data_service():
    rows = _published(_render([], profile=True))
    exposed = [r for r in rows if r[0] in DATA_SERVICES]
    assert exposed == [], f"data services must not be published in prod: {exposed}"


def test_single_host_prod_keeps_the_app_behind_the_tls_proxy():
    rows = _published(_render([], profile=True))
    for name, host_ip, published in rows:
        assert host_ip not in PUBLIC_HOST_IPS, (
            f"{name}:{published} is published on all interfaces; the TLS proxy must be "
            "the only public entrance on Droplet A"
        )


def test_data_droplet_binds_only_to_the_vpc_address():
    config = _render(["docker-compose.data.yml"], profile=False,
                     extra_env={"DATA_BIND_IP": "10.0.0.3"})
    rows = _published(config)
    assert rows, "the data droplet must publish something for Droplet A to reach"
    for name, host_ip, published in rows:
        assert host_ip == "10.0.0.3", f"{name}:{published} bound to {host_ip!r}, not the VPC address"
    # Neo4j's HTTP browser is never published; bolt is all the app needs.
    assert ("neo4j", "10.0.0.3", "7474") not in rows
    assert ("neo4j", "10.0.0.3", "7687") in rows


def test_data_droplet_refuses_to_start_without_an_explicit_vpc_address():
    """No default: an unset DATA_BIND_IP must fail, never bind everywhere."""
    env = {**os.environ, **FAKE_SECRETS, "PATH": f"{DOCKER_BIN_HINT}:{os.environ.get('PATH','')}"}
    env.pop("DATA_BIND_IP", None)
    dotenv = REPO / ".env"
    created = False
    if not dotenv.exists():
        dotenv.write_text("")
        created = True
    try:
        out = subprocess.run(
            [_docker(), "compose", "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
             "-f", "docker-compose.data.yml", "config"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=180,
        )
        assert out.returncode != 0
        assert "DATA_BIND_IP" in out.stderr
    finally:
        if created:
            dotenv.unlink(missing_ok=True)


def test_documented_memory_ceilings_are_respected():
    """Architecture §3.2: Neo4j heap <=1G and page cache <=1G, Postgres
    shared_buffers <=1G, Redis maxmemory <=512M."""
    config = _render([], profile=True)
    services = config["services"]

    neo = services["neo4j"]["environment"]
    assert neo["NEO4J_server_memory_heap_max__size"] in ("1G", "1g")
    assert neo["NEO4J_server_memory_pagecache_size"].lower().rstrip("m") == "512"

    pg_cmd = " ".join(str(a) for a in services["postgres"]["command"])
    assert "shared_buffers=640MB" in pg_cmd

    redis_cmd = " ".join(str(a) for a in services["redis"]["command"])
    assert "512mb" in redis_cmd and "allkeys-lru" in redis_cmd

    # A "4 GB" droplet is 4096 MiB; Ubuntu + dockerd need ~400 MiB, so the
    # container budget is ~3700 MiB (docs/backend/DEPLOYMENT.md).
    MIB = 1024 * 1024
    total_mib = sum(int(services[s]["mem_limit"]) for s in ("postgres", "neo4j", "redis")) // MIB
    assert total_mib <= 3700, f"data tier limits total {total_mib} MiB; budget is 3700 MiB on a 4 GiB droplet"
