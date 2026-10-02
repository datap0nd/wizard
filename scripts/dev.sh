#!/usr/bin/env bash
# Start Wizard for local development: API on :8770 (settings from .env) and the Vite dev server on :5173.
#   scripts/dev.sh            # API + hot-reloading web app
#   scripts/dev.sh --api-only # API serving the built web app from apps/web/dist
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example (replay mode)."; }
uv sync >/dev/null
[ -d apps/web/node_modules ] || npm --prefix apps/web ci --no-audit --no-fund
if [ "${1:-}" = "--api-only" ]; then
  [ -f apps/web/dist/index.html ] || npm --prefix apps/web run build
  exec uv run python -m wizard_api
fi
uv run python -m wizard_api & API=$!
trap 'kill $API 2>/dev/null' EXIT
npm --prefix apps/web run dev
