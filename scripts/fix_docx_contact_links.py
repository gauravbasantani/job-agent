#!/usr/bin/env python3
"""Repair DOCX header contact hyperlinks.

Some source resumes have the visible contact line inside one LinkedIn hyperlink,
with empty portfolio/email hyperlink elements after it. This rewrites that line
so each visible contact item owns only its own hyperlink target.
"""

import argparse
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

LINKEDIN_TEXT = "linkedin.com/in/yourname"
PORTFOLIO_TEXT = "yourname.example.com"
GITHUB_TEXT = "github.com/yourname"
EMAIL_TEXT = "you@example.com"
PHONE_TEXT = "(555) 123-4567"

TARGETS = {
    LINKEDIN_TEXT: "https://www.linkedin.com/in/yourname",
    PORTFOLIO_TEXT: "https://yourname.example.com",
    GITHUB_TEXT: "https://github.com/yourname",
    EMAIL_TEXT: "mailto:you@example.com",
}

COMPACT_LABELS = {
    LINKEDIN_TEXT: "LinkedIn",
    PORTFOLIO_TEXT: "Portfolio",
    GITHUB_TEXT: "GitHub",
    EMAIL_TEXT: "Email",
}


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))


def next_rid(rels_root: ET.Element) -> str:
    max_seen = 0
    for rel in rels_root:
        rid = rel.attrib.get("Id", "")
        if rid.startswith("rId") and rid[3:].isdigit():
            max_seen = max(max_seen, int(rid[3:]))
    return f"rId{max_seen + 1}"


def ensure_relationship(rels_root: ET.Element, target: str) -> str:
    for rel in rels_root:
        if (
            rel.attrib.get("Type")
            == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
            and rel.attrib.get("Target") == target
        ):
            return rel.attrib["Id"]

    rid = next_rid(rels_root)
    ET.SubElement(
        rels_root,
        f"{REL}Relationship",
        {
            "Id": rid,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            "Target": target,
            "TargetMode": "External",
        },
    )
    return rid


def clone_run_props(paragraph: ET.Element) -> ET.Element | None:
    for run in paragraph.iter(f"{W}r"):
        props = run.find(f"{W}rPr")
        if props is not None:
            return ET.fromstring(ET.tostring(props))
    return None


def remove_empty_hyperlinks(root: ET.Element) -> None:
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for hyperlink in list(root.iter(f"{W}hyperlink")):
        if paragraph_text(hyperlink).strip():
            continue
        parent = parent_map.get(hyperlink)
        if parent is not None:
            parent.remove(hyperlink)


def repair_name_spacing(root: ET.Element) -> None:
    for paragraph in root.iter(f"{W}p"):
        if paragraph_text(paragraph).replace(" ", "") != "YourName":
            continue
        text_nodes = list(paragraph.iter(f"{W}t"))
        if not text_nodes:
            continue
        text_nodes[0].text = "Your Name"
        text_nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for node in text_nodes[1:]:
            node.text = ""


def make_run(text: str, props: ET.Element | None = None) -> ET.Element:
    run = ET.Element(f"{W}r")
    if props is not None:
        run.append(ET.fromstring(ET.tostring(props)))
    text_node = ET.SubElement(run, f"{W}t")
    text_node.text = text
    text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return run


def make_hyperlink(text: str, rid: str, props: ET.Element | None) -> ET.Element:
    hyperlink = ET.Element(f"{W}hyperlink", {f"{R}id": rid})
    hyperlink.append(make_run(text, props))
    return hyperlink


def repair_docx(path: Path, compact: bool = False) -> bool:
    with zipfile.ZipFile(path, "r") as source:
        files = {name: source.read(name) for name in source.namelist()}

    doc_root = ET.fromstring(files["word/document.xml"])
    rels_root = ET.fromstring(files["word/_rels/document.xml.rels"])
    remove_empty_hyperlinks(doc_root)
    repair_name_spacing(doc_root)

    contact_paragraph = None
    for paragraph in doc_root.iter(f"{W}p"):
        text = paragraph_text(paragraph)
        if LINKEDIN_TEXT in text and PORTFOLIO_TEXT in text and EMAIL_TEXT in text:
            contact_paragraph = paragraph
            break

    if contact_paragraph is None:
        return False

    had_github = GITHUB_TEXT in paragraph_text(contact_paragraph)
    props = clone_run_props(contact_paragraph)
    paragraph_props = contact_paragraph.find(f"{W}pPr")
    for child in list(contact_paragraph):
        if child is not paragraph_props:
            contact_paragraph.remove(child)

    linkedin_rid = ensure_relationship(rels_root, TARGETS[LINKEDIN_TEXT])
    portfolio_rid = ensure_relationship(rels_root, TARGETS[PORTFOLIO_TEXT])
    email_rid = ensure_relationship(rels_root, TARGETS[EMAIL_TEXT])

    linkedin_label = COMPACT_LABELS[LINKEDIN_TEXT] if compact else LINKEDIN_TEXT
    portfolio_label = COMPACT_LABELS[PORTFOLIO_TEXT] if compact else PORTFOLIO_TEXT
    email_label = COMPACT_LABELS[EMAIL_TEXT] if compact else EMAIL_TEXT
    github_label = COMPACT_LABELS[GITHUB_TEXT] if compact else GITHUB_TEXT

    contact_paragraph.append(make_hyperlink(linkedin_label, linkedin_rid, props))
    contact_paragraph.append(make_run(" | ", props))
    contact_paragraph.append(make_hyperlink(portfolio_label, portfolio_rid, props))
    contact_paragraph.append(make_run(" | ", props))

    # GitHub is included only when the source line already carried it, so
    # rebuilding an older resume never silently adds a link its author omitted.
    if had_github:
        github_rid = ensure_relationship(rels_root, TARGETS[GITHUB_TEXT])
        contact_paragraph.append(make_hyperlink(github_label, github_rid, props))
        contact_paragraph.append(make_run(" | ", props))

    contact_paragraph.append(make_hyperlink(email_label, email_rid, props))
    contact_paragraph.append(make_run(f"  | {PHONE_TEXT}", props))

    files["word/document.xml"] = ET.tostring(doc_root, encoding="utf-8", xml_declaration=True)
    files["word/_rels/document.xml.rels"] = ET.tostring(
        rels_root, encoding="utf-8", xml_declaration=True
    )

    fd, temp_name = tempfile.mkstemp(suffix=".docx", dir=path.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_name, "w", zipfile.ZIP_DEFLATED) as output:
            for name, data in files.items():
                output.writestr(name, data)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Use short visible labels while keeping individual hyperlink targets.",
    )
    args = parser.parse_args()
    changed = repair_docx(args.docx, compact=args.compact)
    print(f"{args.docx}: {'repaired' if changed else 'no matching contact line'}")


if __name__ == "__main__":
    main()
