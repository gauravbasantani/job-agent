set appFolder to POSIX path of ((path to home folder as text)) & "job-agent-system/applications/2026-08-01-tomo-product-designer/"
set resumePath to appFolder & "resume-used.md"
set docxPath to appFolder & "Your_Name_Product_Designer_Resume.docx"
set pdfPath to appFolder & "Your_Name_Product_Designer_Resume.pdf"

set resumeText to read POSIX file resumePath as «class utf8»
tell application "Microsoft Word"
	activate
	set newDoc to make new document
	set content of text object of newDoc to resumeText
	do Visual Basic "ActiveDocument.SaveAs2 FileName:=" & quote & docxPath & quote & ", FileFormat:=16"
	do Visual Basic "ActiveDocument.SaveAs2 FileName:=" & quote & pdfPath & quote & ", FileFormat:=17"
	close newDoc saving no
end tell
