#!/usr/bin/env python3
"""Add a small amount of breathing room after list paragraphs in a resume DOCX."""

import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def main() -> None:
    path = Path(sys.argv[1])
    after_twips = sys.argv[2] if len(sys.argv) > 2 else "24"
    with zipfile.ZipFile(path) as source:
        files = {name: source.read(name) for name in source.namelist()}

    root = ET.fromstring(files["word/document.xml"])
    changed = 0
    for paragraph in root.iter(W + "p"):
        props = paragraph.find(W + "pPr")
        if props is None or props.find(W + "numPr") is None:
            continue
        spacing = props.find(W + "spacing")
        if spacing is None:
            spacing = ET.SubElement(props, W + "spacing")
        spacing.set(W + "after", after_twips)
        changed += 1

    files["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    backup = path.with_suffix(path.suffix + ".pre-rhythm")
    shutil.copy2(path, backup)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in files.items():
            output.writestr(name, data)
    print(f"adjusted {changed} list paragraphs")


if __name__ == "__main__":
    main()
