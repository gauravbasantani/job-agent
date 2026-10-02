#!/usr/bin/env python3
"""Parse job-agent commands and generate direct-source search queries."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys


SUPPORTED_JOB_BOARDS = {
    "adp": ("ADP", ["workforcenow.adp.com"]),
    "ashby": ("Ashby", ["jobs.ashbyhq.com"]),
    "greenhouse": ("Greenhouse", ["job-boards.greenhouse.io", "boards.greenhouse.io"]),
    "icims": ("iCIMS", ["icims.com/jobs"]),
    "lever": ("Lever", ["jobs.lever.co"]),
    "linkedin": ("LinkedIn", ["linkedin.com/jobs/view"]),
    "smartrecruiters": ("SmartRecruiters", ["jobs.smartrecruiters.com"]),
    "workday": ("Workday", ["myworkdayjobs.com"]),
}
BOARD_ALIASES = {
    "green house": "greenhouse",
    "smart recruiters": "smartrecruiters",
    "work day": "workday",
}
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
FILTER_RE = re.compile(
    r"\b(job_title|jobboard|company_page|not_on_linkedin)\s*:\s*(\"[^\"]*\"|'[^']*'|[^\s]*)",
    re.IGNORECASE,
)


def bool_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_board(value: str) -> str | None:
    key = re.sub(r"\s+", " ", value.strip().lower())
    key = BOARD_ALIASES.get(key, key)
    return key if key in SUPPORTED_JOB_BOARDS else None


def command_intent(text: str) -> str:
    lowered = text.strip().lower()
    if lowered.startswith("force tailor"):
        return "force_tailor"
    first = lowered.split(maxsplit=1)[0] if lowered else ""
    return {
        "apply": "apply",
        "check": "check",
        "continue": "continue",
        "fill": "apply",
        "find": "find",
        "list": "find",
        "prepare": "apply",
        "search": "find",
        "show": "find",
        "submit": "submit",
    }.get(first, "unknown")


JOB_KEY_INTENTS = {"continue", "submit"}
LEADING_WORDS_RE = re.compile(
    r"^\s*(force tailor|continue|submit|apply|check|fill|prepare|find|search|list|show)\b",
    re.IGNORECASE,
)


def slugify_job_key(value: str) -> str:
    """Normalize a spoken job reference into the stable browser job key."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:120]


def extract_job_key(text: str, intent: str) -> str:
    """Pull the job reference out of `continue {job}` / `submit {job}`.

    The browser tab map, application folder, and tracker all key off this
    slug, so `submit Eudia Product Designer` and `submit
    eudia-product-designer` must resolve to the same job.
    """
    if intent not in JOB_KEY_INTENTS:
        return ""
    remainder = LEADING_WORDS_RE.sub("", text, count=1)
    remainder = FILTER_RE.sub(" ", remainder)
    remainder = URL_RE.sub(" ", remainder)
    # Strip the filler a person naturally speaks around the job reference, so
    # "submit the Eudia Product Designer application" and the bare slug agree.
    remainder = re.sub(r"^\s*(the|this|that|my|for)\b\s*", " ", remainder, flags=re.IGNORECASE)
    remainder = re.sub(r"^\s*(job|application|role|posting)\b\s*", " ", remainder, flags=re.IGNORECASE)
    remainder = re.sub(r"\s*\b(application|job|role|posting)\s*$", " ", remainder, flags=re.IGNORECASE)
    remainder = remainder.strip().strip("{}[]()\"'")
    return slugify_job_key(remainder)


def parse_command(text: str) -> dict[str, object]:
    filters: dict[str, str] = {}
    for match in FILTER_RE.finditer(text):
        raw = match.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        filters[match.group(1).lower()] = raw

    lowered = text.lower()
    not_on_linkedin = bool_value(filters.get("not_on_linkedin", ""))
    if "not on linkedin" in lowered or "not listed on linkedin" in lowered:
        not_on_linkedin = True
    company_page = bool_value(filters.get("company_page", ""))
    if "company page" in lowered or "company careers" in lowered:
        company_page = True

    board_value = filters.get("jobboard", "")
    requested_boards = []
    unknown_boards = []
    if board_value:
        for item in board_value.split(","):
            normalized = normalize_board(item)
            if normalized and normalized not in requested_boards:
                requested_boards.append(normalized)
            elif item.strip():
                unknown_boards.append(item.strip())
    else:
        requested_boards = [key for key in SUPPORTED_JOB_BOARDS if key != "linkedin"]

    if not_on_linkedin:
        requested_boards = [board for board in requested_boards if board != "linkedin"]

    url_match = URL_RE.search(text)
    url = url_match.group(0).rstrip(".,);]") if url_match else ""
    job_title = filters.get("job_title", "").strip()
    intent = command_intent(text)

    return {
        "intent": intent,
        "url": url,
        "job_key": extract_job_key(text, intent),
        "job_title": job_title,
        "jobboards": requested_boards,
        "jobboard_labels": [SUPPORTED_JOB_BOARDS[key][0] for key in requested_boards],
        "unknown_jobboards": unknown_boards,
        "company_page": company_page,
        "not_on_linkedin": not_on_linkedin,
    }


def search_queries(parsed: dict[str, object]) -> list[str]:
    title = str(parsed.get("job_title") or "").strip()
    if not title:
        return []
    quoted_title = f'"{title}"'
    queries = []
    for board in parsed.get("jobboards", []):
        for domain in SUPPORTED_JOB_BOARDS[str(board)][1]:
            queries.append(f"{quoted_title} site:{domain}")
    if parsed.get("company_page"):
        queries.append(f'{quoted_title} (careers OR "open positions")')
    return queries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command_text", nargs="+")
    args = parser.parse_args(argv)
    text = " ".join(args.command_text)
    parsed = parse_command(text)
    parsed["search_queries"] = search_queries(parsed)
    print(json.dumps(parsed, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
