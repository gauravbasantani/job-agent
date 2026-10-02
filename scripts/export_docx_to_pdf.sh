#!/bin/zsh
# Export a DOCX to PDF through Microsoft Word.
#
# Usage: export_docx_to_pdf.sh <in.docx> <out.pdf>
#
# Word on this machine intermittently throws -1708 ("doesn't understand the
# close message") on `close document`. The save-as still succeeds, but the
# document stays open and silently breaks the NEXT export, which is how a batch
# ends up with DOCX files and no PDFs. So: quit Word before and after instead
# of closing documents, and never suppress that into a false success.
set -e
[[ -f "$1" ]] || { echo "no such docx: $1" >&2; exit 1; }
osascript -e 'tell application "Microsoft Word" to quit saving no' >/dev/null 2>&1 || true
sleep 2
osascript -e "with timeout of 180 seconds
tell application \"Microsoft Word\"
  activate
  open POSIX file \"$PWD/$1\"
  delay 2
  save as active document file name \"$PWD/$2\" file format format PDF
  delay 1
end tell
end timeout" >/dev/null 2>&1 || true
osascript -e 'tell application "Microsoft Word" to quit saving no' >/dev/null 2>&1 || true
sleep 1
[[ -f "$2" ]] || { echo "export FAILED, no pdf at $2" >&2; exit 1; }
echo "exported $2"
