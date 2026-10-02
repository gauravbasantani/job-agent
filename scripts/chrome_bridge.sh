#!/usr/bin/env bash
#
# Start (or confirm) the Chrome instance the job agent is allowed to drive.
#
# Why a dedicated user-data-dir instead of your everyday Chrome:
# since Chrome 136, --remote-debugging-port is refused on the default
# user-data-dir. That is a deliberate anti-cookie-theft measure, and working
# around it by exposing your main profile to CDP would hand any local process
# your logged-in sessions. So automation gets its own Chrome data directory,
# with a profile named `the user Automation` that `chrome_tabs.mjs` verifies
# before it touches a tab. The name is deliberately distinct from your real
# `the user` profile: a second profile with the same name would pass the guard
# by impersonation, which would make the check meaningless.
#
# You log into LinkedIn and the ATS platforms in this window once. The session
# persists in ~/.job-agent/chrome-profile like any normal Chrome profile.
#
# Usage:
#   ./scripts/chrome_bridge.sh start     # launch (idempotent) and verify
#   ./scripts/chrome_bridge.sh status    # is the bridge up?
#   ./scripts/chrome_bridge.sh stop      # quit only this instance
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
USER_DATA_DIR="${JOB_AGENT_CHROME_DIR:-$HOME/.job-agent/chrome-profile}"
PORT="${JOB_AGENT_CDP_PORT:-9222}"
PROFILE_NAME="the user Automation"
LOG_FILE="$USER_DATA_DIR/chrome-bridge.log"

cdp_up() {
  curl -s --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1
}

# Chrome names a fresh profile "Your Chrome"/"Person 1", and the guard in
# chrome_tabs.mjs checks Chrome's own metadata rather than trusting a flag.
# Seed the name into Local State *before* launching: Chrome holds that file in
# memory and rewrites it on exit, so editing a running instance loses the edit.
seed_profile_name() {
  python3 - "$USER_DATA_DIR" "$PROFILE_NAME" <<'PY'
import json, os, sys
user_data_dir, wanted = sys.argv[1], sys.argv[2]
path = os.path.join(user_data_dir, "Local State")
try:
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, json.JSONDecodeError):
    state = {}
entry = state.setdefault("profile", {}).setdefault("info_cache", {}).setdefault("Default", {})
if entry.get("name") == wanted:
    print(f"profile already named {wanted}")
    sys.exit(0)
entry["name"] = wanted
entry["shortcut_name"] = wanted
entry.setdefault("is_using_default_name", False)
os.makedirs(user_data_dir, exist_ok=True)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(state, handle)
print(f"profile named {wanted}")
PY
}

start() {
  if cdp_up; then
    echo "CDP already listening on ${PORT}"
  else
    mkdir -p "$USER_DATA_DIR/Default"
    seed_profile_name
    echo "Starting Chrome (profile: ${PROFILE_NAME}, port: ${PORT})..."
    "$CHROME_BIN" \
      --user-data-dir="$USER_DATA_DIR" \
      --profile-directory=Default \
      --remote-debugging-port="$PORT" \
      --no-first-run \
      --no-default-browser-check \
      --disable-breakpad \
      --disable-crash-reporter \
      --disable-crashpad \
      --restore-last-session \
      >"$LOG_FILE" 2>&1 &
    for _ in $(seq 1 30); do
      cdp_up && break
      sleep 0.5
    done
  fi

  if ! cdp_up; then
    echo "Chrome did not expose CDP on ${PORT}. See ${LOG_FILE}" >&2
    return 1
  fi

  echo
  echo "Verifying the agent will accept this profile..."
  node "$REPO_ROOT/scripts/chrome_tabs.mjs" verify --port "$PORT"
}

case "${1:-start}" in
  start) start ;;
  status)
    if cdp_up; then
      echo "up on ${PORT}"
      node "$REPO_ROOT/scripts/chrome_tabs.mjs" verify --port "$PORT"
    else
      echo "down"
      exit 1
    fi
    ;;
  stop)
    pkill -f "user-data-dir=${USER_DATA_DIR}" && echo "stopped" || echo "was not running"
    ;;
  *)
    echo "Usage: $0 {start|status|stop}" >&2
    exit 2
    ;;
esac
