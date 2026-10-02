#!/usr/bin/env python3
"""Human-verification handoff: pause a job, tell the user what to do, resume it.

Some application steps are his alone: creating an account, typing a password,
entering a one-time code, clicking an emailed verification link, solving a
CAPTCHA. This script records that a job is waiting on one of those, states
exactly what to complete, and marks it resumable once he is done.

What this deliberately does NOT do, per `context/hard-rules.md`:
  - store, read back, or transcribe a one-time code, password, or token;
  - open or follow a magic-login link;
  - create an account or act as the user in any credential flow.

Gmail assistance is confirmation-only. `gmail-query` builds a narrow search;
the agent runs it through the Gmail connector in METADATA-ONLY mode and pipes
the response to `record-email`, which confirms the message *arrived* without
ever ingesting what it says.

`record-email` is the gatekeeper, not a formality. It reconstructs a fresh
record from an allowlist of non-content fields — sender address, timestamp,
thread id, labels — and drops everything else on the floor. Subject lines,
snippets and bodies are discarded even when handed to it, because a
verification email's snippet very often contains the code itself.

Usage:
    python3 scripts/verification_handoff.py open --job JOB --type email_verification \\
        --url URL [--company NAME] [--instructions TEXT] [--sender no-reply@ats.com]
    python3 scripts/verification_handoff.py list [--pending]
    python3 scripts/verification_handoff.py status --job JOB
    python3 scripts/verification_handoff.py resolve --job JOB [--note TEXT]
    python3 scripts/verification_handoff.py gmail-query --job JOB
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = REPO_ROOT / ".job-agent" / "verification-handoff.json"
DEFAULT_AUDIT = REPO_ROOT / ".job-agent" / "verification-audit.jsonl"

# Every handoff type is a human-only step. The agent's job is to pause, keep
# the tab mapped, explain the step, and wait for `continue {job}`.
HANDOFF_TYPES = {
    "email_verification": "Open the verification email and complete the link/code step in the mapped tab.",
    "account_creation": "Create the account yourself using the signup link, then return to the mapped tab.",
    "login": "Sign in to the existing account in the mapped tab.",
    "otp": "Enter the one-time code yourself. The agent will never read or type it.",
    "captcha": "Solve the CAPTCHA in the mapped tab.",
    "identity_document": "Provide the identity/government document yourself if you choose to continue.",
    "payment": "Provide any payment detail yourself if you choose to continue.",
}

JOB_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,119}$", re.IGNORECASE)

# Anything matching these is scrubbed before it reaches disk. A note is free
# text typed by a human in a hurry; it must never carry a live secret.
SECRET_PATTERNS = (
    re.compile(r"\b(?:code|otp|pin|password|passcode|token|secret)\b\s*[:=]?\s*\S+", re.IGNORECASE),
    re.compile(r"\b\d{4,10}\b"),
    re.compile(r"https?://\S*(?:token|verify|confirm|magic|auth|reset)\S*", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b(?=\S*(?:token|code))", re.IGNORECASE),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str | None) -> str:
    """Strip anything that looks like a live secret from free text."""
    value = str(text or "")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[redacted]", value)
    return value.strip()[:500]


def valid_job_key(value: str) -> bool:
    return bool(JOB_KEY_RE.match(str(value or "")))


# --- Gmail metadata gatekeeper -------------------------------------------
#
# The Gmail connector must be called with THREAD_VIEW_METADATA_ONLY. This code
# assumes it wasn't. Everything below rebuilds a record from an allowlist of
# non-content fields, so a subject or snippet cannot reach disk even if the
# caller hands over a full message. Deleting known-bad keys would fail open on
# the first field shape nobody anticipated; an allowlist fails closed.

GMAIL_METADATA_FIELDS = ("thread_id", "from", "received_at", "label_ids")
EMAIL_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def sender_address(value: object) -> str:
    """Keep only the address. A display name is attacker-controlled text and
    has carried codes before ("Your code is 481920 <no-reply@x.com>")."""
    match = EMAIL_ADDRESS_RE.search(str(value or ""))
    return match.group(0)[:200] if match else ""


def normalized_timestamp(value: object) -> str:
    """Accept a real date in either common Gmail shape, or nothing at all."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat(timespec="seconds")
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).isoformat(timespec="seconds")
    except (TypeError, ValueError, IndexError):
        return ""


