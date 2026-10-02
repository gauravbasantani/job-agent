-- Fallback exporter. The main export_docx_to_pdf.applescript enumerates
-- `count of documents`, which fails on some Word states with error -1708.
-- This opens the file directly instead of counting the document collection.
on run argv
  set inPath to item 1 of argv
  set outPath to item 2 of argv
  tell application "Microsoft Word"
    activate
    open POSIX file inPath
    delay 2
    set d to active document
    save as d file name outPath file format format PDF
    delay 1
    close d saving no
  end tell
  return "ok"
end run
