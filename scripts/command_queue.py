#!/usr/bin/env python3
"""Idempotent, auditable command intake so the user can queue work from a phone.

The queue is deliberately dumb: it accepts the same commands the agent already
understands (`check {url}`, `apply {url}`, `continue {job}`, `submit {job}`),
stores them locally, and hands them out one at a time. It runs no browser and
makes no decisions.

Enqueueing is NOT authorization to submit. A queued `submit {job}` still goes
through the confirmation gate in `context/hard-rules.md` rule 1 when the agent
picks it up — the queue records intent, it does not bypass a human.

Idempotency: every command carries a key. An explicit `--idempotency-key`
wins; otherwise the key is derived from the normalized command text, so a
phone that retries on a flaky connection enqueues one item, not five.

Reality check: this only queues work. Local Chrome automation still needs the
Mac awake with the the user profile and the CDP bridge running. A queued command
sits pending until an agent session drains it.

Usage:
    python3 scripts/command_queue.py enqueue "apply https://..." [--idempotency-key K] [--source phone]
    python3 scripts/command_queue.py list [--status pending] [--assigned-worker codex]
    python3 scripts/command_queue.py claim [--worker NAME] [--worker-type claude|codex|any]
    python3 scripts/command_queue.py complete --id ID [--result TEXT]
    python3 scripts/command_queue.py fail --id ID [--result TEXT]
    python3 scripts/command_queue.py release --id ID
    python3 scripts/command_queue.py attach-result --id ID --result-file PATH [--renotify]
    python3 scripts/command_queue.py mark-notified --id ID --status completed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUEUE = REPO_ROOT / ".job-agent" / "command-queue.json"
DEFAULT_AUDIT = REPO_ROOT / ".job-agent" / "command-audit.jsonl"

TERMINAL_STATUSES = {"completed", "failed"}

# How much of a worker's final answer is kept. Slack splits it into several
# messages on the way out, so this only needs to bound the queue file.
RESULT_DETAILS_LIMIT = 40000
VALID_WORKERS = {"", "claude", "codex"}
CLAUDE_DEFAULT_WORKER = "claude"

# Secrets must never reach the queue file or the audit log, even if someone
# pastes a whole verification email into a command from their phone.
SECRET_PATTERNS = (
    re.compile(r"\b(?:password|passcode|otp|pin|token|secret|api[_-]?key)\b\s*[:=]?\s*\S+", re.IGNORECASE),
    re.compile(r"\b(?:code)\b\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"https?://\S*(?:token|magic|auth|verify|reset)=\S*", re.IGNORECASE),
    re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b"),  # SSN-shaped
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),  # card-shaped
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str | None, limit: int = 2000) -> str:
    value = str(text or "")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[redacted]", value)
    return value.strip()[:limit]


def normalize_command(text: str) -> str:
    """Collapse whitespace and case so trivial retries hash identically."""
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def extract_worker(text: str) -> tuple[str, str]:
    """Return command text plus an optional worker routing label.

    Phone commands should still start with the normal verb, so routing lives at
    the end: `apply ... worker:codex`, `apply ... :codex`, or `apply ... for codex`.
    Unknown labels are left as part of the command instead of guessed.
    """
    value = str(text or "").strip()
    suffix = r"(?:['’]s)?[\s.!,;:]*$"
    match = re.search(
        rf"(?:\s+worker\s*:\s*(claude|codex)|\s+for\s+(claude|codex)|\s*:(claude|codex)){suffix}",
        value,
        re.IGNORECASE,
    )
    if not match:
        return value, ""
    worker = next(part for part in match.groups() if part).lower()
    return value[: match.start()].strip(), worker


def derive_key(text: str) -> str:
    return hashlib.sha256(normalize_command(text).encode("utf-8")).hexdigest()[:16]


def load_queue(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "next_id": 1, "items": []}
    data.setdefault("version", 1)
    data.setdefault("next_id", 1)
    data.setdefault("items", [])
    return data


def save_queue(path: Path, queue: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_audit(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {
        "timestamp": now(),
        **{key: redact(value) if isinstance(value, str) else value for key, value in event.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, sort_keys=True) + "\n")


def find_by_key(queue: dict, key: str) -> dict | None:
    for item in queue["items"]:
        if item.get("idempotency_key") == key:
            return item
    return None


def find_by_id(queue: dict, item_id: int) -> dict | None:
    for item in queue["items"]:
        if item.get("id") == item_id:
            return item
    return None


def clean_metadata(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "", str(value or ""))[:128]


def slack_notify_metadata(team: str = "", channel: str = "", user: str = "", thread_ts: str = "") -> dict:
    channel = clean_metadata(channel)
    user = clean_metadata(user)
    if not channel and not user:
        return {}
    return {
        "type": "slack",
        "team": clean_metadata(team),
        "channel": channel,
        "user": user,
        "thread_ts": clean_metadata(thread_ts),
        "notified_status": "",
        "notified_at": "",
    }


def merge_notify_metadata(item: dict, notify: dict | None) -> None:
    if not notify:
        return
    existing = item.setdefault("notify", {"type": notify.get("type", "")})
    if existing.get("type") and existing.get("type") != notify.get("type"):
        return
    for key in ("type", "team", "channel", "user", "thread_ts"):
        value = notify.get(key)
        if value:
            existing[key] = value
    existing.setdefault("notified_status", "")
    existing.setdefault("notified_at", "")


def enqueue(queue: dict, command: str, key: str, source: str, notify: dict | None = None) -> dict:
    command_text, assigned_worker = extract_worker(command)
    text = redact(command_text)
    if not text:
        raise ValueError("command text is empty")
    idempotency_key = key or derive_key(f"{assigned_worker}:{text}")

    existing = find_by_key(queue, idempotency_key)
    if existing is not None:
        # Same key, already known: return the original item untouched. This is
        # what makes a phone retry safe.
        merge_notify_metadata(existing, notify)
        existing["duplicate_count"] = int(existing.get("duplicate_count", 0)) + 1
        existing["last_submitted_at"] = now()
        return {"enqueued": False, "duplicate": True, "item": existing}

    item = {
        "id": queue["next_id"],
        "command": text,
        "assigned_worker": assigned_worker,
        "idempotency_key": idempotency_key,
        "status": "pending",
        "source": redact(source) or "unknown",
        "enqueued_at": now(),
        "last_submitted_at": now(),
        "duplicate_count": 0,
        "claimed_by": "",
        "claimed_at": "",
        "finished_at": "",
        "result": "",
        "note": "Queued only. Submission still requires explicit confirmation when the agent runs it.",
    }
    merge_notify_metadata(item, notify)
    queue["items"].append(item)
    queue["next_id"] += 1
    return {"enqueued": True, "duplicate": False, "item": item}


def assigned_worker_for(item: dict) -> str:
    saved = str(item.get("assigned_worker") or "").strip().lower()
    if saved and saved in VALID_WORKERS:
        return saved
    _, parsed = extract_worker(item.get("command") or "")
    return parsed if parsed in VALID_WORKERS else ""


def normalize_worker_metadata(item: dict) -> str:
    saved = str(item.get("assigned_worker") or "").strip().lower()
    command_text, parsed = extract_worker(item.get("command") or "")
    if parsed in VALID_WORKERS and (not saved or saved == parsed):
        item["command"] = command_text
        item["assigned_worker"] = parsed
        return parsed
    return saved if saved in VALID_WORKERS else ""


def worker_matches(item: dict, worker_type: str) -> bool:
    worker_type = str(worker_type or CLAUDE_DEFAULT_WORKER).strip().lower()
    if worker_type == "any":
        return True
    if worker_type not in {"claude", "codex"}:
        raise ValueError("--worker-type must be claude, codex, or any")
    assigned = assigned_worker_for(item)
    if worker_type == CLAUDE_DEFAULT_WORKER:
        return assigned in {"", CLAUDE_DEFAULT_WORKER}
    return assigned == worker_type


def claim(queue: dict, worker: str, worker_type: str = CLAUDE_DEFAULT_WORKER) -> dict:
    for item in queue["items"]:
        if item.get("status") == "pending" and worker_matches(item, worker_type):
            normalize_worker_metadata(item)
            item["status"] = "in_progress"
            item["claimed_by"] = redact(worker) or "agent"
            item["claimed_at"] = now()
            if worker_type == "codex":
                item["result_details_expected"] = True
            return {"claimed": True, "item": item}
    return {"claimed": False, "item": None}


def finish(queue: dict, item_id: int, status: str, result: str) -> dict:
    item = find_by_id(queue, item_id)
    if item is None:
        raise ValueError(f"No queued command with id {item_id}")
    # Idempotent: finishing an already-terminal item does not overwrite the
    # original outcome or timestamp.
    if item["status"] in TERMINAL_STATUSES:
        return {"changed": False, "item": item}
    item["status"] = status
    item["result"] = redact(result)
    item["finished_at"] = now()
    return {"changed": True, "item": item}


def release_stale(queue: dict, older_than_minutes: int) -> dict:
    """Return abandoned claims to pending.

    A drain cycle can die mid-flight — the Mac sleeps, launchd kills it, the
    process is interrupted. Without this the item stays `in_progress` forever
    and is never retried, which looks exactly like the agent ignoring you.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (older_than_minutes * 60)
    released = []
    for item in queue["items"]:
        if item.get("status") != "in_progress":
            continue
        claimed_at = item.get("claimed_at") or ""
        try:
            claimed_ts = datetime.fromisoformat(claimed_at).timestamp()
        except ValueError:
            claimed_ts = 0  # unparseable claim time counts as stale
        if claimed_ts < cutoff:
            item["status"] = "pending"
            item["claimed_by"] = ""
            item["claimed_at"] = ""
            # See release(): this belongs to the claim being abandoned.
            item["result_details_expected"] = False
            released.append(item["id"])
    return {"released": released, "count": len(released)}


