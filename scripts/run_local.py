#!/usr/bin/env python3
"""Run the local FastAPI + Expo web profile without dotenv loading."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
CLIENT_DIR = ROOT / "apps" / "client"
LOCAL_DIR = ROOT / ".local"


def command_or_fail(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise SystemExit(f"required executable is missing: {name}")
    return resolved


def terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
    for process in processes:
        if process.poll() is None:
            process.wait()


def main() -> int:
    venv_python = API_DIR / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.is_file() else command_or_fail("python3.12")
    npm = command_or_fail("npm")

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    blob_root = LOCAL_DIR / "blobs"
    blob_root.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    forced_safe_values = {
        "APP_ENV": "development",
        "DEMO_MODE": "true",
        "PROVIDER_MODE": "fixture",
        "ALLOW_REMOTE_PROVIDER_CALLS": "false",
        "DATABASE_URL": f"sqlite:///{LOCAL_DIR / 'pocket_demo.db'}",
        "BLOB_ROOT": str(blob_root),
        "FIXTURE_ROOT": str(ROOT / "fixtures"),
        "INLINE_WORKER": "true",
        "COOKIE_SECURE": "false",
        "CORS_ORIGINS": "http://localhost:8081,http://127.0.0.1:8081",
        "SESSION_SECRET": "local-demo-session-secret-not-for-shared-deployments",
        "CSRF_SECRET": "local-demo-csrf-secret-not-for-shared-deployments",
        "TOKEN_SIGNING_SECRET": "local-demo-capability-secret-not-for-shared-deployments",
        "LOG_CONTENT_POLICY": "metadata-only",
        "EXPO_NO_DOTENV": "1",
        "EXPO_PUBLIC_API_URL": "http://localhost:8000",
        "EXPO_PUBLIC_DEMO_MODE": "true",
    }
    for secret_key in (
        "ASSEMBLYAI_API_KEY",
        "OPENAI_API_KEY",
        "PROVIDER_CALLBACK_SECRET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    ):
        environment.pop(secret_key, None)
    environment.update(forced_safe_values)

    # The Expo process receives only normal process settings and explicitly public
    # values. Server/provider credentials from the invoking shell stay API-only.
    client_process_keys = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "TERM",
        "CI",
        "NO_COLOR",
        "FORCE_COLOR",
    }
    client_environment = {
        key: value
        for key, value in environment.items()
        if key in client_process_keys
        or key.startswith("LC_")
        or key.startswith("npm_config_")
        or key.startswith("EXPO_PUBLIC_")
        or key == "EXPO_NO_DOTENV"
    }

    processes: list[subprocess.Popen[bytes]] = []
    shutting_down = False

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal shutting_down
        shutting_down = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        processes.append(
            subprocess.Popen(
                [
                    python,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--no-access-log",
                ],
                cwd=API_DIR,
                env=environment,
            )
        )
        processes.append(
            subprocess.Popen(
                [npm, "--prefix", str(CLIENT_DIR), "run", "web"],
                cwd=ROOT,
                env=client_environment,
            )
        )
        print("Pocket Demo starting: web http://localhost:8081, API http://localhost:8000")
        print("Fixture mode is active; no remote provider calls are allowed.")

        while not shutting_down:
            for process in processes:
                result = process.poll()
                if result is not None:
                    return result if result != 0 else 1
            time.sleep(0.2)
        return 0
    finally:
        terminate(processes)


if __name__ == "__main__":
    sys.exit(main())
