# Resume Output Spec

Rules for the FINAL file generated at submission time. This extends
`resume-standards.md` (which governs content) — this file governs the
output artifact itself. The tailoring agent checks both before marking a
resume ready.

## Build method: edit the original .docx, never rebuild the layout
The user's own resume files in `profile/resumes-docx/` are the visual source
of truth. Generate the submission file by copying the best-matching `.docx`
and editing it in place — reorder and delete `<w:p>` paragraphs, and replace
text only inside existing runs. That preserves fonts, spacing, tab stops,
section rules, and the bold emphasis inside bullets, all of which are lost
if the resume is rebuilt from markdown.

Two rules when editing runs: bullets carry bold emphasis on key phrases
(reordering keeps it, rewriting destroys it), and skills lines start with a
bold label run ("Design & Research:") followed by the list — replace only
the list run.

Export the PDF from Microsoft Word via AppleScript, not a HTML converter.
`textutil`/`cupsfilter`/headless-Chrome renderings of a .docx do not
reproduce Word's layout and will misrepresent the page.

Before exporting, run `scripts/fix_docx_contact_links.py` on the generated
DOCX. The header contact line must have separate visible hyperlink targets for
LinkedIn, portfolio, and email, no hidden/empty hyperlinks, and the rendered
name must read `Your Name` with the space intact.

If Word automation is unavailable, create a clearly labeled preview PDF from
`resume-used.md` so the packet is not missing an artifact, but mark
`format_fallback: true` in `application.md`. A fallback preview is not
submission-ready until it has been visually inspected and either approved or
re-exported from the source DOCX. Never report a fallback as preserved Word
layout.

## Format
- **One page. Hard limit — and fill it.** Under-filling is its own failure:
  a page that stops two thirds down reads as a thin resume. Cut the least
  JD-relevant bullets only when content genuinely overflows, and if trimming
  leaves a large empty block, put bullets back. Never shrink the font below
  readable size or squeeze margins to cheat the limit.
- Verify by rendering the exported PDF to an image and looking at it. Page
  count alone does not tell you whether the page is well filled.
- **Font: Calibri.** Body 10.5-11pt, name/header slightly larger. Nothing
  decorative.
- **PDF is the submission format, always.** Generate docx first (as the
  editable intermediate), export to PDF, attach the PDF to applications.
  Keep the docx in the same application folder in case a form specifically
  demands docx.

## File naming
```
Your_Name_{Job_Title}_Resume.pdf
```
Derive `{Job_Title}` from the actual posting title, underscored:
- "UX Designer" → `Your_Name_UX_Designer_Resume.pdf`
- "Product Designer" → `Your_Name_Product_Designer_Resume.pdf`
- "Senior Product Designer, Growth" → strip qualifiers to the recognizable
  core: `Your_Name_Senior_Product_Designer_Resume.pdf`

Keep it clean — no dates, no company names, no version numbers in the
filename a recruiter sees.

## The 7-second scan check
Recruiters skim before they read. Before marking a resume ready, verify:
1. **Top third of the page carries the match.** Name, title line, and the
   first 2-3 bullets a scanner hits must reflect the JD's top
   requirements. If the strongest JD-relevant proof point is buried
   halfway down the page, the tailoring isn't done — move it up.
2. **The title line mirrors the posting.** If the posting says "Product
   Designer," the headline under the name says Product Designer — not a
   different self-chosen title the scanner has to translate.
3. **Numbers are visible at a skim.** Quantified results (%, $, scale)
   should be scannable without reading full sentences — they're what
   stops the eye.
4. **No dense walls.** Bullets over two lines get tightened. White space
   is part of scannability, not wasted space.

## Where output lands
Final files go in that job's application folder:
```
applications/{date}-{company}-{role}/
  resume-used.md          (the tailored markdown source)
  Your_Name_{Job_Title}_Resume.docx
  Your_Name_{Job_Title}_Resume.pdf   ← this is what gets attached
```
