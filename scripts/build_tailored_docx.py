#!/usr/bin/env python3
"""Build a tailored .docx from the base resume skeleton + tailored markdown.

Sets paragraph text by INDEX (no prefix collisions) and rebuilds inline bold
in the original's style: bold lead verb phrase + bold metric spans. Skills
lines keep their bold label run and only the list run is replaced.
"""
import copy, re, shutil, sys, zipfile, os
import xml.etree.ElementTree as ET
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML = "{http://www.w3.org/XML/1998/namespace}"
# Do NOT register a default namespace: attributes would lose their w: prefix
# (w:val -> val), which Word treats as invalid. Let ET emit ns0:/ns1: as the
# original file does.

BASE = "profile/resumes-docx/Amazon Propelus Kajabi  Your_Name_Resume Product Designer.docx"

# base skeleton indices
CONTACT = 1
SUMMARY = 4
Your University = [8, 9, 10, 11, 12]
COMPANY_B = [16, 17, 18]
TCOG = [22, 23, 24, 25]
COMPANY_D = [29, 30, 31]
P1H, P1B = 40, [41, 42]
P2H, P2B = 43, [44, 45]
SKILLS = [48, 49, 50]

STOP = r"(?!and\b|while\b|through\b|by\b|as\b|for\b|of\b|instead\b|that\b|with\b|so\b)"
METRIC = re.compile(
    r"(?<![A-Za-z0-9-])"                                # not K-12, not word- or digit-adjacent
    r"\$?\d[\d,.]*\s*(?:%|K|M|\+)?"                     # the number itself
    r"(?:\s+(?:to|from)\s+\$?\d[\d,.]*\s*%?)?"          # ranges: 60% to 85%
    r"(?:\s+" + STOP + r"[a-zA-Z][\w/-]*){0,3}"         # up to 3 trailing words
)


def parse_md(path):
    txt = Path(path).read_text(encoding="utf-8")
    lines = txt.split("\n")
    out = {"summary": "", "roles": [], "projects": [], "skills": [], "contact": ""}
    for ln in lines[:4]:
        if "@" in ln and "|" in ln:
            out["contact"] = ln.strip(); break
    sec = None
    cur_role = None
    cur_proj = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "SUMMARY":
            sec = "sum"; continue
        if s == "PROFESSIONAL EXPERIENCE":
            sec = "exp"; continue
        if s == "EDUCATION":
            sec = "edu"; continue
        if s == "RELEVANT PROJECTS":
            sec = "proj"; continue
        if s == "TECHNICAL SKILLS":
            sec = "skills"; continue
        if not s:
            continue
        if sec == "sum" and not out["summary"]:
            out["summary"] = s
        elif sec == "exp":
            if s.startswith("- "):
                if cur_role is not None:
                    cur_role.append(s[2:])
            elif re.match(r"^(Product Designer|UX Designer|User Experience Designer|UI/UX Designer|Senior Product Designer|Design Engineer)\s{2,}", ln):
                cur_role = []
                out["roles"].append(cur_role)
        elif sec == "proj":
            if s.startswith("- "):
                if cur_proj is not None:
                    cur_proj["bullets"].append(s[2:])
            else:
                cur_proj = {"heading": ln.rstrip(), "bullets": []}
                out["projects"].append(cur_proj)
        elif sec == "skills":
            out["skills"].append(s)
    return out


MASK = ""  # private-use placeholder so "0 to 1" is never read as a metric


def segments(text):
    """Return [(is_bold, chunk)] — bold lead verb phrase + metric spans."""
    text = text.replace("0 to 1", MASK * 6)
    words = text.split(" ")
    lead_n = 2 if len(words) > 3 else 1
    lead = " ".join(words[:lead_n])
    rest = text[len(lead):]
    segs = [(True, lead)]
    pos = 0
    for m in METRIC.finditer(rest):
        a, b = m.span()
        chunk = m.group().rstrip(" ,.;")
        if not any(ch.isdigit() for ch in chunk):
            continue
        b = a + len(chunk)
        if a > pos:
            segs.append((False, rest[pos:a]))
        segs.append((True, chunk))
        pos = b
    if pos < len(rest):
        segs.append((False, rest[pos:]))
    return [(bold, c.replace(MASK * 6, "0 to 1")) for bold, c in segs if c]


def clear_runs(p):
    """Remove every run under p, including runs nested in w:hyperlink etc."""
    parents = {id(c): par for par in p.iter() for c in par}
    for r in list(p.iter(W + "r")):
        par = parents.get(id(r))
        if par is not None:
            par.remove(r)
    for h in list(p.iter(W + "hyperlink")):
        par = parents.get(id(h))
        if par is not None and len(h) == 0:
            par.remove(h)


def set_runs(p, text, bold_template, plain_template, rebuild_bold=True):
    clear_runs(p)
    segs = segments(text) if rebuild_bold else [(False, text)]
    for is_bold, chunk in segs:
        run = copy.deepcopy(bold_template if is_bold else plain_template)
        for t in list(run.findall(W + "t")):
            run.remove(t)
        t = ET.SubElement(run, W + "t")
        t.text = chunk
        t.set(XML + "space", "preserve")
        p.append(run)


