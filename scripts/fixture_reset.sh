#!/usr/bin/env bash
# Reset local development state: regenerate SYNTHETIC fixtures, transcripts and goldens, and wipe the local dev database
# and per-user homes under var/ (never touches a pilot data directory outside the repo).
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then PY="uv run python"; else PY="python"; fi
$PY scripts/generate_fixtures.py
$PY scripts/write_transcripts.py
$PY scripts/write_goldens.py
$PY scripts/export_contracts.py
if [ -d var ]; then
  rm -rf var/wizard.sqlite3 var/wizard.sqlite3-wal var/wizard.sqlite3-shm var/users
  echo "Removed local dev database and user homes under var/ (session key kept)."
fi
$PY scripts/verify_spec.py
