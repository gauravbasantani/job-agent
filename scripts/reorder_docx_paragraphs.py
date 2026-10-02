#!/usr/bin/env python3
"""Reorder existing DOCX paragraphs without rebuilding their formatting."""

import argparse
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("order_file", type=Path)
    args = parser.parse_args()

    groups = json.loads(args.order_file.read_text(encoding="utf-8"))
    with zipfile.ZipFile(args.docx, "r") as source:
        files = {name: source.read(name) for name in source.namelist()}

    root = ET.fromstring(files["word/document.xml"])
    for prefixes in groups:
        parent_map = {child: parent for parent in root.iter() for child in parent}
        matches = []
        for paragraph in root.iter(f"{W}p"):
            text = paragraph_text(paragraph)
            for order, prefix in enumerate(prefixes):
                if text.startswith(prefix):
                    matches.append((order, parent_map[paragraph], paragraph))
                    break
        if len(matches) != len(prefixes):
            found = [paragraph_text(item[2])[:80] for item in matches]
            raise SystemExit(f"Expected {len(prefixes)} paragraphs, found {len(matches)}: {found}")
        parents = {id(item[1]) for item in matches}
        if len(parents) != 1:
            raise SystemExit("Paragraph group spans multiple DOCX containers")
        parent = matches[0][1]
        first_index = min(list(parent).index(item[2]) for item in matches)
        for _, _, paragraph in matches:
            parent.remove(paragraph)
        for offset, (_, _, paragraph) in enumerate(sorted(matches)):
            parent.insert(first_index + offset, paragraph)

    files["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    fd, temp_name = tempfile.mkstemp(suffix=".docx", dir=args.docx.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_name, "w", zipfile.ZIP_DEFLATED) as output:
            for name, data in files.items():
                output.writestr(name, data)
        os.replace(temp_name, args.docx)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


if __name__ == "__main__":
    main()
