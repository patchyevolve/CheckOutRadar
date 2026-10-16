"""
Regression tests for Phase 2: One-Command Startup & Fresh Clone Portability.
Tests mock-by-default behavior, pre-flight environment cloning, compose syntax,
and launcher script permissions.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.worker.job_runner import get_adapter
from app.tinyfish.mock_client import MockTinyFishClient


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IS_HOST_ENV = (REPO_ROOT / "start.sh").exists()


def test_default_mock_mode_when_env_unconfigured(monkeypatch):
    """When no MOCK_TINYFISH or TINYFISH_API_KEY is provided, job_runner safely defaults to MockTinyFishClient."""
    monkeypatch.delenv("MOCK_TINYFISH", raising=False)
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    adapter = get_adapter()
    assert isinstance(adapter, MockTinyFishClient), "Expected MockTinyFishClient by default"


def test_health_endpoint_reports_mock_mode_default(monkeypatch):
    """Health check reports healthy and mock_mode True when MOCK_TINYFISH is unset."""
    monkeypatch.delenv("MOCK_TINYFISH", raising=False)
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["mock_mode"] is True
    assert data["has_tinyfish_key"] is False


@pytest.mark.skipif(not IS_HOST_ENV, reason="Host launcher scripts are evaluated in host environment")
def test_launcher_env_file_generation(tmp_path):
    """Launcher ensures a valid .env with mock mode is created if .env is missing."""
    import importlib.util
    launcher_path = REPO_ROOT / "scripts" / "launcher.py"
    spec = importlib.util.spec_from_file_location("launcher", launcher_path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    test_env = tmp_path / ".env"
    test_example = tmp_path / ".env.example"
    test_example.write_text("MOCK_TINYFISH=true\nTINYFISH_API_KEY=\n", encoding="utf-8")

    # Patch paths
    launcher.ENV_FILE = test_env
    launcher.ENV_EXAMPLE = test_example

    assert not test_env.exists()
    launcher.ensure_env_file()
    assert test_env.exists()
    content = test_env.read_text(encoding="utf-8")
    assert "MOCK_TINYFISH=true" in content


@pytest.mark.skipif(not IS_HOST_ENV, reason="Host launcher scripts are evaluated in host environment")
def test_startup_scripts_exist_and_executable():
    """Verify all platform startup scripts exist and POSIX scripts have execute bits."""
    scripts = ["start.sh", "stop.sh", "start.cmd", "stop.cmd", "scripts/launcher.py"]
    for s in scripts:
        p = REPO_ROOT / s
        assert p.exists(), f"Missing required launcher script: {s}"
        assert p.stat().st_size > 50, f"Script {s} appears empty or truncated"

        if s.endswith(".sh") or s.endswith(".py"):
            mode = p.stat().st_mode
            assert bool(mode & stat.S_IXUSR), f"Script {s} must have executable permissions"


@pytest.mark.skipif(not IS_HOST_ENV, reason="Host docker compose CLI is evaluated in host environment")
def test_docker_compose_syntax_and_healthchecks():
    """Verify docker-compose.yml parses cleanly with docker compose config."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    assert compose_path.exists()
    
    # Run docker compose config on the file directly
    res = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "config"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"docker compose config failed: {res.stderr}"
    config_text = res.stdout
    assert "healthcheck" in config_text, "Compose configuration must declare healthchecks"
    assert "harness" in config_text
    assert "api" in config_text
    assert "worker" in config_text


def test_demo_seed_initialization(tmp_path, monkeypatch):
    """Verify that seed_demo_data_if_empty seeds baseline demo fixtures into an empty database."""
    from app.db import connection

    test_db = tmp_path / "test_fresh_clone.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))

    connection.init_db(seed_demo=False)
    conn = connection.get_connection()
    try:
        # Initially empty
        count = conn.execute("SELECT COUNT(*) FROM audits").fetchone()[0]
        assert count == 0

        # Seed baseline demo fixtures
        connection.seed_demo_data_if_empty(conn)

        count_after = conn.execute("SELECT COUNT(*) FROM audits").fetchone()[0]
        assert count_after == 3

        # Verify specific demo audit IDs
        audit_ids = [r[0] for r in conn.execute("SELECT id FROM audits").fetchall()]
        assert "aud_b29153cee0b1" in audit_ids  # Headphone Zone live
        assert "aud_4d476bc71e63" in audit_ids  # Late fee drip
        assert "aud_f0946ab48e50" in audit_ids  # Inconclusive default

        # Idempotence: second call should not duplicate or error
        connection.seed_demo_data_if_empty(conn)
        count_idempotent = conn.execute("SELECT COUNT(*) FROM audits").fetchone()[0]
        assert count_idempotent == 3
    finally:
        conn.close()

