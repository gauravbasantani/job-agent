"""Prepend a plain-text location to the rebuilt contact line.

fix_docx_contact_links.py wipes the contact paragraph and rebuilds it from
fixed constants (LinkedIn, portfolio, email, phone), which destroys any prefix
written in the markdown. This runs AFTER the fixer and puts the location back
as a plain run, so a recruiter screening for local candidates sees it first.
"""
import sys, zipfile, shutil, copy
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML = "{http://www.w3.org/XML/1998/namespace}"
path, location = sys.argv[1], sys.argv[2]

with zipfile.ZipFile(path) as z:
    files = {n: z.read(n) for n in z.namelist()}
    head = files["word/document.xml"][:2000].decode("utf-8", "replace")
for pre, uri in __import__("re").findall(r'xmlns:([A-Za-z0-9_.-]+)="([^"]+)"', head):
    try: ET.register_namespace(pre, uri)
    except ValueError: pass

root = ET.fromstring(files["word/document.xml"])
body = root.find(W + "body")
paras = body.findall(W + "p")

def text(p): return "".join(t.text or "" for t in p.iter(W + "t"))

target = next(
    (
        p
        for p in paras[:4]
        if "|" in text(p)
        and (
            "@" in text(p)
            or ("LinkedIn" in text(p) and "Email" in text(p))
        )
    ),
    None,
)
if target is None:
    sys.exit("contact paragraph not found")
if text(target).startswith(location):
    sys.exit("location already present")

# clone run props from the first existing run so styling matches exactly
first_run = next(target.iter(W + "r"), None)
run = ET.Element(W + "r")
if first_run is not None:
    rpr = first_run.find(W + "rPr")
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
t = ET.SubElement(run, W + "t")
t.text = f"{location} | "
t.set(XML + "space", "preserve")
target.insert(len(target.findall(W + "pPr")), run)

files["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
shutil.copy(path, path + ".bak")
with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
    for n, d in files.items(): z.writestr(n, d)
print(f"prepended {location!r} to contact line")
