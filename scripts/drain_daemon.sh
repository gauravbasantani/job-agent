#!/usr/bin/env bash
#
# Background worker: finds JOBAGENT emails and runs them, with no terminal
# open and no Claude session alive.
#
#   ./scripts/drain_daemon.sh arm      # keep the Mac awake + install the timer
#   ./scripts/drain_daemon.sh disarm   # stop the timer and let the Mac sleep
#   ./scripts/drain_daemon.sh once     # run a single cycle now (for testing)
#   ./scripts/drain_daemon.sh status   # is it armed? what happened last?
#
# Cost control: most polls find an empty inbox, and spawning a full agent
# session for nothing is wasteful. So each cycle runs a cheap probe first —
# one small headless call that just counts unprocessed mail — and only starts
# the real (expensive) drain when there is something to do.
#
# The probe relies on Gmail labels doubling as the processed-marker: the query
# excludes anything already labelled, so it naturally returns only new mail.
#
# Hard limit: launchd does not fire while the Mac is asleep, and Chrome cannot
# run either. `arm` starts caffeinate for exactly this reason. A closed laptop
# in a bag does nothing, and no configuration changes that.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
LABEL="com.the user.jobagent.drain"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
INTERVAL="${JOB_AGENT_DRAIN_INTERVAL:-1200}"   # seconds; 20 min default
LOG_DIR="$HOME/.job-agent/logs"
LOG_FILE="$LOG_DIR/drain.log"
CAFFEINATE_PID="$HOME/.job-agent/caffeinate.pid"
CLAUDE_PERMISSION_MODE="${JOB_AGENT_CLAUDE_PERMISSION_MODE:-acceptEdits}"
CLAUDE_BROWSER_DIRS=(
  "$HOME/.job-agent"
  "$HOME/Library/Application Support/Google/Chrome/Crashpad"
)

GMAIL_TOOLS="mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Gmail__label_message mcp__claude_ai_Gmail__unlabel_message mcp__claude_ai_Gmail__list_labels"

mkdir -p "$LOG_DIR" "$HOME/.job-agent"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE"; }

pending_count() {
  python3 "$REPO_ROOT/scripts/command_queue.py" list --status pending 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("count",0))' 2>/dev/null || echo 0
}

