#!/usr/bin/env python3
"""Normalize a TextEdit-generated cover letter DOCX to a compact one-page layout."""

import argparse
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    args = parser.parse_args()

    with zipfile.ZipFile(args.docx, "r") as source:
        files = {name: source.read(name) for name in source.namelist()}

    root = ET.fromstring(files["word/document.xml"])
    size_map = {"40": "30", "28": "21", "25": "19"}
    for element in root.iter():
        if element.tag in {f"{W}sz", f"{W}sz-cs"}:
            value = element.get(f"{W}val")
            if value in size_map:
                element.set(f"{W}val", size_map[value])
        elif element.tag == f"{W}rFonts":
            for attribute in ("ascii", "hAnsi", "cs"):
                element.set(f"{W}{attribute}", "Calibri")
        elif element.tag == f"{W}spacing" and element.get(f"{W}after") == "160":
            element.set(f"{W}after", "100")

    section = root.find(f".//{W}sectPr")
    if section is None:
        raise SystemExit("DOCX section properties not found")
    margin = section.find(f"{W}pgMar")
    if margin is None:
        margin = ET.SubElement(section, f"{W}pgMar")
    margin.set(f"{W}top", "720")
    margin.set(f"{W}right", "936")
    margin.set(f"{W}bottom", "720")
    margin.set(f"{W}left", "936")
    margin.set(f"{W}header", "360")
    margin.set(f"{W}footer", "360")
    margin.set(f"{W}gutter", "0")

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
