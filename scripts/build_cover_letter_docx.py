#!/usr/bin/env python3
"""Build a tailored cover letter .docx from the user's base letter + markdown.

Mirrors build_tailored_docx.py: edits the user's own DOCX in place so fonts,
spacing and layout survive, replacing paragraph text by index. The base file has
five body-paragraph slots; extra paragraphs are inserted by cloning an existing
body paragraph so styling carries over.

Also repairs the phone number. profile/personal-info.md records the base cover
letter DOCX as containing (555) 123-4567, which is wrong; the confirmed number
is (555) 123-4567.
"""
import copy, re, shutil, sys, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML = "{http://www.w3.org/XML/1998/namespace}"
BASE = "profile/cover-letters-docx/Your Name Cover letter.docx"

LOC, CONTACT, LINKS = 1, 2, 3
BODY = [5, 6, 7, 8, 9]
PORTFOLIO, THANKS, SIGNOFF = 10, 11, 12
BAD_PHONE, GOOD_PHONE = "(555) 123-4567", "(555) 123-4567"


def parse_md(path):
    lines = Path(path).read_text(encoding="utf-8").rstrip().split("\n")
    header = [l.strip() for l in lines[:4]]
    rest = [l.strip() for l in lines[4:] if l.strip()]
    signoff = rest[-1]
    thanks = rest[-2]
    portfolio = rest[-3]
    body = rest[:-3]
    return dict(loc=header[1], contact=header[2], links=header[3],
                body=body, portfolio=portfolio, thanks=thanks, signoff=signoff)


def clear_runs(p):
    parents = {id(c): par for par in p.iter() for c in par}
    for r in list(p.iter(W + "r")):
        par = parents.get(id(r))
        if par is not None:
            par.remove(r)


def set_text(p, text, template):
    clear_runs(p)
    run = copy.deepcopy(template)
    for t in list(run.findall(W + "t")):
        run.remove(t)
    t = ET.SubElement(run, W + "t")
    t.text = text
    t.set(XML + "space", "preserve")
    p.append(run)



def register_original_namespaces(xml_bytes):
    """Preserve the template's namespace prefixes.

    The cover-letter base is a genuine Word file: its root declares ~a dozen
    namespaces and carries mc:Ignorable="w14 w15 wp14", an attribute whose
    VALUE names prefixes that must stay declared. ElementTree renames prefixes
    to ns0/ns1 and drops any namespace it did not use, which leaves
    mc:Ignorable pointing at undeclared prefixes -- Word then reports the file
    as corrupt. Registering every original prefix first makes the round trip
    lossless. Never register the EMPTY prefix: that strips w: from attribute
    names (w:val -> val) and Word rejects that too.
    """
    start = xml_bytes.index(b"<w:document") if b"<w:document" in xml_bytes else 0
    head = xml_bytes[start:xml_bytes.index(b">", start) + 1].decode("utf-8", "replace")
    for prefix, uri in re.findall(r'xmlns:([A-Za-z0-9_.-]+)="([^"]+)"', head):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass



def extract_root_tag(xml_bytes):
    """Return the template's <w:document ...> opening tag verbatim."""
    start = xml_bytes.index(b"<w:document")
    return xml_bytes[start:xml_bytes.index(b">", start) + 1]


def build(md_path, out_docx):
    shutil.copy(BASE, out_docx)
    with zipfile.ZipFile(out_docx, "r") as z:
        files = {n: z.read(n) for n in z.namelist()}
    register_original_namespaces(files["word/document.xml"])
    original_root_tag = extract_root_tag(files["word/document.xml"])
    root = ET.fromstring(files["word/document.xml"])
    paras = list(root.iter(W + "p"))
    md = parse_md(md_path)

    body_tpl = None
    for r in paras[BODY[0]].findall(W + "r"):
        if "".join(x.text or "" for x in r.iter(W + "t")).strip():
            body_tpl = r
            break
    hdr_tpl = paras[CONTACT].findall(W + "r")[0]

    set_text(paras[LOC], md["loc"], hdr_tpl)
    set_text(paras[CONTACT], md["contact"].replace(BAD_PHONE, GOOD_PHONE), hdr_tpl)
    set_text(paras[LINKS], md["links"], hdr_tpl)

    body = md["body"]
    parent = root.find(W + "body")
    for i, pid in enumerate(BODY):
        if i < len(body):
            set_text(paras[pid], body[i], body_tpl)
        else:
            # Fewer body paragraphs than template slots: DROP the unused slot.
            # Leaving it alone ships the base letter's original text (the
            # "Helping utility customers understand how they use energy"
            # paragraph) inside the tailored letter, and the build still
            # reports success.
            parent.remove(paras[pid])

    # insert any paragraphs beyond the five skeleton slots
    if len(body) > len(BODY):
        kids = list(parent)
        pos = kids.index(paras[BODY[-1]])
        for extra in body[len(BODY):]:
            pos += 1
            np = copy.deepcopy(paras[BODY[-1]])
            parent.insert(pos, np)
            set_text(np, extra, body_tpl)

    set_text(paras[PORTFOLIO], md["portfolio"], body_tpl)
    set_text(paras[THANKS], md["thanks"], body_tpl)
    set_text(paras[SIGNOFF], md["signoff"], body_tpl)

    out = ET.tostring(root, encoding="utf-8")
    # Restore the template's full root tag. ElementTree only writes namespace
    # declarations for namespaces it actually USED, so the ~31 unused ones
    # (w15, w16*, wp14, wps, ...) get dropped -- while mc:Ignorable still names
    # them. Word then reports the file as corrupt and silently fails to open.
    start = out.index(b"<w:document")
    out = original_root_tag + out[out.index(b">", start) + 1:]
    files["word/document.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + out)
    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return len(body)


if __name__ == "__main__":
    n = build(sys.argv[1], sys.argv[2])
    print(f"built {sys.argv[2]} ({n} body paragraphs)")
