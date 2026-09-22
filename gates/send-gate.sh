#!/usr/bin/env bash
# gates/send-gate.sh — pre-send gate seam for a batch driver's send path.
#
# A batcher calls this immediately before every model send, binding the
# folder the send is about to touch:
#
#   ZFT_GATE_CMD='./gates/driver-gate.sh {folder}' \
#   ZFT_GATE_HOOK=shadow \
#   gates/send-gate.sh "$REPO_DIR" || exit 1
#
# Flag layer (the RUNBOOK batch-driver contract, env form so any shell or
# subprocess dispatcher can set it):
#   ZFT_GATE_CMD          {folder}-template of the gate command
#   ZFT_GATE_HOOK         off (default) | shadow | enforce
#   ZFT_SEND_GATE_LOG     JSONL verdict log
#                                (default <folder>/.traceagent/send-gate/log.jsonl)
#   ZFT_SEND_GATE_TIMEOUT kill window in seconds (default 120, the
#                                documented driver kill)
#
# Modes:
#   off      — seam does nothing, exit 0, zero overhead. ROLLBACK = this one
#              flag (unset or `off`); no other config changes.
#   shadow   — run the gate, append one JSONL verdict, ALWAYS exit 0: shadow
#              records would-blocks, it never blocks a send.
#   enforce  — a gate red blocks the send (exit 1). A gate that cannot
#              answer (misconfigured template, spawn failure, budget kill)
#              is a transport error and fails OPEN like the documented driver
#              contract — loudly, in the log — never silently green.
#
# Verdict vocabulary: allow (gate exit 0), would-block (gate answered red),
# gate-unavailable (the gate could not answer). One line per send:
#   {"ts":..,"mode":..,"folder":..,"gate_cmd":..,"decision":..,
#    "gate_exit":..|null,"elapsed_ms":..,"reason":..|"","output":".."}
# The gate's bounded output rides along capped at 1900 chars (the driver
# sink is ~2000); control characters are flattened so the line stays 1 JSONL.
set -u

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
  echo "send-gate: usage: send-gate.sh <folder> (batcher binds the send's folder)"
  exit 2
fi
if [ ! -d "$1" ]; then
  echo "send-gate: not a folder: $1"
  exit 1
fi
FOLDER=$(cd "$1" && pwd) || { echo "send-gate: cannot resolve folder: $1"; exit 1; }

MODE=${ZFT_GATE_HOOK:-off}
if [ "$MODE" = "off" ] || [ -z "${ZFT_GATE_CMD:-}" ]; then
  # rollback path: one flag off (or the gate cmd never configured) — a no-op
  exit 0
fi
if [ "$MODE" != "shadow" ] && [ "$MODE" != "enforce" ]; then
  echo "send-gate: ZFT_GATE_HOOK must be off|shadow|enforce, got '$MODE'"
  exit 2
fi

LOG=${ZFT_SEND_GATE_LOG:-"$FOLDER/.traceagent/send-gate/log.jsonl"}
KILL_S=${ZFT_SEND_GATE_TIMEOUT:-120}
GATE_TEMPLATE=$ZFT_GATE_CMD

# flatten control chars, escape for JSON, cap to the driver sink budget
_flatten() {
  printf '%s' "$1" | tr '\000-\010\013\014\016-\037\t\n\r' '                        ' \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

decision=""
reason=""
gate_exit=null
T0=$(date +%s%3N 2>/dev/null || echo "$(date +%s)000")

case "$GATE_TEMPLATE" in
  *"{folder}"*)
    CMD=${GATE_TEMPLATE//\{folder\}/$FOLDER}
    if OUT=$(timeout -k 5 "$KILL_S" bash -c "$CMD" 2>&1); then
      decision="allow"; gate_exit=0
    else
      RC=$?
      if [ "$RC" -eq 124 ] || [ "$RC" -eq 137 ]; then
        decision="gate-unavailable"; reason="budget kill at ${KILL_S}s"
      elif [ "$RC" -eq 127 ]; then
        decision="gate-unavailable"; reason="gate command not found"
      else
        decision="would-block"; gate_exit=$RC
      fi
    fi
    ;;
  *)
    decision="gate-unavailable"; reason="template has no {folder} placeholder"
    OUT=""
    ;;
esac

T1=$(date +%s%3N 2>/dev/null || echo "$(date +%s)000")
OUT=${OUT:-""}
[ "${#OUT}" -gt 1900 ] && OUT="${OUT:0:1900}"
OUT=$(_flatten "$OUT")
REASON=$(_flatten "$reason")

LOGDIR=$(dirname "$LOG")
if mkdir -p "$LOGDIR" 2>/dev/null && \
   printf '{"ts":"%s","mode":"%s","folder":"%s","gate_cmd":"%s","decision":"%s","gate_exit":%s,"elapsed_ms":%s,"reason":"%s","output":"%s"}\n' \
     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$MODE" "$(_flatten "$FOLDER")" \
     "$(_flatten "$GATE_TEMPLATE")" "$decision" "$gate_exit" "$((T1 - T0))" \
     "$REASON" "$OUT" >> "$LOG" 2>/dev/null; then
  :
else
  echo "send-gate: could not write verdict log $LOG (send proceeds; decision was $decision)" >&2
fi

if [ "$MODE" = "enforce" ] && [ "$decision" = "would-block" ]; then
  printf 'send-gate: GATE RED blocks the send — %s\n' "$OUT"
  exit 1
fi
exit 0
