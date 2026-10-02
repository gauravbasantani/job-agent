#!/usr/bin/env python3
"""Reduce a cover letter DOCX's top and bottom page margins.

Usage: tighten_cover_letter_margins.py <docx> [twips]   (1440 twips = 1 inch)

The base cover-letter template uses 1 inch (1440 twips) on all four sides,
which costs roughly five lines of vertical space and pushes a five-paragraph
letter onto a second page. This drops top and bottom to 0.75 inch (1080) and
leaves LEFT and RIGHT untouched on purpose: changing the text width would
re-wrap every line and invalidate any length tuning already done.

Run after build_cover_letter_docx.py, before the Word PDF export.
"""
import os, re, sys, tempfile, zipfile

DEFAULT_TOP_BOTTOM = "1080"


def main(path, top_bottom=DEFAULT_TOP_BOTTOM):
    with zipfile.ZipFile(path) as src:
        files = {n: src.read(n) for n in src.namelist()}
    doc = files["word/document.xml"].decode("utf-8")
    if "<w:pgMar" not in doc:
        raise SystemExit(f"{path}: no page margins found")
    def fix(m):
        tag = m.group(0)
        tag = re.sub(r'w:top="\d+"', f'w:top="{top_bottom}"', tag)
        tag = re.sub(r'w:bottom="\d+"', f'w:bottom="{top_bottom}"', tag)
        return tag
    doc = re.sub(r"<w:pgMar[^/]*/>", fix, doc)
    files["word/document.xml"] = doc.encode("utf-8")
    fd, tmp = tempfile.mkstemp(suffix=".docx", dir=os.path.dirname(path) or ".")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for n, d in files.items():
                out.writestr(n, d)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(f"tightened top/bottom margins to {int(top_bottom)/1440:.3g}in in {path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TOP_BOTTOM)