# Cheap probe: count JOBAGENT mail that carries no JobAgent/* label yet.
#
# The reply must be a bare integer and nothing else. Scraping digits out of
# arbitrary output turned the error "You've hit your limit · resets 10:20pm"
# into a mail count of 1020, which fired the expensive drain every cycle —
# the exact waste this probe exists to prevent. Anything unparseable is an
# error, never a count.
new_mail_count() {
  local out
  out="$("$CLAUDE_BIN" -p "Use ToolSearch with query 'select:mcp__claude_ai_Gmail__search_threads' to load the Gmail tool, then call it with query 'subject:(JOBAGENT) newer_than:2d -label:JobAgent/Queued -label:JobAgent/Done -label:JobAgent/Blocked -label:JobAgent/Rejected' and view THREAD_VIEW_MINIMAL. Reply with ONLY the number of threads found, no words." \
    --allowedTools "ToolSearch" mcp__claude_ai_Gmail__search_threads 2>/dev/null)"

  if [[ "$out" =~ ^[[:space:]]*([0-9]{1,4})[[:space:]]*$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif printf '%s' "$out" | grep -qiE "hit your limit|usage limit|rate limit|quota"; then
    printf 'LIMIT'
  else
    printf 'ERROR'
  fi
}

run_once() {
  # A previous cycle may have been killed mid-flight (sleep, launchd timeout,
  # interrupted process), leaving an item claimed forever. Recover those first
  # or they are never retried, which looks like the agent ignoring you.
  local recovered
  recovered="$(python3 "$REPO_ROOT/scripts/command_queue.py" release-stale --older-than-minutes 30 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("count",0))' 2>/dev/null || echo 0)"
  [ "${recovered:-0}" -gt 0 ] && log "recovered ${recovered} abandoned claim(s)"

  if ! "$REPO_ROOT/scripts/chrome_bridge.sh" status >/dev/null 2>&1; then
    log "chrome bridge down - starting it"
    "$REPO_ROOT/scripts/chrome_bridge.sh" start >/dev/null 2>&1
  fi

  local pending new
  pending="$(pending_count)"
  new="$(new_mail_count)"

  case "$new" in
    LIMIT)
      # Burning cycles against an exhausted quota helps nobody. Local work
      # still waits in the queue and runs when the limit resets.
      log "usage limit reached - skipping this cycle (pending: ${pending})"
      return 0
      ;;
    ERROR)
      log "gmail probe failed - skipping this cycle (pending: ${pending})"
      return 0
      ;;
  esac

  if [ "$pending" -eq 0 ] && [ "$new" -eq 0 ]; then
    log "idle (no new mail, empty queue) - skipping the expensive drain"
    return 0
  fi

  if ! node "$REPO_ROOT/scripts/chrome_tabs.mjs" list >/dev/null 2>&1; then
    log "chrome CDP unreachable - skipping drain before claiming work (new mail: ${new}, pending: ${pending})"
    return 0
  fi

  log "work found (new mail: ${new}, pending: ${pending}) - running /drain"
  local claude_permission_args=(--permission-mode "$CLAUDE_PERMISSION_MODE")
  if [ "$CLAUDE_PERMISSION_MODE" = "bypassPermissions" ]; then
    claude_permission_args=(--allow-dangerously-skip-permissions "${claude_permission_args[@]}")
  fi
  "$CLAUDE_BIN" -p "/drain" \
    --add-dir "${CLAUDE_BROWSER_DIRS[@]}" \
    --allowedTools "ToolSearch" "Bash" "Read" "Write" "Edit" "WebSearch" "WebFetch" $GMAIL_TOOLS \
    "${claude_permission_args[@]}" \
    >>"$LOG_FILE" 2>&1
  log "drain cycle finished"
}

write_plist() {
  cat >"$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${REPO_ROOT}/scripts/drain_daemon.sh</string>
    <string>once</string>
  </array>
  <key>StartInterval</key><integer>${INTERVAL}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>${LOG_DIR}/launchd.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/launchd.err.log</string>
  <key>WorkingDirectory</key><string>${REPO_ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>${HOME}/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST_EOF
}

case "${1:-status}" in
  arm)
    write_plist
    launchctl unload "$PLIST" 2>/dev/null
    launchctl load "$PLIST" 2>/dev/null
    # launchd will not fire while the Mac sleeps, so hold it awake.
    if ! pgrep -x caffeinate >/dev/null; then
      caffeinate -dims &
      echo $! >"$CAFFEINATE_PID"
    fi
    log "armed (interval ${INTERVAL}s)"
    echo "Armed. Polling every $((INTERVAL / 60)) min; Mac held awake."
    echo "Log: $LOG_FILE"
    ;;
  disarm)
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    if [ -f "$CAFFEINATE_PID" ]; then
      kill "$(cat "$CAFFEINATE_PID")" 2>/dev/null
      rm -f "$CAFFEINATE_PID"
    fi
    log "disarmed"
    echo "Disarmed. The Mac may sleep again."
    ;;
  once)
    run_once
    ;;
  status)
    if launchctl list 2>/dev/null | grep -q "$LABEL"; then
      echo "armed (every $((INTERVAL / 60)) min)"
    else
      echo "not armed"
    fi
    pgrep -x caffeinate >/dev/null && echo "Mac held awake" || echo "Mac NOT held awake - it will sleep and nothing will run"
    echo "queue pending: $(pending_count)"
    if [ -f "$LOG_FILE" ]; then
      echo "--- last 5 log lines ---"
      tail -5 "$LOG_FILE"
    fi
    exit 0
    ;;
  *)
    echo "Usage: $0 {arm|disarm|once|status}" >&2
    exit 2
    ;;
esac
