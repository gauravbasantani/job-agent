#!/usr/bin/env python3
"""Turn pasted job emails into tracker status updates.

There is no Gmail connector in this repo and none is assumed. This script is
the transport that works anyway: paste the email text (or pipe a file), and it
matches each message to an application folder and updates its status.

    # see what it would do, change nothing (default)
    pbpaste | python3 scripts/email_status_update.py

    # actually write
    pbpaste | python3 scripts/email_status_update.py --apply

    # one message, company forced (when the text does not name it clearly)
    python3 scripts/email_status_update.py --company "Rho" --outcome rejected --apply

Messages are separated by a line of three or more dashes, or by a new "From:"
header, so you can paste several at once.

Deliberate limits, same spirit as gmail_intake.py:
  - **Dry run by default.** Nothing is written without --apply.
  - **Never downgrades a terminal status.** An application already Rejected is
    not moved back to Applied by a later "thanks for applying" autoresponder.
  - **Ambiguous matches are reported, not guessed.** If the company name hits
    two folders, it says so and skips.
  - **Bodies are not stored.** Only the outcome, the date, and a one-line
    subject go into the record.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys

APPS = pathlib.Path(__file__).resolve().parent.parent / "applications"

# Order matters: the first pattern that matches wins.
# Rejections are checked BEFORE interviews, because rejection language is far
# more formulaic and shares vocabulary with invitations. "We have decided to
# move forward with other candidates" is a rejection that reads as an interview
# invite to a naive matcher; that bug was caught on the first test run.
OUTCOME_PATTERNS = [
    ("offer", [
        r"\boffer of employment\b", r"\bpleased to offer\b", r"\bextend an offer\b",
    ]),
    ("rejected", [
        r"\bnot (?:be )?mov(?:e|ing) forward\b", r"\bdecided to move forward with other\b",
        r"\bwill not be proceeding\b", r"\bunfortunately\b[^.]{0,80}\b(?:not|other candidates)\b",
        r"\bnot selected\b", r"\bpursu(?:e|ing) other candidates\b",
        r"\bdecided not to (?:proceed|continue|move)\b", r"\bno longer under consideration\b",
        r"\bwe have filled\b", r"\bposition has been filled\b",
        # Added 2026-10-02 from a live Gmail scan that these patterns missed.
        r"\bgoing in a direction that better fits\b",
        r"\bdid not meet the minimum qualifications\b",
        r"\bcannot consider it\b",
        r"\bmoving forward with another candidate\b",
        r"\bnot an ideal fit\b", r"\bisn.t an ideal fit\b",
        r"\bwe (?:have )?closed the .{0,40}position\b",
        r"\bunable to move forward\b",
        r"\bnot (?:be )?proceeding with your\b",
        r"\bdecided not to proceed with your\b",
        r"\bkeep your (?:resume|application) on file\b",
        r"\bwish you (?:the best|luck)\b[^.]{0,60}\bsearch\b",
    ]),
    ("interview", [
        r"\bschedule (?:a|an|your) (?:call|interview|chat|conversation)\b",
        r"\binvite you to interview\b", r"\bset up (?:a|some) time\b",
        r"\bnext round\b", r"\bphone screen\b", r"\bhiring manager (?:call|chat)\b",
        r"\bwould love to (?:chat|talk|connect)\b",
        r"\bmove forward (?:with|to)\b(?![^.]{0,40}other (?:candidate|applicant))",
        # Added 2026-10-02: HireVue and other one-way video interview invites.
        r"\b(?:digital|video|one.way|recorded) interview\b",
        r"\bparticipate in a .{0,30}interview\b",
        r"\brecord a video response\b",
        r"\binvite you to (?:learn more|complete|take)\b",
    ]),
    ("assessment", [
        r"\bdesign (?:exercise|challenge)\b", r"\btake[- ]home\b",
        r"\bassessment\b", r"\bcoding challenge\b", r"\bportfolio review\b",
    ]),
    ("acknowledged", [
        r"\bthank you for applying\b", r"\bwe(?:'ve| have) received your application\b",
        r"\bapplication (?:has been )?received\b", r"\bthanks for your interest\b",
    ]),
]

STATUS_FOR = {
    "offer": "Offer",
    "interview": "Interviewing",
    "assessment": "Assessment requested",
    "rejected": "Rejected",
    "acknowledged": None,   # acknowledgement is not a state change
}

# Statuses we refuse to overwrite with something weaker.
TERMINAL = {"Rejected", "Offer", "Interviewing", "Assessment requested"}
RANK = {"Rejected": 3, "Assessment requested": 4, "Interviewing": 5, "Offer": 6}


def classify(text: str) -> str | None:
    low = text.lower()
    for outcome, pats in OUTCOME_PATTERNS:
        for p in pats:
            if re.search(p, low):
                return outcome
    return None


def split_messages(blob: str) -> list[str]:
    parts = re.split(r"\n-{3,}\n|\n(?=From:\s)", blob)
    return [p.strip() for p in parts if p.strip()]


def load_apps() -> list[tuple[pathlib.Path, str, str, str]]:
    """Return (path, company, title, status) for every application record."""
    out = []
    for md in sorted(APPS.glob("*/application.md")):
        head = md.read_text(encoding="utf-8", errors="ignore")[:2500]
        def field(name: str) -> str:
            m = re.search(rf"^{name}:\s*(.*)$", head, re.M)
            return (m.group(1).strip().strip("'\"") if m else "")
        out.append((md, field("company"), field("title"), field("status")))
    return out


def find_matches(text: str, apps, forced: str | None):
    """Match on company name. Word-boundary only, so 'Fort' never hits 'effort'."""
    hits = []
    for md, company, title, status in apps:
        name = forced or company
        if not name:
            continue
        if forced and forced.lower() != (company or "").lower():
            continue
        if not forced:
            if not re.search(rf"(?<![A-Za-z0-9]){re.escape(company)}(?![A-Za-z0-9])", text, re.I):
                continue
        hits.append((md, company, title, status))
    return hits


def subject_of(text: str) -> str:
    m = re.search(r"^Subject:\s*(.+)$", text, re.M)
    line = m.group(1) if m else text.strip().split("\n")[0]
    return line.strip()[:120]


def apply_update(md: pathlib.Path, new_status: str, subject: str, when: str) -> bool:
    body = md.read_text(encoding="utf-8")
    cur = re.search(r"^status:\s*(.*)$", body, re.M)
    cur_status = cur.group(1).strip().strip("'\"") if cur else ""
    if RANK.get(cur_status, 0) >= RANK.get(new_status, 0) and cur_status in TERMINAL:
        return False
    body = re.sub(r"^status:.*$", f"status: {new_status}", body, count=1, flags=re.M)
    if re.search(r"^outcome_date:", body, re.M):
        body = re.sub(r"^outcome_date:.*$", f"outcome_date: '{when}'", body, count=1, flags=re.M)
    else:
        body = re.sub(r"^(status: .*)$", rf"\1\noutcome_date: '{when}'", body, count=1, flags=re.M)
    body += (f"\n## Status update {when}\n\n"
             f"Set to **{new_status}** from an email the user pasted in.\n"
             f"Subject line: {subject}\n"
             f"(Only the outcome, date and subject are recorded. The body is not stored.)\n")
    md.write_text(body, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    ap.add_argument("--company", help="force the company when the text does not name it clearly")
    ap.add_argument("--folder", help="target exactly one application folder name. Use this, not "
                                     "--company, when a company has several open roles: --company "
                                     "alone picks the first match and that silently updated the "
                                     "wrong Amazon req once (2026-10-02)")
    ap.add_argument("--outcome", choices=list(STATUS_FOR), help="force the outcome")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--file", help="read from a file instead of stdin")
    a = ap.parse_args()

    blob = pathlib.Path(a.file).read_text(encoding="utf-8") if a.file else (
        "" if (a.company and a.outcome) and sys.stdin.isatty() else sys.stdin.read())
    messages = split_messages(blob) or [""]
    apps = load_apps()

    changed = skipped = unmatched = 0
    for msg in messages:
        outcome = a.outcome or classify(msg)
        if not outcome:
            print(f"  ?  no outcome detected: {subject_of(msg)[:70]!r}")
            unmatched += 1
            continue
        new_status = STATUS_FOR[outcome]
        if a.folder:
            hits = [t for t in apps if t[0].parent.name == a.folder]
            if not hits:
                print(f"  !  no folder named {a.folder!r}")
                unmatched += 1
                continue
        else:
            hits = find_matches(msg, apps, a.company)
        if not hits:
            print(f"  ?  no application matched: {subject_of(msg)[:70]!r}")
            unmatched += 1
            continue
        if len(hits) > 1 and not a.company:
            print(f"  !  {len(hits)} applications match {hits[0][1]!r}; rerun with --company and pick one:")
            for md, co, title, st in hits:
                print(f"       {md.parent.name}  [{st}]  {title}")
            skipped += 1
            continue
        md, co, title, st = hits[0]
        if new_status is None:
            print(f"  -  {co} / {title}: acknowledgement only, status left at {st}")
            skipped += 1
            continue
        if a.apply:
            ok = apply_update(md, new_status, subject_of(msg), a.date)
            print(("  OK " if ok else "  -  ") +
                  f"{co} / {title}: {st} -> {new_status}" + ("" if ok else "  (kept, already terminal)"))
            changed += ok
            skipped += (not ok)
        else:
            print(f"  DRY {co} / {title}: {st} -> {new_status}")
            changed += 1

    print(f"\n{changed} to change, {skipped} skipped, {unmatched} unmatched")
    if changed and not a.apply:
        print("Nothing written. Re-run with --apply, then: python3 scripts/build_tracker.py")
    elif changed:
        print("Now run: python3 scripts/build_tracker.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