def sanitize_email_metadata(payload: object) -> dict:
    """Reduce any Gmail-shaped response to confirmation metadata only."""
    thread: dict = {}
    if isinstance(payload, dict):
        threads = payload.get("threads")
        if isinstance(threads, list) and threads and isinstance(threads[0], dict):
            thread = threads[0]
        elif isinstance(payload.get("thread"), dict):
            thread = payload["thread"]
        else:
            thread = payload

    messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
    message = next((item for item in reversed(messages) if isinstance(item, dict)), {})

    thread_id = str(thread.get("id") or thread.get("threadId") or message.get("threadId") or "")
    labels = message.get("labelIds") or thread.get("labelIds") or []
    # The live connector names this `sender`; the REST API and most examples
    # use `from`. Accept both, or the sender silently records as empty.
    sender = (
        message.get("sender")
        or message.get("from")
        or thread.get("sender")
        or thread.get("from")
    )

    return {
        "thread_id": thread_id if IDENTIFIER_RE.match(thread_id) else "",
        "from": sender_address(sender),
        "received_at": normalized_timestamp(
            message.get("date") or message.get("receivedAt") or thread.get("date")
        ),
        "label_ids": [
            str(label)[:40] for label in labels if isinstance(label, str)
        ][:10],
    }


def record_email(state: dict, job: str, payload: object) -> dict:
    """Note that the verification message arrived. Never what it said."""
    entry = state["handoffs"].get(job)
    if not entry:
        raise ValueError(f"No verification handoff is recorded for {job}")

    metadata = sanitize_email_metadata(payload)
    if not any(metadata[field] for field in GMAIL_METADATA_FIELDS):
        raise ValueError(
            "No usable message metadata found. Call the Gmail connector with "
            "view=THREAD_VIEW_METADATA_ONLY and pass its response."
        )

    entry["email_seen"] = True
    entry["email_checked_at"] = now()
    entry["email_from"] = metadata["from"]
    entry["email_received_at"] = metadata["received_at"]
    entry["email_thread_id"] = metadata["thread_id"]
    # Finding the email does not clear the blocker: the user still completes the
    # step. This only upgrades "go look" into "it arrived".
    entry["status"] = entry.get("status", "pending")
    return {"handoff": entry, "metadata": metadata}


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "handoffs": {}}
    data.setdefault("version", 1)
    data.setdefault("handoffs", {})
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_audit(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {"timestamp": now(), **{key: redact(value) if isinstance(value, str) else value for key, value in event.items()}}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, sort_keys=True) + "\n")


def gmail_query(entry: dict) -> str:
    """Build a narrow Gmail search that finds the message without reading it."""
    parts = ["newer_than:1d"]
    sender = entry.get("sender", "")
    if sender:
        parts.append(f"from:({sender})")
    company = entry.get("company", "")
    if company and not sender:
        parts.append(f'("{company}")')
    subject_terms = {
        "email_verification": "(verify OR verification OR confirm)",
        "account_creation": "(welcome OR \"create your account\" OR activate)",
        "login": "(sign-in OR login OR \"new sign-in\")",
        "otp": "(code OR verification)",
    }
    term = subject_terms.get(entry.get("type", ""))
    if term:
        parts.append(f"subject:{term}")
    return " ".join(parts)


def open_handoff(state: dict, args: argparse.Namespace) -> dict:
    if not valid_job_key(args.job):
        raise ValueError("--job must be a stable slug of 2-120 characters")
    if args.type not in HANDOFF_TYPES:
        raise ValueError(f"--type must be one of: {', '.join(sorted(HANDOFF_TYPES))}")

    existing = state["handoffs"].get(args.job)
    # Idempotent: re-reporting the same open blocker returns the same record
    # instead of stacking duplicates every time a retry hits the same wall.
    if existing and existing.get("status") == "pending" and existing.get("type") == args.type:
        existing["last_seen_at"] = now()
        existing["seen_count"] = int(existing.get("seen_count", 1)) + 1
        return {"created": False, "reused": True, "handoff": existing}

    entry = {
        "job_key": args.job,
        "type": args.type,
        "status": "pending",
        "company": redact(args.company),
        "url": redact(args.url),
        "sender": redact(args.sender),
        "action_required": HANDOFF_TYPES[args.type],
        "instructions": redact(args.instructions) or HANDOFF_TYPES[args.type],
        "agent_will_not": [
            "type or read a one-time code",
            "type a password or create an account",
            "click a magic-login link",
            "solve a CAPTCHA",
        ],
        "resume_with": f"continue {args.job}",
        "opened_at": now(),
        "last_seen_at": now(),
        "seen_count": 1,
        "resolved_at": "",
    }
    entry["gmail_query"] = gmail_query(entry)
    state["handoffs"][args.job] = entry
    return {"created": True, "reused": False, "handoff": entry}


