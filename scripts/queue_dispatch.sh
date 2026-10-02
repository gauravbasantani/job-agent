#!/usr/bin/env bash
#
# Start one drain cycle for the worker requested by Slack intake.
#
# This script is intentionally small: it gives Slack a cheap way to kick the
# existing worker without making the Slack listener itself responsible for
# Chrome, resumes, or application logic.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKER="${1:-claude}"
LOG_DIR="$HOME/.job-agent/logs"
LOCK_ROOT="$HOME/.job-agent/locks"
LOG_FILE="$LOG_DIR/dispatch.log"

mkdir -p "$LOG_DIR" "$LOCK_ROOT"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE"; }

case "$WORKER" in
  codex|claude) ;;
  "")
    WORKER="claude"
    ;;
  *)
    log "unknown worker: $WORKER"
    exit 2
    ;;
esac

LOCK_DIR="$LOCK_ROOT/${WORKER}.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "$WORKER dispatch already running"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

log "starting $WORKER dispatch"
case "$WORKER" in
  codex)
    "$REPO_ROOT/scripts/codex_drain.sh" once >>"$LOG_FILE" 2>&1
    ;;
  claude)
    "$REPO_ROOT/scripts/drain_daemon.sh" once >>"$LOG_FILE" 2>&1
    ;;
esac
log "finished $WORKER dispatch"
