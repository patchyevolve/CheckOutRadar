#!/usr/bin/env python3
"""
Cross-platform Launcher & Pre-flight Validator for Checkout Radar.
Works seamlessly across Linux, macOS, and Windows.

Features:
- Docker daemon & Compose pre-flight checks with actionable diagnostics.
- Automatic .env preparation for credential-free, zero-dependency offline demo.
- Builds containers and orchestrates healthcheck readiness before opening browser.
- Automatically resolves dynamic or custom host port mappings.
- Clean error reporting with container logs if startup times out or fails.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# Paths relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def log(msg: str, level: str = "INFO"):
    prefixes = {
        "INFO": "[\033[94mINFO\033[0m]",
        "SUCCESS": "[\033[92mSUCCESS\033[0m]",
        "WARN": "[\033[93mWARN\033[0m]",
        "ERROR": "[\033[91mERROR\033[0m]",
    }
    # Windows cmd.exe color support fallback
    if os.name == "nt" and not os.environ.get("WT_SESSION") and not os.environ.get("ANSICON"):
        prefix = f"[{level}]"
    else:
        prefix = prefixes.get(level, f"[{level}]")
    print(f"{prefix} {msg}", flush=True)


def get_compose_cmd() -> list[str]:
    """Detect whether 'docker compose' or legacy 'docker-compose' is available."""
    try:
        res = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        if res.returncode == 0:
            return ["docker", "compose"]
    except Exception:
        pass

    if shutil.which("docker-compose"):
        return ["docker-compose"]

    log("Neither 'docker compose' nor 'docker-compose' found in PATH.", "ERROR")
    log("Please install Docker Desktop or the Docker Compose plugin:", "ERROR")
    log("  https://docs.docker.com/compose/install/", "ERROR")
    sys.exit(1)


def check_docker_daemon():
    """Verify Docker CLI and daemon responsiveness."""
    if not shutil.which("docker"):
        log("Docker is not installed or not in PATH.", "ERROR")
        log("Please install Docker Desktop: https://www.docker.com/products/docker-desktop/", "ERROR")
        sys.exit(1)

    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            log("Docker daemon is not running or current user lacks docker permissions.", "ERROR")
            if sys.platform == "darwin":
                log("On macOS: Launch Docker Desktop from Applications.", "ERROR")
            elif sys.platform.startswith("linux"):
                log("On Linux: Run 'sudo systemctl start docker' or add your user to the 'docker' group.", "ERROR")
            elif sys.platform == "win32":
                log("On Windows: Start Docker Desktop from the Start Menu.", "ERROR")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        log("Docker daemon check timed out after 10 seconds. Is Docker Desktop responsive?", "ERROR")
        sys.exit(1)
    except Exception as e:
        log(f"Failed to communicate with Docker daemon: {e}", "ERROR")
        sys.exit(1)


def ensure_env_file():
    """Ensure .env exists; if not, clone from .env.example with offline mock mode."""
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            log("No .env found. Initializing default .env from .env.example (Mock Mode enabled)...", "INFO")
            shutil.copy(ENV_EXAMPLE, ENV_FILE)
            log("Created .env with zero-dependency offline mock defaults.", "SUCCESS")
        else:
            log(".env.example missing; creating minimal .env...", "WARN")
            with open(ENV_FILE, "w", encoding="utf-8") as f:
                f.write("MOCK_TINYFISH=true\n")
                f.write("MAX_RUNS_PER_AUDIT=12\n")


def get_mapped_port(compose_cmd: list[str], service: str, container_port: int, default_port: int) -> tuple[str, int]:
    """Retrieve the host port mapping for a compose service, falling back to default."""
    try:
        res = subprocess.run(
            compose_cmd + ["port", service, str(container_port)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            # Format: 127.0.0.1:36063 or 0.0.0.0:8000
            output = res.stdout.strip().split("\n")[0]
            parts = output.split(":")
            if len(parts) >= 2:
                host = parts[0] if parts[0] not in ("0.0.0.0", "") else "127.0.0.1"
                port = int(parts[-1])
                return host, port
    except Exception:
        pass
    return "127.0.0.1", default_port


def wait_for_health(host: str, port: int, timeout_sec: int = 75, compose_cmd: list[str] = None) -> bool:
    """Poll API /health endpoint until it reports healthy or times out."""
    health_url = f"http://{host}:{port}/health"
    log(f"Waiting for services to become healthy at {health_url}...", "INFO")
    start_time = time.time()
    
    while time.time() - start_time < timeout_sec:
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "CheckoutRadarLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    log("Checkout Radar API reports healthy!", "SUCCESS")
                    return True
        except (urllib.error.URLError, ConnectionResetError, OSError):
            pass
        time.sleep(1.5)
        # Check if containers exited prematurely
        if compose_cmd:
            ps_res = subprocess.run(compose_cmd + ["ps", "-a"], cwd=str(REPO_ROOT), capture_output=True, text=True)
            if "Exited" in ps_res.stdout or "Dead" in ps_res.stdout:
                log("One or more containers exited unexpectedly during startup!", "ERROR")
                print(ps_res.stdout)
                break

    return False


def dump_logs(compose_cmd: list[str]):
    """Dump recent container logs for rapid troubleshooting."""
    log("Fetching recent container logs for diagnostic troubleshooting...", "WARN")
    try:
        subprocess.run(compose_cmd + ["logs", "--tail", "40"], cwd=str(REPO_ROOT))
    except Exception as e:
        log(f"Failed to fetch logs: {e}", "WARN")


def open_browser(url: str):
    """Safely open web browser without crashing if in headless or SSH environment."""
    log(f"Launching web browser for {url}...", "INFO")
    try:
        # Check if GUI environment exists
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            log("Headless Linux environment detected (no DISPLAY). Skipping browser launch.", "INFO")
            return
        webbrowser.open(url, new=2)
    except Exception as e:
        log(f"Could not open browser automatically: {e}", "WARN")


def run_down(compose_cmd: list[str]):
    """Stop and tear down Checkout Radar containers."""
    log("Stopping Checkout Radar services...", "INFO")
    subprocess.run(compose_cmd + ["down"], cwd=str(REPO_ROOT))
    log("Checkout Radar stopped cleanly.", "SUCCESS")


def main():
    parser = argparse.ArgumentParser(description="Checkout Radar One-Command Launcher")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically launch web browser")
    parser.add_argument("--down", action="store_true", help="Stop and tear down running containers")
    parser.add_argument("--status", action="store_true", help="Check status of running containers")
    parser.add_argument("--logs", action="store_true", help="View container logs")
    args = parser.parse_args()

    compose_cmd = get_compose_cmd()

    if args.down:
        run_down(compose_cmd)
        return

    if args.logs:
        dump_logs(compose_cmd)
        return

    if args.status:
        subprocess.run(compose_cmd + ["ps"], cwd=str(REPO_ROOT))
        return

    # Pre-flight checks
    log("Starting pre-flight system diagnostics...", "INFO")
    check_docker_daemon()
    ensure_env_file()

    # Build and start services
    log("Building and orchestrating containers with Docker Compose...", "INFO")
    build_res = subprocess.run(compose_cmd + ["up", "--build", "-d"], cwd=str(REPO_ROOT))
    if build_res.returncode != 0:
        log("Docker Compose build or startup failed. See error output above.", "ERROR")
        dump_logs(compose_cmd)
        sys.exit(1)

    # Resolve ports
    api_host, api_port = get_mapped_port(compose_cmd, "api", 8000, 8000)
    harness_host, harness_port = get_mapped_port(compose_cmd, "harness", 8001, 8001)

    # Wait for health
    healthy = wait_for_health(api_host, api_port, timeout_sec=75, compose_cmd=compose_cmd)
    if not healthy:
        log("Service failed to report healthy within timeout window.", "ERROR")
        dump_logs(compose_cmd)
        log("Run './start.sh --logs' or 'docker compose logs' for more details.", "ERROR")
        sys.exit(1)

    dashboard_url = f"http://{api_host}:{api_port}"
    harness_url = f"http://{harness_host}:{harness_port}"
    docs_url = f"http://{api_host}:{api_port}/docs"

    print("\n" + "=" * 70)
    print(" 📡 CHECKOUT RADAR IS READY")
    print("=" * 70)
    print(f"  • Auditor Dashboard:       {dashboard_url}")
    print(f"  • Demo Merchant Harness:   {harness_url}")
    print(f"  • Interactive API Docs:    {docs_url}")
    print("=" * 70)
    print("  Mode: Deterministic Offline Mock (Zero external API dependencies)")
    print("  To stop services: run './stop.sh' or 'docker compose down'\n")

    if not args.no_browser:
        open_browser(dashboard_url)


if __name__ == "__main__":
    main()