def set_heading_with_tab(p, text, template):
    """Write a project heading, restoring the right-aligned tab before the date.

    The base paragraph carries a right tab stop (pPr/tabs/tab @ 10800) and the
    date run begins with a <w:tab/>. Writing plain text runs destroys that, so
    the date drifts to wherever the source spaces happen to land. Split the
    markdown line on its run of spaces and re-emit the tab element.
    """
    clear_runs(p)
    parts = re.split(r"\s{2,}", text.strip())
    title = parts[0]
    date = parts[-1] if len(parts) > 1 else ""

    run = copy.deepcopy(template)
    for t in list(run.findall(W + "t")):
        run.remove(t)
    t = ET.SubElement(run, W + "t")
    t.text = title
    t.set(XML + "space", "preserve")
    p.append(run)

    if date:
        drun = copy.deepcopy(template)
        for t in list(drun.findall(W + "t")):
            drun.remove(t)
        ET.SubElement(drun, W + "tab")
        t = ET.SubElement(drun, W + "t")
        t.text = date
        t.set(XML + "space", "preserve")
        p.append(drun)


def build(md_path, out_docx, plan):
    shutil.copy(BASE, out_docx)
    with zipfile.ZipFile(out_docx, "r") as z:
        files = {n: z.read(n) for n in z.namelist()}
    root = ET.fromstring(files["word/document.xml"])
    paras = list(root.iter(W + "p"))

    # harvest run templates
    bold_t = plain_t = None
    for run in paras[8].findall(W + "r"):
        b = run.find(W + "rPr/" + W + "b")
        if b is not None and b.get(W + "val") == "1" and bold_t is None:
            bold_t = run
        elif (b is None or b.get(W + "val") != "1") and plain_t is None:
            plain_t = run
    plain_sum = paras[SUMMARY].find(W + "r")

    md = parse_md(md_path)
    kill = set()

    # contact line — written from the markdown so additions like GitHub survive.
    # fix_docx_contact_links.py re-applies hyperlinks afterwards.
    if md.get("contact"):
        set_runs(paras[CONTACT], md["contact"], plain_sum, plain_sum, rebuild_bold=False)

    # summary (no bold rebuild — original summary is unbolded)
    set_runs(paras[SUMMARY], md["summary"], plain_sum, plain_sum, rebuild_bold=False)

    # experience
    for slot_ids, bullets in zip([Your University, COMPANY_B, TCOG, COMPANY_D], md["roles"]):
        for j, pid in enumerate(slot_ids):
            if j < len(bullets):
                set_runs(paras[pid], bullets[j], bold_t, plain_t)
            else:
                kill.add(pid)

    # projects
    for (hid, bids), proj in zip([(P1H, P1B), (P2H, P2B)], md["projects"]):
        set_heading_with_tab(paras[hid], proj["heading"], bold_t)
        for j, pid in enumerate(bids):
            if j < len(proj["bullets"]):
                set_runs(paras[pid], proj["bullets"][j], bold_t, plain_t)
            else:
                kill.add(pid)

    # skills — keep bold label run, replace only the list run
    for pid, line in zip(SKILLS, md["skills"]):
        label, _, rest = line.partition(": ")
        p = paras[pid]
        runs = list(p.iter(W + "r"))
        clear_runs(p)
        rb = copy.deepcopy(runs[0])
        for t in list(rb.findall(W + "t")):
            rb.remove(t)
        t = ET.SubElement(rb, W + "t"); t.text = label + ": "; t.set(XML + "space", "preserve")
        p.append(rb)
        rp = copy.deepcopy(plain_t)
        for t in list(rp.findall(W + "t")):
            rp.remove(t)
        t = ET.SubElement(rp, W + "t"); t.text = rest; t.set(XML + "space", "preserve")
        p.append(rp)

    # delete surplus paragraphs
    for parent in root.iter():
        for child in list(parent):
            if child.tag == W + "p" and id(child) in {id(paras[i]) for i in kill}:
                parent.remove(child)

    # extra project blocks beyond the two skeleton slots.
    # The base file has room for exactly two projects. Rather than pad the
    # existing bullets to fill the page, clone the project-2 heading and bullet
    # paragraphs (which carry the right tab stop and the bullet list style) and
    # insert filled copies after the last surviving project paragraph.
    if len(md["projects"]) > 2:
        body = root.find(W + "body")
        if body is not None:
            kids = list(body)
            anchor_pos = None
            for pid in (P2B[-1], P2B[0], P2H):
                if pid in kill:
                    continue
                try:
                    anchor_pos = kids.index(paras[pid])
                    break
                except ValueError:
                    continue
            if anchor_pos is not None:
                head_tpl = copy.deepcopy(paras[P2H])
                bul_tpl = copy.deepcopy(paras[P2B[0]])
                pos = anchor_pos
                for proj in md["projects"][2:]:
                    pos += 1
                    h = copy.deepcopy(head_tpl)
                    body.insert(pos, h)
                    set_heading_with_tab(h, proj["heading"], bold_t)
                    for b in proj["bullets"][:2]:
                        pos += 1
                        bb = copy.deepcopy(bul_tpl)
                        body.insert(pos, bb)
                        set_runs(bb, b, bold_t, plain_t)

    files["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return len(kill)


if __name__ == "__main__":
    md, out = sys.argv[1], sys.argv[2]
    n = build(md, out, None)
    print(f"built {out} (removed {n} surplus paragraphs)")
