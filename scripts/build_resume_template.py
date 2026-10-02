#!/usr/bin/env python3
"""Build a correctly formatted resume template from a source .docx in profile/.

The originals in profile/resumes-docx/ carry the right fonts and bold emphasis but
three defects that make the exported PDF read badly:

  1. The header contact line has underline applied to the whole paragraph, so the
     " | " separators and the phone number are underlined as if they were links.
  2. The font hierarchy is flat and too small: 12pt name, 10.5pt section headers,
     10pt job titles, 9pt body, 8pt skills. resume-output-spec.md requires
     10.5-11pt body.
  3. Job title/date and company/location lines are right-aligned with hand counted
     literal spaces tuned to the old small font. Raise the font and the dates wrap
     to a second line.

This rebuilds all three: underline only on real hyperlinks, a real hierarchy, and
proper right tab stops that hold at any font size. Output is the editable base for
per-job tailoring via delete/reorder/replace_docx_paragraphs.py.

Usage:
  python3 scripts/build_resume_template.py \
      --source "profile/resumes-docx/Your_Name_Resume Product Designer.docx" \
      --output .job-agent/resume-template.docx
"""

import argparse
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

SECTION_HEADERS = [4, 6, 34, 40, 48]
BODY_PARAGRAPHS = [5, 9, 10, 11, 12, 13, 17, 18, 19, 23, 24, 25, 26, 30, 31, 32,
                   35, 36, 37, 38, 41, 42, 43, 44, 45, 46, 49, 50, 51]
# (paragraph index, left text, right text, bold, half-point size)
TAB_LINES = [
    (7, "Product Designer", "May 2024 – Present", True, 22),
    (8, "Your Current Employer (Your University)", "Your City", False, 21),
    (15, "UX Designer", "Oct 2025 – Dec 2025", True, 22),
    (16, "Company B", "Remote, Boston, MA, USA", False, 21),
    (21, "UX Designer", "Jan 2023 - Jul 2023", True, 22),
    (22, "Company C", "Your City", False, 21),
    (28, "Product Designer", "Jun 2022 - Dec 2022", True, 22),
    (29, "Company D", "Your City", False, 21),
]
RIGHT_TAB_POS = "11240"


def set_size(paragraph, half_points):
    for run in paragraph.iter(f"{W}r"):
        rpr = run.find(f"{W}rPr")
        if rpr is None:
            continue
        for tag in (f"{W}sz", f"{W}szCs"):
            node = rpr.find(tag)
            if node is not None:
                node.set(f"{W}val", str(half_points))


def make_rpr(bold, half_points):
    rpr = ET.Element(f"{W}rPr")
    if bold:
        ET.SubElement(rpr, f"{W}b").set(f"{W}val", "1")
        ET.SubElement(rpr, f"{W}bCs").set(f"{W}val", "1")
    ET.SubElement(rpr, f"{W}sz").set(f"{W}val", str(half_points))
    ET.SubElement(rpr, f"{W}szCs").set(f"{W}val", str(half_points))
    ET.SubElement(rpr, f"{W}rtl").set(f"{W}val", "0")
    return rpr


def strip_contact_underline(paragraph):
    """Underline belongs on the three hyperlinks, not the separators or phone."""
    for child in list(paragraph):
        if child.tag == f"{W}r":
            rpr = child.find(f"{W}rPr")
            if rpr is None:
                continue
            underline = rpr.find(f"{W}u")
            if underline is not None:
                rpr.remove(underline)
            for tag in (f"{W}sz", f"{W}szCs"):
                node = rpr.find(tag)
                if node is not None:
                    node.set(f"{W}val", "20")
        elif child.tag == f"{W}hyperlink":
            for run in child.iter(f"{W}r"):
                rpr = run.find(f"{W}rPr")
                if rpr is None:
                    continue
                for tag in (f"{W}sz", f"{W}szCs"):
                    node = rpr.find(tag)
                    if node is not None:
                        node.set(f"{W}val", "20")

    ppr = paragraph.find(f"{W}pPr")
    if ppr is not None:
        mark = ppr.find(f"{W}rPr")
        if mark is not None:
            underline = mark.find(f"{W}u")
            if underline is not None:
                mark.remove(underline)
            for tag in (f"{W}sz", f"{W}szCs"):
                node = mark.find(tag)
                if node is not None:
                    node.set(f"{W}val", "20")