def resolve_handoff(state: dict, job: str, note: str) -> dict:
    entry = state["handoffs"].get(job)
    if not entry:
        raise ValueError(f"No verification handoff is recorded for {job}")
    # Idempotent: resolving twice is a no-op, so a repeated `continue {job}`
    # from a phone never corrupts state.
    if entry.get("status") == "resolved":
        return {"changed": False, "handoff": entry}
    entry["status"] = "resolved"
    entry["resolved_at"] = now()
    if note:
        entry["resolution_note"] = redact(note)
    return {"changed": True, "handoff": entry}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--audit-file", type=Path, default=DEFAULT_AUDIT)
    sub = parser.add_subparsers(dest="command", required=True)

    opener = sub.add_parser("open", help="Record that a job is waiting on a human step")
    opener.add_argument("--job", required=True)
    opener.add_argument("--type", required=True, choices=sorted(HANDOFF_TYPES))
    opener.add_argument("--url", default="")
    opener.add_argument("--company", default="")
    opener.add_argument("--sender", default="")
    opener.add_argument("--instructions", default="")

    lister = sub.add_parser("list", help="List handoffs")
    lister.add_argument("--pending", action="store_true")

    status = sub.add_parser("status", help="Show one job's handoff")
    status.add_argument("--job", required=True)

    resolver = sub.add_parser("resolve", help="Mark the human step complete so the job can resume")
    resolver.add_argument("--job", required=True)
    resolver.add_argument("--note", default="")

    query = sub.add_parser("gmail-query", help="Print the narrow Gmail search for this job")
    query.add_argument("--job", required=True)

    recorder = sub.add_parser(
        "record-email",
        help="Record that the verification message arrived (metadata only)",
    )
    recorder.add_argument("--job", required=True)
    recorder.add_argument("--payload", type=Path, help="File holding the Gmail connector response")
    recorder.add_argument("--payload-json", default="", help="Gmail connector response as inline JSON")

    args = parser.parse_args(argv)
    state_path = args.state_file.resolve()
    audit_path = args.audit_file.resolve()
    state = load_state(state_path)

    try:
        if args.command == "open":
            result = open_handoff(state, args)
            save_state(state_path, state)
            write_audit(audit_path, {
                "job_key": args.job,
                "action": "open",
                "type": args.type,
                "result": "created" if result["created"] else "reused",
            })
        elif args.command == "resolve":
            result = resolve_handoff(state, args.job, args.note)
            save_state(state_path, state)
            write_audit(audit_path, {
                "job_key": args.job,
                "action": "resolve",
                "result": "resolved" if result["changed"] else "already_resolved",
            })
        elif args.command == "status":
            entry = state["handoffs"].get(args.job)
            if not entry:
                print(json.dumps({"job_key": args.job, "status": "none"}, indent=2))
                return 0
            result = entry
        elif args.command == "gmail-query":
            entry = state["handoffs"].get(args.job)
            if not entry:
                raise ValueError(f"No verification handoff is recorded for {args.job}")
            result = {
                "job_key": args.job,
                "gmail_query": gmail_query(entry),
                "required_view": "THREAD_VIEW_METADATA_ONLY",
                "note": (
                    "Run this through the Gmail connector with "
                    "view=THREAD_VIEW_METADATA_ONLY, then pipe the response to "
                    "`record-email`. The default view returns snippets, and a "
                    "verification snippet usually contains the code itself. "
                    "Confirm the message arrived; never copy a code into the agent."
                ),
            }
        elif args.command == "record-email":
            if args.payload_json:
                payload = json.loads(args.payload_json)
            elif args.payload:
                payload = json.loads(args.payload.read_text(encoding="utf-8"))
            else:
                raise ValueError("record-email needs --payload or --payload-json")
            result = record_email(state, args.job, payload)
            save_state(state_path, state)
            write_audit(audit_path, {
                "job_key": args.job,
                "action": "record_email",
                "result": "email_seen",
                "sender": result["metadata"]["from"],
            })
        else:
            entries = list(state["handoffs"].values())
            if args.pending:
                entries = [entry for entry in entries if entry.get("status") == "pending"]
            result = {"count": len(entries), "handoffs": entries}
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
