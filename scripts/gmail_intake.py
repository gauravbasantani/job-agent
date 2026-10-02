#!/usr/bin/env python3
"""Turn `JOBAGENT:` emails into queued commands, so a phone can drive the Mac.

Workflow: from anywhere, email yourself with the command in the SUBJECT line:

    Subject: JOBAGENT: apply https://job-boards.greenhouse.io/acme/jobs/123

The agent session on the Mac runs the Gmail connector, pipes the response here,
and this enqueues the command into the same queue `command_queue.py` owns. The
Mac still does the work; this is only the doorbell.

Deliberate limits, because this reads a mailbox:

  - **Subject line only.** Message bodies are never parsed, so a forwarded
    newsletter or a quoted reply cannot inject a command.
  - **Sender allowlist.** Only mail from your own address is considered. Anyone
    can send you email; not everyone gets to queue work on your machine.
  - **Verb allowlist.** The command must start with a verb the agent already
    supports. Anything else is reported as rejected, never enqueued "just in
    case".
  - **Idempotent by Gmail message id**, so re-running intake over the same
    inbox window never double-queues. That matters because polling overlaps.

Enqueuing is not authorization. A queued `submit {job}` still meets the
confirmation gate in `context/hard-rules.md` rule 1 when the agent runs it.

Usage:
    python3 scripts/gmail_intake.py parse --payload-json '{...}'
    python3 scripts/gmail_intake.py parse --payload response.json --allow-from me@example.com
    python3 scripts/gmail_intake.py query          # print the Gmail search to run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUEUE = REPO_ROOT / ".job-agent" / "command-queue.json"
DEFAULT_AUDIT = REPO_ROOT / ".job-agent" / "command-audit.jsonl"
DEFAULT_ALLOWED_SENDER = "you@example.com"

# Tolerate the labels mail clients and humans put in front of the command.
# "Subject:" shows up because the runbook example is written as a mail header
# and gets copied verbatim into the subject field.
SUBJECT_PREFIX_RE = re.compile(
    # The trailing group is optional: a bare "JOBAGENT:" subject with the
    # instruction in the body is the normal way to send one of these, and the
    # colon is optional because phone keyboards make it easy to drop.
    r"^\s*(?:(?:re|fwd?|subject)\s*:\s*)*JOBAGENT\s*:?\s*(.*)$",
    re.IGNORECASE,
)
EMAIL_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Mirrors the commands in AGENTS.md. `find` is included so a search can be
# queued, but it produces a report rather than touching a live application.
ALLOWED_COMMANDS = re.compile(
    r"^(check|apply|force\s+tailor|continue|submit|find|search)\b",
    re.IGNORECASE,
)

# Where a signature starts, the command ends. Gmail's `snippet` field flattens
# the whole message onto one line, so a real message reads
# "find jobs from the past 24 hours and apply Best, the user Portfolio | ..."
# and the signature has to be cut off or it becomes part of the command.
SIGNATURE_RE = re.compile(
    r"\s*(?:--\s|—\s|best[,.]|best regards|regards[,.]|thanks[,.]|thank you[,.]|"
    r"cheers[,.]|sent from my|get outlook for)",
    re.IGNORECASE,
)


def command_from_body(text: object) -> str:
    """Pull the instruction out of the first meaningful line of a message."""
    for line in str(text or "").splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith(">"):  # quoted reply text is not an instruction
            continue
        cut = SIGNATURE_RE.search(candidate)
        if cut:
            candidate = candidate[: cut.start()].strip()
        if candidate:
            return re.sub(r"\s+", " ", candidate)
    return ""


def _load_command_queue():
    """Reuse the queue implementation rather than duplicating its format."""
    spec = importlib.util.spec_from_file_location(
        "command_queue", REPO_ROOT / "scripts" / "command_queue.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


command_queue = _load_command_queue()


def gmail_query(window: str = "1d") -> str:
    """The narrow search the agent should run. Subject-scoped by design."""
    return f'subject:(JOBAGENT) newer_than:{window} -in:draft'


def sender_address(value: object) -> str:
    match = EMAIL_ADDRESS_RE.search(str(value or ""))
    return match.group(0).lower() if match else ""


def extract_messages(payload: object) -> list[dict]:
    """Flatten a Gmail threads response into individual messages."""
    messages: list[dict] = []
    if not isinstance(payload, dict):
        return messages
    threads = payload.get("threads")
    if isinstance(threads, list):
        for thread in threads:
            if not isinstance(thread, dict):
                continue
            thread_id = str(thread.get("id") or thread.get("threadId") or "")
            for message in thread.get("messages") or []:
                if isinstance(message, dict):
                    messages.append({**message, "_thread_id": thread_id})
    elif isinstance(payload.get("messages"), list):
        messages.extend(m for m in payload["messages"] if isinstance(m, dict))
    return messages


def parse_message(message: dict, allowed_senders: set[str]) -> dict:
    """Decide whether one message is a legitimate command."""
    message_id = str(message.get("id") or message.get("messageId") or message.get("_thread_id") or "")
    sender = sender_address(message.get("sender") or message.get("from"))
    subject = str(message.get("subject") or "")

    if not message_id:
        return {"accepted": False, "reason": "no message id", "sender": sender}
    if sender not in allowed_senders:
        # Anyone can email you. Only you can queue work.
        return {"accepted": False, "reason": "sender not allowed", "sender": sender, "message_id": message_id}

    # The subject is the gate: without the JOBAGENT prefix from an allowed
    # sender, nothing in the message is treated as an instruction.
    match = SUBJECT_PREFIX_RE.match(subject)
    if not match:
        return {"accepted": False, "reason": "subject is not a JOBAGENT command", "message_id": message_id}

    subject_command = re.sub(r"\s+", " ", match.group(1)).strip()
    body_command = command_from_body(message.get("body") or message.get("snippet"))

    # The body wins when it carries a real command, because that is where
    # people actually write the instruction — the subject stays a marker.
    if ALLOWED_COMMANDS.match(body_command):
        command, source = body_command, "body"
    elif ALLOWED_COMMANDS.match(subject_command):
        command, source = subject_command, "subject"
    elif not subject_command and not body_command:
        return {"accepted": False, "reason": "empty command", "message_id": message_id}
    else:
        return {"accepted": False, "reason": "unsupported command verb", "message_id": message_id}

    return {
        "accepted": True,
        "message_id": message_id,
        "sender": sender,
        "command": command,
        "command_source": source,
        # Gmail's message id is stable, so re-reading the same inbox window
        # cannot enqueue the same instruction twice.
        "idempotency_key": f"gmail:{message_id}",
    }


def intake(payload: object, allowed_senders: set[str], queue_path: Path, audit_path: Path) -> dict:
    queue = command_queue.load_queue(queue_path)
    accepted, rejected = [], []

    for message in extract_messages(payload):
        parsed = parse_message(message, allowed_senders)
        if not parsed["accepted"]:
            rejected.append(parsed)
            continue
        result = command_queue.enqueue(
            queue, parsed["command"], parsed["idempotency_key"], "gmail"
        )
        accepted.append({
            "message_id": parsed["message_id"],
            "command": result["item"]["command"],
            "queue_id": result["item"]["id"],
            "duplicate": result["duplicate"],
        })

    command_queue.save_queue(queue_path, queue)
    for entry in accepted:
        command_queue.write_audit(audit_path, {
            "action": "gmail_intake",
            "id": entry["queue_id"],
            "result": "duplicate_ignored" if entry["duplicate"] else "enqueued",
            "source": "gmail",
        })

    return {
        "enqueued": [entry for entry in accepted if not entry["duplicate"]],
        "already_queued": [entry for entry in accepted if entry["duplicate"]],
        "rejected": rejected,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queue-file", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--audit-file", type=Path, default=DEFAULT_AUDIT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("query", help="Print the Gmail search the agent should run")

    parse_cmd = sub.add_parser("parse", help="Enqueue commands found in a Gmail response")
    parse_cmd.add_argument("--payload", type=Path)
    parse_cmd.add_argument("--payload-json", default="")
    parse_cmd.add_argument(
        "--allow-from",
        action="append",
        default=[],
        help="Sender address permitted to queue commands (repeatable)",
    )

    args = parser.parse_args(argv)

    if args.command == "query":
        print(json.dumps({
            "gmail_query": gmail_query(),
            "note": "Subject lines only. Bodies are never parsed, so a quoted "
                    "or forwarded message cannot inject a command.",
        }, indent=2))
        return 0

    try:
        if args.payload_json:
            payload = json.loads(args.payload_json)
        elif args.payload:
            payload = json.loads(args.payload.read_text(encoding="utf-8"))
        else:
            raise ValueError("parse needs --payload or --payload-json")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2

    allowed = {address.lower() for address in (args.allow_from or [DEFAULT_ALLOWED_SENDER])}
    result = intake(payload, allowed, args.queue_file.resolve(), args.audit_file.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