def rebuild_tab_line(paragraph, left_text, right_text, bold, half_points):
    """Replace space padding with a real right tab stop at the margin."""
    for child in list(paragraph):
        if child.tag in (f"{W}r", f"{W}hyperlink"):
            paragraph.remove(child)

    ppr = paragraph.find(f"{W}pPr")
    if ppr is None:
        ppr = ET.Element(f"{W}pPr")
        paragraph.insert(0, ppr)
    old_tabs = ppr.find(f"{W}tabs")
    if old_tabs is not None:
        ppr.remove(old_tabs)
    tabs = ET.Element(f"{W}tabs")
    tab = ET.SubElement(tabs, f"{W}tab")
    tab.set(f"{W}val", "right")
    tab.set(f"{W}leader", "none")
    tab.set(f"{W}pos", RIGHT_TAB_POS)
    ppr.insert(0, tabs)
    mark = ppr.find(f"{W}rPr")
    if mark is not None:
        ppr.remove(mark)
    ppr.append(make_rpr(bold, half_points))

    left = ET.SubElement(paragraph, f"{W}r")
    left.append(make_rpr(bold, half_points))
    left_t = ET.SubElement(left, f"{W}t")
    left_t.set(XML_SPACE, "preserve")
    left_t.text = left_text

    right = ET.SubElement(paragraph, f"{W}r")
    right.append(make_rpr(bold, half_points))
    ET.SubElement(right, f"{W}tab")
    right_t = ET.SubElement(right, f"{W}t")
    right_t.set(XML_SPACE, "preserve")
    right_t.text = right_text


def normalize_tab_stops(root):
    """Every right tab stop must sit at the same margin.

    The Education and Relevant Projects lines carry their own right tab stops from
    the source file, set for the original page margins. Rebuilding only the
    experience lines left those two sections about a third of an inch short of the
    right edge, so dates and CGPA did not line up with the job dates above them.
    """
    moved = 0
    for tab in root.iter(f"{W}tab"):
        pos = tab.get(f"{W}pos")
        if pos and pos != RIGHT_TAB_POS:
            tab.set(f"{W}pos", RIGHT_TAB_POS)
            moved += 1
    return moved


def trim_text(paragraph, needle, replacement=""):
    for run in paragraph.iter(f"{W}r"):
        node = run.find(f"{W}t")
        if node is not None and node.text and needle in node.text:
            node.text = node.text.replace(needle, replacement)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(args.source, args.output)

    with zipfile.ZipFile(args.output, "r") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}

    root = ET.fromstring(files["word/document.xml"])
    paragraphs = list(root.iter(f"{W}p"))
    if len(paragraphs) < 51:
        raise SystemExit(
            f"Expected the 51-paragraph source layout, found {len(paragraphs)}. "
            "Point --source at an unedited resume in profile/resumes-docx/."
        )

    strip_contact_underline(paragraphs[1])
    for index in SECTION_HEADERS:
        set_size(paragraphs[index - 1], 24)
    for index in BODY_PARAGRAPHS:
        set_size(paragraphs[index - 1], 21)
    for index, left, right, bold, size in TAB_LINES:
        rebuild_tab_line(paragraphs[index - 1], left, right, bold, size)
    realigned = normalize_tab_stops(root)

    # Two low-value keywords trimmed so the fuller page still fits one sheet.
    trim_text(paragraphs[49], "After Effects, ")
    trim_text(paragraphs[48], "Journey mapping, ")

    margins = root.find(f".//{W}sectPr").find(f"{W}pgMar")
    margins.set(f"{W}top", "400")
    margins.set(f"{W}bottom", "150")
    margins.set(f"{W}left", "500")
    margins.set(f"{W}right", "500")

    files["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)

    print(f"{args.output}: template built, {realigned} tab stop(s) realigned to the margin")


if __name__ == "__main__":
    main()
