#!/usr/bin/env bash
#
# Codex worker for Slack/Gmail queue items explicitly routed to Codex.
#
# Send from Slack:
#   check https://... worker:codex
#   apply https://... worker:codex
#   find Product Designer jobs worker:codex
#
# Commands:
#   ./scripts/codex_drain.sh once
#   ./scripts/codex_drain.sh loop
#   ./scripts/codex_drain.sh status
#
# This intentionally does not claim unlabeled or worker:claude items.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_CODEX_BIN="$HOME/.vscode/extensions/openai.chatgpt-26.727.40816-darwin-arm64/bin/macos-aarch64/codex"
CODEX_BIN="${CODEX_BIN:-$(command -v codex 2>/dev/null || true)}"
if [ -z "$CODEX_BIN" ] && [ -x "$DEFAULT_CODEX_BIN" ]; then
  CODEX_BIN="$DEFAULT_CODEX_BIN"
fi
LOG_DIR="$HOME/.job-agent/logs"
LOG_FILE="$LOG_DIR/codex-drain.log"
LAST_MESSAGE="$LOG_DIR/codex-drain-last-message.md"
INTERVAL="${JOB_AGENT_CODEX_DRAIN_INTERVAL:-300}"
# Queue-routed Codex jobs need local Chrome/CDP access for live ATS forms.
# The prompt still enforces hard rules: no credentials, CAPTCHA, account
# creation, government/payment data, or final submit without confirmation.
SANDBOX="${JOB_AGENT_CODEX_SANDBOX:-danger-full-access}"
DEFAULT_EXTRA_WRITE_DIRS="$HOME/.job-agent:$HOME/Library/Application Support/Google/Chrome/Crashpad"
EXTRA_WRITE_DIRS="${JOB_AGENT_CODEX_EXTRA_WRITE_DIRS:-${JOB_AGENT_CODEX_EXTRA_WRITE_DIR:-$DEFAULT_EXTRA_WRITE_DIRS}}"

mkdir -p "$LOG_DIR"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

queue_json() {
  python3 "$REPO_ROOT/scripts/command_queue.py" "$@"
}

codex_pending_count() {
  queue_json list --status pending --assigned-worker codex 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("count",0))' 2>/dev/null || echo 0
}

claim_one() {
  queue_json claim --worker codex-session --worker-type codex
}

run_codex_for_item() {
  local item_json id command prompt_file extra_args=()
  item_json="$1"
  id="$(ITEM_JSON="$item_json" python3 -c 'import json,os; print(json.loads(os.environ["ITEM_JSON"])["id"])')"
  command="$(ITEM_JSON="$item_json" python3 -c 'import json,os; print(json.loads(os.environ["ITEM_JSON"])["command"])')"
  prompt_file="$(mktemp "${TMPDIR:-/tmp}/job-agent-codex-prompt.XXXXXX")"

  cat >"$prompt_file" <<PROMPT
You are the Codex away-mode drain worker for the user's job-agent system.

Queue item:
- id: ${id}
- command: ${command}

Rules:
- Work from this repo only: ${REPO_ROOT}
- Read AGENTS.md and context/hard-rules.md before touching any live job application.
- Execute exactly the queued command. Do not process any other queue item.
- If the command is check/find/search, report verified links, ATS/match score, best resume variant, and source status as the repo rules require.
- If the command is apply/force tailor/continue/submit, follow the repo workflow and stop at hard-rule blockers/final-submit boundary.
- Never create accounts. Never type credentials, passwords, OTPs, CAPTCHA, SSN, payment info, or magic links.
- Never submit an application unless the queued command is an explicit submit for that named prepared job and the hard rules are satisfied.
- Use the existing scripts and the Chrome bridge; do not invent a second queue.
- At the end, mark this queue item complete or failed with scripts/command_queue.py.
  - Success: python3 scripts/command_queue.py complete --id ${id} --result "short outcome"
  - Blocked/failure: python3 scripts/command_queue.py fail --id ${id} --result "short blocker"

Be concise in final output. Include the queue id and status.
PROMPT

  log "running Codex for queue #${id}: ${command}"
  IFS=: read -r -a extra_dirs <<<"$EXTRA_WRITE_DIRS"
  for dir in "${extra_dirs[@]}"; do
    [ -n "$dir" ] && extra_args+=(--add-dir "$dir")
  done
  "$CODEX_BIN" \
    --ask-for-approval never \
    --search \
    exec \
    --cd "$REPO_ROOT" \
    "${extra_args[@]}" \
    --skip-git-repo-check \
    --sandbox "$SANDBOX" \
    --output-last-message "$LAST_MESSAGE" \
    - <"$prompt_file" >>"$LOG_FILE" 2>&1
  local status=$?
  rm -f "$prompt_file"
  if [ "$status" -ne 0 ]; then
    log "Codex exited ${status} for queue #${id}; releasing item"
    queue_json release --id "$id" >/dev/null 2>&1 || true
    return "$status"
  fi
  if [ -s "$LAST_MESSAGE" ]; then
    queue_json attach-result --id "$id" --result-file "$LAST_MESSAGE" --renotify >/dev/null 2>&1 \
      || log "could not attach final Codex message for queue #${id}"
  fi
  log "Codex finished queue #${id}"
}

run_once() {
  if [ -z "$CODEX_BIN" ] || [ ! -x "$CODEX_BIN" ]; then
    log "codex CLI not found"
    return 2
  fi

  queue_json release-stale --older-than-minutes 30 >/dev/null 2>&1 || true

  if ! "$REPO_ROOT/scripts/chrome_bridge.sh" status >/dev/null 2>&1; then
    log "chrome bridge down - starting it"
    "$REPO_ROOT/scripts/chrome_bridge.sh" start >/dev/null 2>&1 || log "chrome bridge start failed"
  fi
  if ! node "$REPO_ROOT/scripts/chrome_tabs.mjs" list >/dev/null 2>&1; then
    log "chrome CDP unreachable - not claiming Codex items"
    return 0
  fi

  local pending claim_json claimed item_json
  pending="$(codex_pending_count)"
  if [ "${pending:-0}" -eq 0 ]; then
    log "idle: no worker:codex items"
    return 0
  fi

  claim_json="$(claim_one)"
  claimed="$(CLAIM_JSON="$claim_json" python3 -c 'import json,os; print("true" if json.loads(os.environ["CLAIM_JSON"]).get("claimed") else "false")')"
  if [ "$claimed" != "true" ]; then
    log "nothing claimed"
    return 0
  fi
  item_json="$(CLAIM_JSON="$claim_json" python3 -c 'import json,os; print(json.dumps(json.loads(os.environ["CLAIM_JSON"])["item"]))')"
  run_codex_for_item "$item_json"
}

case "${1:-status}" in
  once)
    run_once
    ;;
  loop)
    log "Codex drain loop started; interval ${INTERVAL}s; sandbox ${SANDBOX}"
    while true; do
      run_once || true
      sleep "$INTERVAL"
    done
    ;;
  status)
    echo "codex binary: ${CODEX_BIN:-not found}"
    echo "codex pending: $(codex_pending_count)"
    echo "log: $LOG_FILE"
    if [ -f "$LOG_FILE" ]; then
      echo "--- last 10 log lines ---"
      tail -10 "$LOG_FILE"
    fi
    ;;
  *)
    echo "Usage: $0 {once|loop|status}" >&2
    exit 2
    ;;
esac
