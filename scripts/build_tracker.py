#!/usr/bin/env python3
"""
Builds TRACKER.md from the frontmatter of every application in applications/.

Deliberately dependency-free (no PyYAML) and deliberately not an LLM call -
this is a mechanical parsing task. Agents should run this script and read
its output (TRACKER.md) instead of opening every application file
themselves. See agents/06-tracker.md for the full policy.

Also prunes regenerable binaries. Markdown is the durable record; .docx,
.pdf and .html are build artifacts that can always be regenerated from
resume-used.md plus the source file in profile/resumes-docx/. Once a job
reaches a terminal status they are deleted so the repo does not accumulate
near-duplicate resumes.

Usage:
    python3 scripts/build_tracker.py           # build + prune
    python3 scripts/build_tracker.py --keep    # build, keep binaries
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLICATIONS_DIR = os.path.join(REPO_ROOT, "applications")
OUTPUT_FILE = os.path.join(REPO_ROOT, "TRACKER.md")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# statuses after which generated binaries are no longer needed
TERMINAL = {"applied", "rejected", "closed", "withdrawn", "offer",
            "interviewing", "submitted",
            # already-final states that do not split on " -"
            "already submitted on linkedin",
            "blocked \u2014 duplicate, 180-day reapply window"}
PRUNE_EXT = (".docx", ".pdf", ".html")

COLUMNS = [
    ("company", "Company"),
    ("title", "Role"),
    ("initial_ats_score", "Initial ATS"),
    ("tailored_ats_score", "Tailored"),
    ("decision", "Decision"),
    ("status", "Status"),
    ("date_applied", "Applied"),
]


def display_value(entry, key):
    """Return a tracker value while preserving older application records."""
    if key == "initial_ats_score":
        return entry.get("initial_ats_score") or entry.get("ats_score") or "-"
    return entry.get(key, "") or "-"


def parse_frontmatter(text):
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    data = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _read_entry(path, label):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    data = parse_frontmatter(text)
    if not data:
        return None
    data["_file"] = label
    return data


def collect_entries():
    """Scan both flat applications/*.md and per-job folders."""
    entries = []
    if not os.path.isdir(APPLICATIONS_DIR):
        return entries
    for name in sorted(os.listdir(APPLICATIONS_DIR)):
        if name.startswith((".", "_")):
            continue
        path = os.path.join(APPLICATIONS_DIR, name)

        if os.path.isdir(path):
            files = os.listdir(path)
            candidates = ["application.md"] + sorted(
                f for f in files
                if f.endswith(".md") and f not in
                ("application.md", "resume-used.md", "cover-letter.md",
                 "form-answers.md"))
            for cand in candidates:
                entry = _read_entry(os.path.join(path, cand),
                                    os.path.join(name, cand))
                if entry:
                    entry["_dir"] = name
                    entry["_has"] = {
                        "resume": "resume-used.md" in files,
                        "cover": "cover-letter.md" in files,
                        "form": "form-answers.md" in files,
                    }
                    entries.append(entry)
                    break
        elif name.endswith(".md"):
            entry = _read_entry(path, name)
            if entry:
                entry["_dir"] = None
                entry["_has"] = {}
                entries.append(entry)
    return entries


def prune_artifacts(entries):
    """Delete regenerable binaries for jobs that have reached a terminal state."""
    removed = []
    for e in entries:
        if not e.get("_dir"):
            continue
        if (e.get("status", "").strip().lower().split(" -")[0]
                not in TERMINAL):
            continue
        folder = os.path.join(APPLICATIONS_DIR, e["_dir"])
        for f in sorted(os.listdir(folder)):
            if f.endswith(PRUNE_EXT):
                try:
                    os.remove(os.path.join(folder, f))
                    removed.append(os.path.join(e["_dir"], f))
                except OSError:
                    pass
    return removed


def docs_cell(entry):
    d, has = entry.get("_dir"), entry.get("_has") or {}
    if not d:
        return "-"
    links = []
    if has.get("resume"):
        links.append(f"[resume](applications/{d}/resume-used.md)")
    if has.get("cover"):
        links.append(f"[cover letter](applications/{d}/cover-letter.md)")
    if has.get("form"):
        links.append(f"[answers](applications/{d}/form-answers.md)")
    return " · ".join(links) if links else "-"


def build_table(entries):
    header = ("| # | " + " | ".join(l for _, l in COLUMNS) +
              " | Documents | Posting |\n")
    header += "|---|" + "|".join(["---"] * (len(COLUMNS) + 2)) + "|\n"
    if not entries:
        return header + "| - | (no applications yet) |"
    rows = []
    for i, e in enumerate(entries, start=1):
        cells = [display_value(e, k) for k, _ in COLUMNS]
        link = e.get("link", "")
        posting = f"[link]({link})" if link else "-"
        rows.append(f"| {i} | " + " | ".join(cells) +
                    f" | {docs_cell(e)} | {posting} |")
    return header + "\n".join(rows)


def build_detail(entries):
    """One block per job so the tracker itself shows what was sent."""
    out = []
    for i, e in enumerate(entries, start=1):
        d = e.get("_dir")
        if not d:
            continue
        out.append(f"### {i}. {e.get('company','?')} — {e.get('title','?')}")
        bits = []
        initial_score = e.get("initial_ats_score") or e.get("ats_score")
        tailored_score = e.get("tailored_ats_score")
        if initial_score and tailored_score:
            delta = e.get("score_delta")
            delta_text = f" ({int(delta):+d})" if str(delta).lstrip("+-").isdigit() else ""
            bits.append(
                f"**{initial_score}%** initial -> **{tailored_score}%** tailored{delta_text}"
            )
        elif initial_score:
            bits.append(f"**{initial_score}%** initial match")
        if e.get("decision"):
            bits.append(f"decision: {e['decision']}")
        if e.get("resume_used"):
            bits.append(f"base resume: `{e['resume_used']}`")
        if e.get("apply_path"):
            bits.append(f"apply path: {e['apply_path']}")
        if e.get("location"):
            bits.append(e["location"])
        if bits:
            out.append(" · ".join(bits))
        out.append("")
        out.append(docs_cell(e).replace(" · ", " | "))
        if str(e.get("ai_detection_trap", "")).lower() == "true":
            out.append("")
            out.append("> This employer's form contained an AI-detection trap.")
        verification = []
        if e.get("active_verified_at"):
            verification.append(f"live verified {e['active_verified_at']}")
        if e.get("linkedin_status") == "no_equivalent_listing_found":
            checked = f" on {e['linkedin_checked_at']}" if e.get("linkedin_checked_at") else ""
            verification.append(f"no equivalent LinkedIn listing found{checked}")
        if verification:
            out.append("")
            out.append("Source verification: " + "; ".join(verification) + ".")
        out.append("")
    return "\n".join(out) if out else "_No application folders yet._\n"


def main():
    keep = "--keep" in sys.argv
    entries = collect_entries()
    removed = [] if keep else prune_artifacts(entries)

    content = (
        "# Application Tracker\n\n"
        "Auto-generated by `scripts/build_tracker.py`. Do not edit by hand -\n"
        "changes will be overwritten on the next run.\n\n"
        "Markdown is the durable record. The tailored resume and cover letter\n"
        "for every job are linked below and stay readable forever; the .docx\n"
        "and .pdf are build artifacts, regenerated only when a form needs a\n"
        "file to attach, and pruned once the job reaches a terminal status.\n\n"
        f"Total applications tracked: {len(entries)}\n\n"
        f"{build_table(entries)}\n\n"
        "## What was sent\n\n"
        f"{build_detail(entries)}"
    )
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Wrote {OUTPUT_FILE} with {len(entries)} entries.")
    if removed:
        print(f"Pruned {len(removed)} regenerable artifact(s):")
        for r in removed:
            print(f"  - {r}")


if __name__ == "__main__":
    sys.exit(main())
