#!/usr/bin/env bash
# gates/driver-gate.sh — per-task acceptance gate for the ZCode batch driver.
#
# Driver contract (--gate-cmd '<this script> {folder}' with --gate-hook shadow|enforce):
#   exit 0 pass, nonzero reject; stdout+stderr land in a ~2000-char sink; the
#   driver kills at 120s and its transport errors fail OPEN. This script
#   therefore answers well inside the kill window and fails CLOSED on its own
#   terms (evidence missing, budget blown, tooling absent => reject, never a
#   vacuous pass).
# Read-only: the governed folder is never written — no ledger, no verdict
# cache, no gherkin render, no bytecode; hypothesis's example DB is pointed at
# a self-removing temp dir by the Python seam. Verdict logging is the driver's
# job (shadow mode).
set -u

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
  echo "driver-gate: usage: driver-gate.sh <folder> (driver binds {folder})"
  exit 2
fi
if [ ! -d "$1" ]; then
  echo "driver-gate: not a folder: $1"
  exit 1
fi
FOLDER=$(cd "$1" && pwd) || { echo "driver-gate: cannot resolve folder: $1"; exit 1; }

# subprocess hygiene mirrors gates.sandbox.gate_env: parent pytest/coverage
# channels must not steer (or write into) the verdict — and even the
# interpreter probe below must not drop bytecode into the package tree
export PYTHONDONTWRITEBYTECODE=1
unset PYTEST_ADDOPTS PYTEST_PLUGINS COVERAGE_FILE COVERAGE_PROCESS_START

# locate an interpreter that can import traceagent (explicit override, the
# checkout's venv, then PATH)
PY=${TRACEAGENT_PYTHON:-}
if [ -z "$PY" ]; then
  HERE=$(cd "$(dirname "$0")" && pwd)
  for cand in "$HERE/../.venv/bin/python" "$HERE/../../.venv/bin/python" python3; do
    if command -v "$cand" >/dev/null 2>&1 \
        && "$cand" -c "import traceagent" >/dev/null 2>&1; then
      PY=$cand
      break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "driver-gate: no interpreter with traceagent importable (set TRACEAGENT_PYTHON)"
  exit 1
fi

# answer before the driver's 120s kill: an overrun is a rejection, because the
# driver-side kill/transport path would fail OPEN
BUDGET=${DRIVER_GATE_BUDGET_S:-100}
if command -v timeout >/dev/null 2>&1; then
  OUT=$(timeout -k 5 "$BUDGET" "$PY" -m traceagent.gates.driver_gate "$FOLDER" 2>&1)
else
  OUT=$("$PY" -m traceagent.gates.driver_gate "$FOLDER" 2>&1)
fi
RC=$?
if [ "$RC" -eq 124 ] || [ "$RC" -eq 137 ]; then
  echo "driver-gate: budget ${BUDGET}s exceeded — rejected (kill would fail open; gate fails closed)"
  exit 1
fi

# the Python seam already fits the budget; this cap is the backstop
if [ "${#OUT}" -gt 1900 ]; then
  OUT="${OUT:0:1740} ...[truncated]"
fi
printf '%s\n' "$OUT"
exit $RC
