#!/usr/bin/env python3
"""Build and query a local, disposable index of job applications.

Application markdown remains the source of truth. This index keeps duplicate
checks and similar-resume lookup mechanical so agents do not need to load old
job descriptions into an LLM.

Usage:
    python3 scripts/job_index.py build
    python3 scripts/job_index.py lookup --url URL
    python3 scripts/job_index.py lookup --company NAME --title TITLE --jd-file JD
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APPLICATIONS_DIR = REPO_ROOT / "applications"
DEFAULT_OUTPUT = REPO_ROOT / ".job-agent" / "job-index.json"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
JOB_DESCRIPTION_RE = re.compile(
    r"^##\s+Job Description\s*$\n(.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
WORD_RE = re.compile(r"[a-z][a-z0-9+#.-]{2,}")
TRACKING_QUERY_KEYS = {
    "ref",
    "refid",
    "source",
    "src",
    "trackingid",
    "trk",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
STOPWORDS = {
    "about", "after", "also", "and", "are", "because", "been", "being",
    "between", "but", "can", "company", "for", "from", "have", "into",
    "job", "more", "our", "role", "that", "the", "their", "this", "through",
    "using", "what", "when", "where", "which", "will", "with", "work", "you",
    "your", "years", "including", "required", "preferred", "responsibilities",
    "qualifications", "experience", "candidate", "team", "position",
}
TERMINAL_PREFIXES = (
    "applied",
    "submitted",
    "rejected",
    "closed",
    "withdrawn",
    "offer",
    "interviewing",
)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def canonicalize_url(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.netloc:
        return value.rstrip("/")

    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"

    linkedin = re.search(r"/jobs/view/(\d+)", path, re.IGNORECASE)
    if host.endswith("linkedin.com") and linkedin:
        return f"https://linkedin.com/jobs/view/{linkedin.group(1)}"

    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not key.lower().startswith("utm_")
    ]
    query.sort()
    return urlunsplit((parts.scheme.lower() or "https", host, path, urlencode(query), ""))


def requisition_key(value: str | None) -> str:
    url = canonicalize_url(value)
    if not url:
        return ""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    segments = [part for part in parts.path.split("/") if part]

    patterns = (
        ("linkedin", r"/jobs/view/(\d+)", None),
        ("greenhouse", r"/jobs/(\d+)", r"/(?:jobs/)?([^/]+)/jobs/\d+"),
        ("icims", r"/jobs/(\d+)", None),
        ("adp", r"/(?:requisitions?|jobs?)/([A-Za-z0-9_-]+)", None),
    )
    for platform, pattern, board_pattern in patterns:
        if platform == "greenhouse" and "greenhouse" not in host:
            continue
        if platform == "linkedin" and "linkedin.com" not in host:
            continue
        if platform == "icims" and "icims.com" not in host:
            continue
        if platform == "adp" and "adp.com" not in host:
            continue
        match = re.search(pattern, parts.path, re.IGNORECASE)
        if match:
            board = ""
            if board_pattern:
                board_match = re.search(board_pattern, parts.path, re.IGNORECASE)
                board = f":{board_match.group(1).lower()}" if board_match else ""
            return f"{platform}{board}:{match.group(1).lower()}"

    if "ashbyhq.com" in host and len(segments) >= 2:
        return f"ashby:{segments[-2].lower()}:{segments[-1].lower()}"
    if "lever.co" in host and len(segments) >= 2:
        return f"lever:{segments[-2].lower()}:{segments[-1].lower()}"
    if "myworkdayjobs.com" in host:
        for segment in reversed(segments):
            if re.fullmatch(r"[A-Za-z]*R[-_A-Za-z0-9]+", segment):
                return f"workday:{host}:{segment.lower()}"
    return ""


def normalized_words(text: str) -> list[str]:
    words = {
        match.group(0).strip(".-")
        for match in WORD_RE.finditer(text.lower())
    }
    return sorted(word for word in words if word and word not in STOPWORDS)


def exact_fingerprint(text: str) -> str:
    normalized = " ".join(normalized_words(text))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def similarity(left: list[str], right: list[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def application_files(applications_dir: Path) -> list[Path]:
    if not applications_dir.is_dir():
        return []
    files: list[Path] = []
    for child in sorted(applications_dir.iterdir()):
        if child.name.startswith((".", "_")):
            continue
        if child.is_file() and child.suffix == ".md":
            files.append(child)
            continue
        if not child.is_dir():
            continue
        preferred = child / "application.md"
        if preferred.is_file():
            files.append(preferred)
            continue
        candidates = sorted(
            path for path in child.glob("*.md")
            if path.name not in {"resume-used.md", "cover-letter.md", "form-answers.md"}
        )
        if candidates:
            files.append(candidates[0])
    return files


def extract_job_description(text: str) -> str:
    match = JOB_DESCRIPTION_RE.search(text)
    return match.group(1).strip() if match else ""


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def make_entry(path: Path, applications_dir: Path) -> dict[str, object] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    data = parse_frontmatter(text)
    if not data:
        return None

    raw_urls = [
        data.get("canonical_url", ""),
        data.get("link", ""),
        data.get("linkedin_link", ""),
    ]
    urls = sorted({canonicalize_url(url) for url in raw_urls if url})
    requisitions = sorted({requisition_key(url) for url in raw_urls if requisition_key(url)})
    if data.get("requisition_id"):
        requisitions.append(f"declared:{data['requisition_id'].lower()}")
        requisitions = sorted(set(requisitions))

    jd = extract_job_description(text)
    folder = path.parent if path.parent != applications_dir else None
    has_resume = bool(folder and (folder / "resume-used.md").is_file())
    status = data.get("status", "")
    initial_score = data.get("initial_ats_score") or data.get("ats_score") or ""

    return {
        "application": display_path(path),
        "folder": display_path(folder) if folder else "",
        "company": data.get("company", ""),
        "title": data.get("title", ""),
        "company_words": normalized_words(data.get("company", "")),
        "title_words": normalized_words(data.get("title", "")),
        "status": status,
        "terminal": status.lower().startswith(TERMINAL_PREFIXES),
        "decision": data.get("decision", ""),
        "date_found": data.get("date_found", ""),
        "date_applied": data.get("date_applied", ""),
        "initial_ats_score": initial_score,
        "tailored_ats_score": data.get("tailored_ats_score", ""),
        "score_delta": data.get("score_delta", ""),
        "resume_used": data.get("resume_used", ""),
        "has_resume": has_resume,
        "canonical_url": canonicalize_url(data.get("canonical_url") or data.get("link")),
        "urls": urls,
        "requisition_keys": requisitions,
        "jd_fingerprint": data.get("jd_fingerprint") or exact_fingerprint(jd),
        "jd_words": normalized_words(jd),
        "active_verified_at": data.get("active_verified_at", ""),
        "linkedin_status": data.get("linkedin_status", ""),
    }


def build_index(applications_dir: Path, output: Path) -> dict[str, object]:
    entries = [
        entry
        for path in application_files(applications_dir)
        if (entry := make_entry(path, applications_dir)) is not None
    ]
    payload: dict[str, object] = {
        "version": 1,
        "applications_dir": str(applications_dir),
        "entries": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def load_or_build(applications_dir: Path, output: Path) -> dict[str, object]:
    files = application_files(applications_dir)
    newest_source = max((path.stat().st_mtime for path in files), default=0)
    if not output.is_file() or output.stat().st_mtime < newest_source:
        return build_index(applications_dir, output)
    try:
        return json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return build_index(applications_dir, output)


def public_entry(entry: dict[str, object], score: float | None = None) -> dict[str, object]:
    keys = (
        "application", "folder", "company", "title", "status", "terminal",
        "decision", "date_applied", "initial_ats_score", "tailored_ats_score",
        "score_delta", "resume_used", "has_resume", "canonical_url",
        "requisition_keys", "active_verified_at", "linkedin_status",
    )
    result = {key: entry.get(key, "") for key in keys}
    if score is not None:
        result["similarity"] = round(score, 3)
    return result


def lookup(
    payload: dict[str, object],
    url: str,
    company: str,
    title: str,
    jd_text: str,
    threshold: float,
    limit: int,
) -> dict[str, object]:
    entries = list(payload.get("entries", []))
    canonical = canonicalize_url(url)
    req_key = requisition_key(url)
    exact: list[dict[str, object]] = []
    for entry in entries:
        if canonical and canonical in entry.get("urls", []):
            exact.append(public_entry(entry))
            continue
        if req_key and req_key in entry.get("requisition_keys", []):
            exact.append(public_entry(entry))
    if exact:
        return {
            "match_type": "exact",
            "query": {"canonical_url": canonical, "requisition_key": req_key},
            "matches": exact,
        }

    company_words = normalized_words(company)
    title_words = normalized_words(title)
    jd_words = normalized_words(jd_text)
    candidates: list[tuple[float, dict[str, object]]] = []
    for entry in entries:
        company_score = similarity(company_words, entry.get("company_words", []))
        title_score = similarity(title_words, entry.get("title_words", []))
        jd_score = similarity(jd_words, entry.get("jd_words", []))
        if jd_words:
            score = 0.15 * company_score + 0.25 * title_score + 0.60 * jd_score
        else:
            score = 0.35 * company_score + 0.65 * title_score
        if score >= threshold and entry.get("has_resume"):
            candidates.append((score, entry))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return {
        "match_type": "similar" if candidates else "none",
        "query": {
            "canonical_url": canonical,
            "requisition_key": req_key,
            "company": company,
            "title": title,
            "has_jd": bool(jd_text),
        },
        "matches": [public_entry(entry, score) for score, entry in candidates[:limit]],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--applications-dir", type=Path, default=DEFAULT_APPLICATIONS_DIR)
    root.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Rebuild the disposable index")
    lookup_parser = sub.add_parser("lookup", help="Find an exact or similar prior job")
    lookup_parser.add_argument("--url", default="")
    lookup_parser.add_argument("--company", default="")
    lookup_parser.add_argument("--title", default="")
    lookup_parser.add_argument("--jd-file", type=Path)
    lookup_parser.add_argument("--threshold", type=float, default=0.55)
    lookup_parser.add_argument("--limit", type=int, default=3)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    applications_dir = args.applications_dir.resolve()
    output = args.output.resolve()
    if args.command == "build":
        payload = build_index(applications_dir, output)
        print(json.dumps({"output": str(output), "entries": len(payload["entries"])}))
        return 0

    jd_text = ""
    if args.jd_file:
        try:
            jd_text = args.jd_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(json.dumps({"error": str(exc)}))
            return 2
    payload = load_or_build(applications_dir, output)
    result = lookup(
        payload,
        args.url,
        args.company,
        args.title,
        jd_text,
        max(0.0, min(1.0, args.threshold)),
        max(1, args.limit),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
