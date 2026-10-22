# Final review package

User approved Native execution of docs/superpowers/plans/2026-10-22-automatic-rda-upload.md and its linked spec. Workspace is not a Git repository. Compare old ocr_app.py, ocr_core.py, build_windows.bat and README.md in baseline/ against current files; remaining production files are new. Baseline snapshots and progress.md are in this directory.

Review current production files: ocr_core.py, rda_mapping.py, rda_schema.json, frappe_client.py, capture_workflow.py, frappe_settings.py, rda_review.py, ocr_app.py, verify_rda_live.py, build_windows.bat, README.md. Existing screen_capture.py is unchanged. Tests: test_ocr_document.py, test_rda_mapping.py, test_frappe_client.py, test_capture_workflow.py, test_rda_upload_ui.py, test_live_verifier.py and prior test_screen_capture.py. Fixtures live in tests_support/.

Current evidence: full suite 55/55 passing; source compilation passed. Real OCR through mapper/client intentionally created two records on authorized development site, each 5/5 fields read back correctly. Same Revenue Item ID; distinct names. Report rda_upload_live_report.json explicitly labels generated fixture. Actual original inline screenshot is not a local image, so OCR accuracy on that original is not claimed. The 49-field reference is covered by coordinate/word fixtures; actual rendered-image tests separately exercise real OCR. Standalone build is running; final UI preview saved as automatic_upload_preview.png.

The Tkinter worker-lifetime crash was reproduced with a RED weak-reference test and fixed with queue-only sinks and no Tk app captures in workers; all 55 tests passed afterward. Packaged Tesseract language-directory regression was reproduced and fixed.

Binding behavior: successful configured captures auto-OCR/map/create a NEW RDA Information document and independently fetch/verify fields. Never update existing records; no deduplication by Revenue Item ID. Uncertain extraction is reviewable and blocks auto-send. Keep SID/CSRF only in memory and scoped to configured HTTPS origin. No automatic POST retry after uncertain outcome. Keep local manual OCR/browse working.

Review Focus from plan:
1. A narrow or scaled capture contains repeated party labels: keep values in their actual section or flag the assignment (Task 2).
2. A response arrives after another capture or after shutdown: ignore stale events and never initiate another send (Task 4).
3. A server inserts a document but its response is lost: show an uncertain outcome and issue exactly one POST (Task 3).
4. A session expires between connection testing and saving: retain the image and mapping, show reconnect guidance, and do not claim success (Tasks 3–4).
5. Two intentional captures have the same Revenue Item ID: create distinct documents, while replaying one completion event does not create a duplicate (Tasks 3–5).

Read only. Do not edit files, call the live site, run UI tests or spawn additional reviewers. Check correctness and reasonable user expectations, including correction dialog lifetime, unknown outcomes, mapping completeness/ambiguity and visible error guidance. You may run focused headless tests if useful. Return concrete severity-calibrated findings with file:line references and a verdict; list every behavior declined as out of scope. This is the one final review; important findings will be fixed through RED→GREEN tests and a green suite, without a second review pass.