def release(queue: dict, item_id: int) -> dict:
    item = find_by_id(queue, item_id)
    if item is None:
        raise ValueError(f"No queued command with id {item_id}")
    if item["status"] != "in_progress":
        return {"changed": False, "item": item}
    item["status"] = "pending"
    item["claimed_by"] = ""
    item["claimed_at"] = ""
    # The flag belongs to the claim, not the item. A codex claim that is
    # released and re-claimed by claude would otherwise wait forever for
    # details nobody is going to attach, and never notify Slack at all.
    item["result_details_expected"] = False
    return {"changed": True, "item": item}


def needs_notification(item: dict) -> bool:
    if item.get("status") not in TERMINAL_STATUSES:
        return False
    if item.get("result_details_expected") and not item.get("result_details"):
        return False
    notify = item.get("notify") or {}
    if notify.get("type") != "slack":
        return False
    if not notify.get("channel") and not notify.get("user"):
        return False
    return notify.get("notified_status") != item.get("status")


def mark_notified(queue: dict, item_id: int, status: str) -> dict:
    item = find_by_id(queue, item_id)
    if item is None:
        raise ValueError(f"No queued command with id {item_id}")
    if item.get("status") != status:
        raise ValueError(f"Queued command {item_id} is {item.get('status')}, not {status}")
    notify = item.setdefault("notify", {"type": "slack"})
    notify["notified_status"] = status
    notify["notified_at"] = now()
    return {"changed": True, "item": item}


