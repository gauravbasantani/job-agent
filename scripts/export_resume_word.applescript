on run argv
	if (count of argv) is not 2 then error "Usage: export_resume_word.applescript input.docx output.pdf"
	set inputPath to item 1 of argv
	set outputPath to item 2 of argv
	tell application "Microsoft Word"
		activate
		open (POSIX file inputPath)
		set sourceDoc to active document
		do Visual Basic "ActiveDocument.ExportAsFixedFormat OutputFileName:=" & quote & outputPath & quote & ", ExportFormat:=17"
		close sourceDoc saving no
	end tell
end run
