#!/usr/bin/env bash
#
# Keep the Slack -> command queue listener running in the background.
#
#   ./scripts/slack_daemon.sh arm
#   ./scripts/slack_daemon.sh disarm
#   ./scripts/slack_daemon.sh start    # background process, avoids launchd/TCC issues
#   ./scripts/slack_daemon.sh stop
#   ./scripts/slack_daemon.sh status
#   ./scripts/slack_daemon.sh run      # foreground, useful for testing
#
# Secrets are read from ~/.job-agent/slack.env at runtime and are never written
# into the launchd plist. The env file should be chmod 600.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.the user.jobagent.slack"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/.job-agent/logs"
LOG_FILE="$LOG_DIR/slack.log"
MANUAL_LOG_FILE="$LOG_DIR/slack.manual.log"
ENV_FILE="${JOB_AGENT_SLACK_ENV_FILE:-$HOME/.job-agent/slack.env}"
PID_FILE="$HOME/.job-agent/slack.pid"

mkdir -p "$LOG_DIR" "$HOME/.job-agent"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE"; }

load_env() {
  if [ ! -f "$ENV_FILE" ]; then
    echo "Missing $ENV_FILE" >&2
    echo "Run: ./scripts/slack_intake.mjs setup" >&2
    return 2
  fi
  # shellcheck disable=SC1090
  . "$ENV_FILE"
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
    <string>${REPO_ROOT}/scripts/slack_daemon.sh</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOG_DIR}/slack.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/slack.err.log</string>
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
  start)
    load_env || exit $?
    node "$REPO_ROOT/scripts/slack_intake.mjs" check-env >/dev/null || exit $?
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Slack listener already running with PID $(cat "$PID_FILE")."
      exit 0
    fi
    nohup "$0" run >>"$MANUAL_LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    log "started manual background listener pid $(cat "$PID_FILE")"
    echo "Slack listener started with PID $(cat "$PID_FILE")."
    echo "Log: $MANUAL_LOG_FILE"
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        kill "$(cat "$PID_FILE")" 2>/dev/null
        log "stopped manual background listener pid $(cat "$PID_FILE")"
        echo "Slack listener stopped."
      else
        echo "Slack listener PID file existed but process was not running."
      fi
      rm -f "$PID_FILE"
    else
      echo "Slack listener is not running via start."
    fi
    ;;
  arm)
    load_env || exit $?
    node "$REPO_ROOT/scripts/slack_intake.mjs" check-env >/dev/null || exit $?
    write_plist
    launchctl unload "$PLIST" 2>/dev/null
    launchctl load "$PLIST" 2>/dev/null
    log "armed"
    echo "Slack listener armed."
    echo "Log: $LOG_FILE"
    ;;
  disarm)
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    log "disarmed"
    echo "Slack listener disarmed."
    ;;
  run)
    load_env || exit $?
    log "starting foreground Slack listener"
    exec node "$REPO_ROOT/scripts/slack_intake.mjs" start
    ;;
  status)
    if launchctl list 2>/dev/null | grep -q "$LABEL"; then
      echo "armed"
    else
      echo "not armed"
    fi
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "manual listener running (PID $(cat "$PID_FILE"))"
    else
      echo "manual listener not running"
    fi
    if [ -f "$ENV_FILE" ]; then
      echo "env file present: $ENV_FILE"
    else
      echo "env file missing: $ENV_FILE"
    fi
    if [ -f "$LOG_FILE" ]; then
      echo "--- last 5 log lines ---"
      tail -5 "$LOG_FILE"
    fi
    ;;
  *)
    echo "Usage: $0 {arm|disarm|start|stop|status|run}" >&2
    exit 2
    ;;
esac
