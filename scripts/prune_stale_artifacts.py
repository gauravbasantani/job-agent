#!/usr/bin/env python3
"""Delete regenerable binaries (.docx/.pdf/.html) from stale application folders.

`build_tracker.py` already prunes folders in a TERMINAL state (applied,
rejected, closed, withdrawn, offer). This covers the other case: folders that
never reached a terminal state and have gone stale — "Ready to apply",
"Tailored", "Blocked", "Prepared" and so on — where the binaries are still
sitting on disk months later.

Nothing is lost. resume-used.md and cover-letter.md are the sources the DOCX is
built from, so anything deleted here regenerates in under a minute:

    python3 scripts/build_tailored_docx.py <dir>/resume-used.md <dir>/<name>.docx
    python3 scripts/fix_docx_contact_links.py <dir>/<name>.docx
    ./scripts/export_docx_to_pdf.sh <dir>/<name>.docx <dir>/<name>.pdf

Usage:
    prune_stale_artifacts.py --before 2026-09-04      # folders dated on or before
    prune_stale_artifacts.py --older-than 21          # folders older than N days
    prune_stale_artifacts.py --before 2026-09-04 --dry-run
"""
import argparse, datetime, glob, os

EXT = (".docx", ".pdf", ".html")
APPS = "applications"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", help="prune folders dated on or before YYYY-MM-DD")
    ap.add_argument("--older-than", type=int, help="prune folders older than N days")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.older_than is not None:
        cut = (datetime.date.today() - datetime.timedelta(days=a.older_than)).isoformat()
    elif a.before:
        cut = a.before
    else:
        raise SystemExit("give --before YYYY-MM-DD or --older-than N")

    n = freed = folders = 0
    for md in sorted(glob.glob(f"{APPS}/*/application.md")):
        d = os.path.dirname(md)
        if os.path.basename(d)[:10] > cut:
            continue
        hits = [p for p in os.listdir(d) if p.lower().endswith(EXT)]
        if not hits:
            continue
        folders += 1
        for p in hits:
            fp = os.path.join(d, p)
            freed += os.path.getsize(fp)
            n += 1
            if not a.dry_run:
                os.remove(fp)
    verb = "would prune" if a.dry_run else "pruned"
    print(f"{verb} {n} files from {folders} folders, {freed/1024/1024:.1f} MB (cutoff {cut})")


if __name__ == "__main__":
    main()
