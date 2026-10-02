on run argv
	if (count of argv) is not 2 then error "Usage: export_docx_to_pdf.applescript input.docx output.pdf"
	set inputPath to item 1 of argv
	set outputPath to item 2 of argv
	set inputFile to POSIX file inputPath
	tell application "Microsoft Word"
		activate
		open inputFile
		delay 1
		-- `repeat with candidateDoc in documents` fails in current Word builds
		-- because the application returns an "every document" specifier rather
		-- than an enumerable list. The file opened immediately above is made the
		-- active document, so use that stable object directly.
		set sourceDoc to active document
		save as sourceDoc file name outputPath file format format PDF
		close sourceDoc saving no
	end tell
end run
