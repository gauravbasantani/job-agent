#!/usr/bin/env python3
"""Insert DOCX paragraphs after matched text prefixes, copying paragraph style."""

import argparse
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()


def set_paragraph_text(paragraph: ET.Element, text: str) -> None:
    text_nodes = list(paragraph.iter(f"{W}t"))
    if not text_nodes:
        run = paragraph.find(f"{W}r")
        if run is None:
            run = ET.SubElement(paragraph, f"{W}r")
        text_nodes = [ET.SubElement(run, f"{W}t")]
    text_nodes[0].text = text
    text_nodes[0].set(f"{XML}space", "preserve")
    for node in text_nodes[1:]:
        node.text = ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("insertions_file", type=Path)
    args = parser.parse_args()

    insertions = json.loads(args.insertions_file.read_text(encoding="utf-8"))
    with zipfile.ZipFile(args.docx, "r") as source:
        files = {name: source.read(name) for name in source.namelist()}

    root = ET.fromstring(files["word/document.xml"])
    for item in insertions:
        after_prefix = item["after_prefix"]
        style_prefix = item.get("style_prefix") or after_prefix
        parent_map = {child: parent for parent in root.iter() for child in parent}
        after_matches = [
            p for p in root.iter(f"{W}p") if paragraph_text(p).startswith(after_prefix)
        ]
        style_matches = [
            p for p in root.iter(f"{W}p") if paragraph_text(p).startswith(style_prefix)
        ]
        if len(after_matches) != 1:
            raise SystemExit(f"Expected one paragraph starting with {after_prefix!r}, found {len(after_matches)}")
        if len(style_matches) != 1:
            raise SystemExit(f"Expected one style paragraph starting with {style_prefix!r}, found {len(style_matches)}")
        new_paragraph = deepcopy(style_matches[0])
        set_paragraph_text(new_paragraph, item["text"])
        parent = parent_map[after_matches[0]]
        parent.insert(list(parent).index(after_matches[0]) + 1, new_paragraph)

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
