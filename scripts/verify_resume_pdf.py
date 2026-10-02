#!/usr/bin/env python3
"""Verify a built resume PDF: page count and how far the ink reaches down page 1.

Usage: verify_resume_pdf.py 'applications/2026-09-11-*/*.pdf'

Two numbers matter:
  pages  must be 1. Counting "<page " in `pdftotext -bbox -f 1 -l 1` does NOT
         work -- it always returns 1 because the range is one page. Use pdfinfo.
  fill   max word yMax as a percentage of page height. Target 95-99% for a
         resume, calibrated against the Amazon Health build at 97.5%. A cover
         letter is exempt: 88-94% is correct there.
"""
import glob, subprocess, sys


def check(path):
    pages = int(subprocess.run(["pdfinfo", path], capture_output=True, text=True)
                 .stdout.split("Pages:")[1].split()[0])
    bb = subprocess.run(["pdftotext", "-bbox", "-f", "1", "-l", "1", path, "-"],
                        capture_output=True, text=True).stdout
    ys = [float(w.split('yMax="')[1].split('"')[0]) for w in bb.split("<word ")[1:]]
    height = float(bb.split('height="')[1].split('"')[0])
    fill = 100 * max(ys) / height if ys else 0.0
    tag = "OK" if pages == 1 and fill >= 95.0 else ("OVERFLOW" if pages > 1 else "SHORT")
    return pages, fill, tag


if __name__ == "__main__":
    for pattern in sys.argv[1:]:
        for path in sorted(glob.glob(pattern)):
            pages, fill, tag = check(path)
            print(f"  pages={pages}  fill={fill:5.1f}%  {tag:9s} {path}")
