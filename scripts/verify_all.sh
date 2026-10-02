#!/usr/bin/env bash
# Run every verification layer and fail closed.
#   scripts/verify_all.sh                         # any FAIL or BLOCKED layer fails the run
#   scripts/verify_all.sh --allow-blocked=live-parity,types
# A BLOCKED layer could not run here (missing live credentials, a policy-blocked tool, no browser). It is never counted
# as passing unless explicitly allowed by name, and the summary always shows it.
set -u
cd "$(dirname "$0")/.."
ALLOW=",${ALLOW_BLOCKED:-},"
for arg in "$@"; do
  case "$arg" in --allow-blocked=*) ALLOW=",${arg#*=},";; esac
done
if command -v uv >/dev/null 2>&1; then PY="uv run python"; else PY="python"; fi
mkdir -p artifacts/verify
NAMES=(); RESULTS=()

record() { NAMES+=("$1"); RESULTS+=("$2"); printf '%-16s %s\n' "$1" "$2"; }

layer() {  # layer <name> <command...>; BLOCKED when output names a policy block or a missing prerequisite
  local name=$1; shift
  local log="artifacts/verify/$name.log"
  if "$@" >"$log" 2>&1; then
    if grep -q "BLOCKED" "$log"; then record "$name" "BLOCKED (see $log)"; else record "$name" "PASS"; fi
  elif grep -qE "Application Control policy|BLOCKED:" "$log"; then
    record "$name" "BLOCKED (see $log)"
  else
    record "$name" "FAIL (see $log)"
  fi
}

layer spec          $PY scripts/verify_spec.py
layer secrets       $PY scripts/scan_secrets.py
layer contracts     $PY scripts/export_contracts.py --check
layer lint          $PY -m ruff check services tests scripts
layer types         $PY -m mypy --show-traceback
layer python-tests  $PY -m pytest tests -m "not live and not gemini_cli"
layer gemini-cli    $PY -m pytest tests -m gemini_cli -rs
layer evals-schema  $PY -m pytest tests/evals
if [ ! -d apps/web/node_modules ]; then (cd apps/web && npm ci --no-audit --no-fund) >artifacts/verify/web-install.log 2>&1; fi
layer web-types     npm --prefix apps/web run typecheck
layer web-unit      npm --prefix apps/web test
layer web-build     npm --prefix apps/web run build
layer e2e           npm --prefix apps/web run e2e
layer live-parity   $PY -m pytest tests/parity -m live -rs

# A pytest run where every test skipped as BLOCKED is reported as BLOCKED above; one that collected nothing is a failure.
status=0
echo
echo "Summary"
for i in "${!NAMES[@]}"; do
  name=${NAMES[$i]}; result=${RESULTS[$i]}
  case "$result" in
    PASS) ;;
    BLOCKED*) if [[ "$ALLOW" == *",$name,"* ]]; then echo "  $name: BLOCKED (explicitly allowed)"; else echo "  $name: BLOCKED (not allowed)"; status=1; fi ;;
    *) echo "  $name: $result"; status=1 ;;
  esac
done
[ $status -eq 0 ] && echo "verify_all: all required layers passed." || echo "verify_all: FAILED (fail-closed)."
exit $status