def attach_result(queue: dict, item_id: int, result_text: str, renotify: bool = False) -> dict:
    item = find_by_id(queue, item_id)
    if item is None:
        raise ValueError(f"No queued command with id {item_id}")
    # A full answer — scored job table, tailoring deltas, what is still waiting
    # on the user — runs well past the old 6000-char cap, and the part he most
    # needs is written last. Keep the whole thing, and if a genuinely runaway
    # result has to be cut, say so instead of ending mid-sentence.
    text = redact(result_text, limit=RESULT_DETAILS_LIMIT)
    if len(str(result_text or "").strip()) > len(text):
        text = f"{text}\n\n_[result truncated at {RESULT_DETAILS_LIMIT} characters]_"
    if not text:
        raise ValueError("result text is empty")
    item["result_details"] = text
    item["result_details_expected"] = False
    if renotify:
        notify = item.setdefault("notify", {"type": "slack"})
        notify["notified_status"] = ""
        notify["notified_at"] = ""
    return {"changed": True, "item": item}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queue-file", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--audit-file", type=Path, default=DEFAULT_AUDIT)
    sub = parser.add_subparsers(dest="command", required=True)

    enq = sub.add_parser("enqueue", help="Add a command to the queue")
    enq.add_argument("text", nargs="+")
    enq.add_argument("--idempotency-key", default="")
    enq.add_argument("--source", default="phone")
    enq.add_argument("--notify-team", default="")
    enq.add_argument("--notify-channel", default="")
    enq.add_argument("--notify-user", default="")
    enq.add_argument("--notify-thread-ts", default="")

    lister = sub.add_parser("list", help="List queued commands")
    lister.add_argument("--status", default="")
    lister.add_argument("--assigned-worker", default="")
    lister.add_argument("--needs-notification", action="store_true")

    claimer = sub.add_parser("claim", help="Take the next pending command")
    claimer.add_argument("--worker", default="agent")
    claimer.add_argument("--worker-type", default=CLAUDE_DEFAULT_WORKER, choices=["claude", "codex", "any"])

    for name in ("complete", "fail"):
        finisher = sub.add_parser(name, help=f"Mark a command {name}d")
        finisher.add_argument("--id", type=int, required=True)
        finisher.add_argument("--result", default="")

    releaser = sub.add_parser("release", help="Return an in-progress command to pending")
    releaser.add_argument("--id", type=int, required=True)

    stale = sub.add_parser("release-stale", help="Return abandoned claims to pending")
    stale.add_argument("--older-than-minutes", type=int, default=30)

    notified = sub.add_parser("mark-notified", help="Mark a terminal command's Slack result sent")
    notified.add_argument("--id", type=int, required=True)
    notified.add_argument("--status", choices=sorted(TERMINAL_STATUSES), required=True)

    attach = sub.add_parser("attach-result", help="Attach the worker's final response to a queued command")
    attach.add_argument("--id", type=int, required=True)
    # A file suits codex (it writes its last message to disk); inline text
    # suits the Claude drain, which already has the answer in hand.
    attach.add_argument("--result-file", type=Path)
    attach.add_argument("--result", default="")
    attach.add_argument("--renotify", action="store_true")

    args = parser.parse_args(argv)
    queue_path = args.queue_file.resolve()
    audit_path = args.audit_file.resolve()
    queue = load_queue(queue_path)

    try:
        if args.command == "enqueue":
            notify = slack_notify_metadata(
                team=args.notify_team,
                channel=args.notify_channel,
                user=args.notify_user,
                thread_ts=args.notify_thread_ts,
            )
            result = enqueue(queue, " ".join(args.text), args.idempotency_key, args.source, notify)
            save_queue(queue_path, queue)
            write_audit(audit_path, {
                "action": "enqueue",
                "id": result["item"]["id"],
                "idempotency_key": result["item"]["idempotency_key"],
                "result": "duplicate_ignored" if result["duplicate"] else "enqueued",
                "source": result["item"]["source"],
            })
        elif args.command == "claim":
            result = claim(queue, args.worker, args.worker_type)
            save_queue(queue_path, queue)
            write_audit(audit_path, {
                "action": "claim",
                "id": result["item"]["id"] if result["item"] else None,
                "result": "claimed" if result["claimed"] else "empty",
                "worker_type": args.worker_type,
            })
        elif args.command in {"complete", "fail"}:
            status = "completed" if args.command == "complete" else "failed"
            result = finish(queue, args.id, status, args.result)
            save_queue(queue_path, queue)
            write_audit(audit_path, {
                "action": args.command,
                "id": args.id,
                "result": status if result["changed"] else "already_terminal",
            })
        elif args.command == "release-stale":
            result = release_stale(queue, max(1, args.older_than_minutes))
            save_queue(queue_path, queue)
            if result["released"]:
                write_audit(audit_path, {"action": "release_stale", "id": None,
                                         "result": f"released {result['released']}"})
        elif args.command == "release":
            result = release(queue, args.id)
            save_queue(queue_path, queue)
            write_audit(audit_path, {"action": "release", "id": args.id,
                                     "result": "released" if result["changed"] else "not_in_progress"})
        elif args.command == "mark-notified":
            result = mark_notified(queue, args.id, args.status)
            save_queue(queue_path, queue)
            write_audit(audit_path, {"action": "mark_notified", "id": args.id,
                                     "result": args.status})
        elif args.command == "attach-result":
            if args.result_file:
                try:
                    result_text = args.result_file.read_text(encoding="utf-8")
                except OSError as exc:
                    raise ValueError(f"Could not read result file: {exc}") from exc
            elif args.result:
                result_text = args.result
            else:
                raise ValueError("attach-result needs --result-file or --result")
            result = attach_result(queue, args.id, result_text, args.renotify)
            save_queue(queue_path, queue)
            write_audit(audit_path, {"action": "attach_result", "id": args.id,
                                     "result": "attached"})
        else:
            items = queue["items"]
            if args.status:
                items = [item for item in items if item.get("status") == args.status]
            if args.assigned_worker:
                wanted = args.assigned_worker.strip().lower()
                items = [item for item in items if assigned_worker_for(item) == wanted]
            if args.needs_notification:
                items = [item for item in items if needs_notification(item)]
            result = {"count": len(items), "items": items}
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
