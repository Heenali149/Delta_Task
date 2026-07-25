# Sample pair provenance

## pair_001

- **PID A** (`pair_001_lift_gas_KA901_A.pdf`): "Lift Gas Compressor P&ID" — 3rd Stage HP Gas Lift Compressor,
  tag `26-KA-901`. Native, born-digital PDF, 1 page, A3 landscape (1191x842 pt), text + vector layer extractable.
- **PID B** (`pair_001_export_gas_KA902_B.pdf`): "Export Gas Compressor P&ID" — 3rd Stage HP Gas Export Compressor,
  tag `26-KA-902`. Same drawing template/layout, native PDF, 1 page, same page size.

**Why this pair:** these are not two revisions of the *same* drawing — they are two different compressor trains
built from the same drawing template (same note numbering scheme, same tag/loop conventions, same equipment
data-table layout). That makes them a good stress test for the delta engine: a real text/pixel diff would report
almost the entire page as "changed" (different tag numbers throughout), while a useful delta needs to recognize
*which* changes are meaningful (spec values, setpoints, service description, added/removed equipment like the
balance-line cooler) versus which are just the expected tag-number relabeling between two trains. Ground truth for
`eval/` was hand-labeled by reading both PDFs and diffing the equipment data tables, setpoints, and notes sections.

Both files were provided directly by the user (see conversation); no synthetic editing was needed since real,
naturally-occurring differences already exist between the two documents.

## Scanned PDF / DWG samples

Not included in this cut. See README "What we cut and why" — the scanned-PDF and DWG adapters are implemented
behind the same `FormatAdapter` interface as native PDF but are stubs in this environment (no OCR binary / no DWG
sample available in the time window). The seam is real: `PdfScannedAdapter` will rasterize + OCR via `pytesseract`
if it's installed and a working Tesseract binary is on `PATH`; otherwise it raises a clear, logged
`AdapterUnavailableError` rather than silently failing.
