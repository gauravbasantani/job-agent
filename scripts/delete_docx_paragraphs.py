#!/usr/bin/env python3
"""Delete complete DOCX paragraphs matched by text prefix."""

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
    parser.add_argument("prefixes_file", type=Path)
    args = parser.parse_args()

    prefixes = json.loads(args.prefixes_file.read_text(encoding="utf-8"))
    with zipfile.ZipFile(args.docx, "r") as source:
        files = {name: source.read(name) for name in source.namelist()}

    root = ET.fromstring(files["word/document.xml"])
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for prefix in prefixes:
        matches = [
            paragraph
            for paragraph in root.iter(f"{W}p")
            if paragraph_text(paragraph).startswith(prefix)
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"Expected one paragraph starting with {prefix!r}, found {len(matches)}"
            )
        parent_map[matches[0]].remove(matches[0])

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
