#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
api_dir="$repo_root/services/api"
client_dir="$repo_root/apps/client"
venv_dir="$api_dir/.venv"

export EXPO_NO_DOTENV=1

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "setup requires Python 3.12" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "setup requires Node.js/npm (Node 22 or newer)" >&2
  exit 1
fi

if [ ! -f "$api_dir/requirements.txt" ]; then
  echo "missing $api_dir/requirements.txt" >&2
  exit 1
fi

if [ ! -f "$client_dir/package-lock.json" ]; then
  echo "missing $client_dir/package-lock.json; commit a lockfile before setup" >&2
  exit 1
fi

python3.12 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --requirement "$api_dir/requirements.txt"
npm --prefix "$client_dir" ci

python3.12 "$repo_root/scripts/generate_fixture_wav.py" --check
python3.12 "$repo_root/scripts/verify_fixture_corpus.py"
python3.12 "$repo_root/scripts/verify_env_example.py"

echo "Pocket Demo dependencies and deterministic fixtures are ready."

