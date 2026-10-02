import argparse
import re
import textwrap
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("application_dir", type=Path)
parser.add_argument("job_title")
args = parser.parse_args()
app = args.application_dir.resolve()
source = app / "resume-used.md"
if not source.is_file():
    raise SystemExit(f"Missing tailored resume: {source}")
safe_title = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", args.job_title)).strip("_")
output = app / f"Your_Name_{safe_title}_Resume.pdf"

def esc(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

section_names = {"SUMMARY", "PROFESSIONAL EXPERIENCE", "EDUCATION", "RELEVANT PROJECTS", "SKILLS"}
prepared = []
first = True
for raw in source.read_text(encoding="utf-8").splitlines():
    text = raw.strip()
    if not text:
        continue
    kind = "body"
    if first:
        kind, first = "title", False
    elif text.startswith("linkedin.com/"):
        kind = "contact"
    elif text in section_names:
        kind = "heading"
    elif text.startswith("-"):
        text = text[1:].strip()
        kind = "bullet"
    elif " | " in text and any(token in text for token in ("Product Designer", "UX Designer", "M.S.", "B.Tech", "AI Shopping", "Hermony:")):
        kind = "role"
    width = {"title": 94, "contact": 125, "heading": 120, "role": 112}.get(kind, 118)
    wrapped = textwrap.wrap(text, width=width, subsequent_indent="  ") or [""]
    for i, line in enumerate(wrapped):
        prepared.append((kind if i == 0 else "body", line))

font_sizes = {"title": 15.5, "contact": 7.8, "heading": 9.2, "role": 8.2, "bullet": 7.45, "body": 7.45}
leadings = {"title": 17, "contact": 9.5, "heading": 11, "role": 9.5, "bullet": 8.5, "body": 8.5}
commands = ["BT"]
y = 746
for index, (kind, line) in enumerate(prepared):
    if index:
        y -= leadings.get(kind, 8.5)
    if kind in {"heading", "role"}:
        y -= 1.4
    if y < 24:
        break
    font = "F2" if kind in {"title", "heading", "role"} else "F1"
    commands.extend([f"/{font} {font_sizes.get(kind, 7.45)} Tf", f"1 0 0 1 40 {y:.1f} Tm", f"({esc(line)}) Tj"])
commands.append("ET")
stream = "\n".join(commands).encode("latin-1", "replace")
objects = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
]
pdf = bytearray(b"%PDF-1.4\n")
offsets = [0]
for number, obj in enumerate(objects, 1):
    offsets.append(len(pdf))
    pdf.extend(f"{number} 0 obj\n".encode("ascii"))
    pdf.extend(obj)
    pdf.extend(b"\nendobj\n")
xref = len(pdf)
pdf.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
for offset in offsets[1:]:
    pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
pdf.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
output.write_bytes(pdf)
print(output)
