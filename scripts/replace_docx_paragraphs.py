#!/usr/bin/env python3
"""Replace complete DOCX paragraph text while preserving paragraph styling."""

import argparse
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("replacements_file", type=Path)
    args = parser.parse_args()

    replacements = json.loads(args.replacements_file.read_text(encoding="utf-8"))
    with zipfile.ZipFile(args.docx, "r") as source:
        files = {name: source.read(name) for name in source.namelist()}

    root = ET.fromstring(files["word/document.xml"])
    for prefix, replacement in replacements.items():
        matches = [paragraph for paragraph in root.iter(f"{W}p") if paragraph_text(paragraph).startswith(prefix)]
        if len(matches) != 1:
            raise SystemExit(f"Expected one paragraph starting with {prefix!r}, found {len(matches)}")
        text_nodes = list(matches[0].iter(f"{W}t"))
        if not text_nodes:
            raise SystemExit(f"Paragraph starting with {prefix!r} has no text nodes")
        text_nodes[0].text = replacement
        text_nodes[0].set(f"{XML}space", "preserve")
        for node in text_nodes[1:]:
            node.text = ""

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
