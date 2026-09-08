#!/usr/bin/env python3
"""Run a client/build command with checked-in public configuration only."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from configuration import PRIVATE_ENV_KEYS, load_public_configuration


ROOT = Path(__file__).resolve().parents[1]
PROCESS_KEYS = {
    "CI",
    "FORCE_COLOR",
    "HOME",
    "LANG",
    "LOGNAME",
    "NO_COLOR",
    "PATH",
    "SHELL",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USER",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-file",
        default=str(ROOT / "config" / "intelligent-audio-analysis.json"),
        help="public JSON configuration path",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise SystemExit("a command is required after --")

    environment = {
        key: value
        for key, value in os.environ.items()
        if key in PROCESS_KEYS
        or key.startswith("LC_")
        or key.startswith("npm_config_")
    }
    assert not set(environment) & PRIVATE_ENV_KEYS
    environment.update(load_public_configuration(args.config_file))
    environment["EXPO_NO_DOTENV"] = "1"
    os.execvpe(command[0], command, environment)
    return 127


if __name__ == "__main__":
    sys.exit(main())
