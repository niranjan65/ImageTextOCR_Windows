# Automatic RDA Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically extract each captured RDA screen, create a new RDA Information record on Skylink, and verify every submitted value after saving.

**Architecture:** Extend local OCR with positioned words, map those words using a section-aware schema, and send validated JSON through an isolated Frappe client. A background capture workflow reports progress through the existing Tk result queue. Connection and correction dialogs stay separate from OCR, mapping, and networking.

**Tech Stack:** Existing Windows Python environment, Tkinter, Pillow, PyOCR/Tesseract, standard-library urllib/json/unittest. No cloud OCR or additional runtime dependency.

**Spec:** `docs/superpowers/specs/2026-10-22-automatic-rda-upload-design.md`

## Global Constraints

- The user explicitly chose **always create a new record**, including when the Revenue Item ID already exists.
- Existing records must never be updated by this workflow.
- Blank or unseen fields are omitted, not filled from the sample.
- Keep the SID and CSRF token in memory; do not place them in source, packaged files, saved JSON, logs, exception messages, or URLs.
- Require HTTPS. Follow redirects only within the configured HTTPS origin; never forward credentials to another host.
- Screenshots themselves remain local; only the mapped record JSON is transmitted.
- A POST must not be automatically retried after a timeout or uncertain response because the server may already have inserted a new record.
- Preserve the existing manual image and plain-text OCR workflows and all 15 capture tests.
- This workspace is not a Git repository. Use local file checkpoints; do not initialize a repository or invent commit SHAs.

## Review Focus

1. A narrow or scaled capture contains repeated party labels: keep values in their actual section or flag the assignment (Task 2).
2. A response arrives after another capture or after shutdown: ignore stale events and never initiate another send (Task 4).
3. A server inserts a document but its response is lost: show an uncertain outcome and issue exactly one POST (Task 3).
4. A session expires between connection testing and saving: retain the image and mapping, show reconnect guidance, and do not claim success (Tasks 3–4).
5. Two intentional captures have the same Revenue Item ID: create distinct documents, while replaying one completion event does not create a duplicate (Tasks 3–5).

## File Map

| File | Responsibility |
|---|---|
| `ocr_core.py` | Existing text OCR plus positioned-word document extraction |
| `rda_schema.json` | Packaged allowlist of 100 data fields, sections, aliases and types |
| `rda_mapping.py` | Section/column mapping, normalization, evidence and validation issues |
| `frappe_client.py` | Origin-confined session authentication, CSRF, create and read-back verification |
| `capture_workflow.py` | Capture job IDs and synchronous worker pipeline, independent of Tk |
| `frappe_settings.py` | Connection dialog and persistence of non-secret preferences |
| `rda_review.py` | Mapped values, correction/omission, JSON export and explicit Send action |
| `ocr_app.py` | Existing UI, queue integration, auto-send controls and saved-record link |
| `test_ocr_document.py`, `test_rda_mapping.py` | OCR and mapping regression tests |
| `test_frappe_client.py`, `test_capture_workflow.py` | Controlled HTTP and workflow tests |
| `test_rda_upload_ui.py` | Desktop connection/capture/correction integration tests |
| `tests_support/rda_fixture.py`, `tests_support/frappe_fixture.py` | Generated RDA images/word fixtures and stateful HTTP fixture |
| `build_windows.bat`, `README.md` | Schema packaging and user/test instructions |

## Task 1: Positioned OCR document output

**Files:** Modify `ocr_core.py`; create `test_ocr_document.py` and `tests_support/rda_fixture.py`.

**Interfaces:**
- Produce frozen `OCRWord(content: str, bbox: tuple[int, int, int, int], confidence: float)` and `OCRDocument(text: str, words: tuple[OCRWord, ...], width: int, height: int)` in `ocr_core.py`.
- Produce `extract_document(image_path: str | Path, language: str = "eng", tool=None) -> OCRDocument`.
- Preserve `extract_text(image_path, language="eng", tool=None) -> str`.
- Fixture helper `render_rda_fixture(path: Path, values: dict[str, object], scale: int = 1) -> None` draws labels, section headers, party columns and the summary grid. Fixture values are supplied by each test, never imported by production code.

- [x] **Step 1: Add tests before implementation.** `test_positioned_words_include_confidence_and_bounds` uses a rendered image containing `Form ID: 0430` and asserts recognized words retain `0430`, coordinates lie within document bounds, and confidence is represented on a 0–100 scale. `test_original_text_extraction_remains_compatible` asserts the existing text API still recognizes `CAPTURE 12345`. `test_rotated_input_uses_displayed_orientation` checks EXIF orientation with a hand-checked fixture.
- [x] **Step 2: Run** `.venv\Scripts\python.exe -m unittest test_ocr_document -v`; confirm the new API test fails because positioned extraction is absent, with no unrelated setup error.
- [x] **Step 3: Implement the dataclasses and `extract_document`** using `pyocr.builders.WordBoxBuilder(tesseract_layout=11)`. Apply EXIF orientation and a consistent small-text upscale before OCR; document dimensions and word coordinates must use the same working-image coordinate system. Derive readable text by grouping words into lines by vertical position. Do not change existing `extract_text` behavior.
- [x] **Step 4: Run** the focused tests and `.venv\Scripts\python.exe -m unittest discover -v`; require passing real OCR and existing capture tests. Tesseract-dependent tests may skip only when the executable/model is genuinely unavailable, and the final report must identify any skip.
- [x] **Step 5: Checkpoint** the changed files and test output locally; no Git commands apply in this workspace.

## Task 2: Schema-aware RDA mapping and correction validation

**Files:** Create `rda_schema.json`, `rda_mapping.py`, `test_rda_mapping.py`; extend `tests_support/rda_fixture.py`.

**Interfaces:**
- Consume `OCRDocument`/`OCRWord` from Task 1.
- Produce `MappingIssue(fieldname: str | None, message: str, raw_value: str | None)` and `MappedRecord(payload: dict[str, object], issues: list[MappingIssue], evidence: dict[str, tuple[OCRWord, ...]])`.
- Produce `load_schema() -> dict`, `map_rda_document(document: OCRDocument, schema: dict | None = None, minimum_confidence: float = 80.0) -> MappedRecord`, and `validate_payload(payload: dict[str, object], schema: dict | None = None) -> list[MappingIssue]`.
- `payload` contains `doctype: "RDA Information"` plus only recognized data fields. Issues block automatic sending; review edits/explicit omissions resolve them and are revalidated.

- [x] **Step 1: Add literal, section-aware expectations.** Tests must assert `shipper_name == "JAMES PARK"`, `recipient_name == "TRINNEE PECUNDO"`, `bill_to_company == "PNG AIR FREIGHT LIMITED"`, and absence of blank `bill_to_name`. Assert `lob == "00002"`, `co == "002"`, `form_id == "0430"`, `revenue_item_id == "2230000850298458"`, `net_amount == 108.28`, `currency == "USD"`, and six appropriate date fields equal `2026-08-27`. Place `C` in the fixture itself for pickup type.
- [x] **Step 2: Add failure and anti-hardcoding tests.** A second fixture with different people/accounts/dates/pickup type must return those new values. Low-confidence identifiers, impossible dates, two competing values, labels missing their section, clipped party headings, sparse unrelated text, and empty captures must produce issues instead of plausible invented values. Scale the same layout and shift its origin to exercise geometric mapping without fixed screen coordinates.
- [x] **Step 3: Run** `.venv\Scripts\python.exe -m unittest test_rda_mapping -v`; establish the missing mapping behavior fails before implementing it.
- [x] **Step 4: Build the packaged schema** from the supplied/live DocType fields: only data fieldname/type/label/options plus section and explicit screen-label aliases. Include all 100 data fields, preserve section membership across Column Breaks, and exclude layout fields and administrative metadata. Resolve the resource relative to `sys._MEIPASS` for packaged execution, otherwise the module directory.
- [x] **Step 5: Implement mapping and validation.** Recognize summary-grid column headers and section rectangles using word positions. Scope repeated labels to their section and adjacent column, with right-of-label and below-header value regions bounded by neighboring labels/headers. Normalize punctuation for label matching; keep original value text. Normalize dates/numbers according to field type, preserve Data strings, and split currencies only for the corresponding amount field. Use only same-section evidence. Unassignable recognized values and confidence below the threshold become explicit issues.
- [x] **Step 6: Run** all mapping tests, actual OCR-to-mapping tests on generated images, and the full suite. Record which tests use synthetic images; do not claim accuracy on the user's original inline screenshot without a local source-image fixture.
- [x] **Step 7: Checkpoint** mapper, schema, fixture and test results.

## Task 3: Authenticated create-and-verify Frappe client

**Files:** Create `frappe_client.py`, `test_frappe_client.py`, `tests_support/frappe_fixture.py`.

**Interfaces:**
- Consume the allowlisted payload and schema from Task 2.
- Produce `FrappeClient(base_url: str, sid: str, timeout: float = 20.0, opener=None)`.
- Produce `ConnectionInfo(user: str, schema: dict)` from `test_connection() -> ConnectionInfo`.
- Produce `SavedRecord(name: str, url: str, submitted: dict[str, object], stored: dict[str, object])` from `create_and_verify(payload: dict[str, object]) -> SavedRecord`.
- Errors: `FrappeError` for definitive errors, `SaveOutcomeUnknown` when POST may have succeeded, and `VerificationError(saved: SavedRecord, mismatches: dict)` when the fetched record differs or cannot be verified. Never include credentials in error text or object representations.
- The injected opener is an HTTP I/O seam for tests, not a way to relax production HTTPS/origin checks.

- [x] **Step 1: Add a stateful HTTP fixture and failing tests.** It exposes authenticated logged-user, DocType, Desk/CSRF, Currency Link, POST-create, and GET-document responses, and stores submitted documents by unique generated names. Intercept urllib requests with a fixture handler so production URL/header/response logic runs without a network dependency. Assert the SID is sent only as a cookie to the exact configured HTTPS origin, CSRF accompanies POST, and all data fields round-trip.
- [x] **Step 2: Add failure tests.** Reject HTTP URLs and cross-origin redirects before credentials are sent. Handle Guest, expired sessions, permission denial, schema type drift, unknown keys, missing Link values, server-side numeric normalization and actual field mismatches. Simulate insertion followed by a lost POST response; assert exactly one POST and `SaveOutcomeUnknown`. Two intentional `create_and_verify` calls with the same Revenue Item ID must return distinct names; assert zero PUT/PATCH/DELETE requests.
- [x] **Step 3: Run** `.venv\Scripts\python.exe -m unittest test_frappe_client -v`; confirm the client behavior is missing before implementation.
- [x] **Step 4: Implement the client** with standard-library urllib, a same-origin redirect policy, masked credential representations, authenticated schema/Link checks, Desk CSRF discovery, one create request, and independent GET verification. Use numeric comparison for Currency/Float/Int, exact comparison for dates/Data, and bounded timeouts. Sanitize response errors before exposing them to the UI.
- [x] **Step 5: Run** the client tests and full suite; require all controlled failure paths to pass without sending requests to the real site.
- [x] **Step 6: Checkpoint** client and controlled HTTP tests.

## Task 4: Automatic capture workflow and desktop controls

**Files:** Create `capture_workflow.py`, `frappe_settings.py`, `rda_review.py`, `test_capture_workflow.py`, `test_rda_upload_ui.py`; modify `ocr_app.py` and existing capture tests as necessary to isolate auto-send configuration.

**Interfaces:**
- Consume `extract_document`, `MappedRecord`, `validate_payload`, `FrappeClient`, and `SavedRecord` from prior tasks.
- Produce `CaptureJob(job_id: int, path: Path, language: str, auto_send: bool)` and `WorkflowEvent(job_id: int, phase: str, data: object)` in `capture_workflow.py`.
- Produce `run_capture_job(job: CaptureJob, tool, client: FrappeClient | None, emit: Callable[[WorkflowEvent], None]) -> None` and `send_reviewed_job(job: CaptureJob, payload: dict[str, object], client: FrappeClient, emit: Callable[[WorkflowEvent], None]) -> None`. These synchronous functions run in a daemon worker started by the app; they never call Tk.
- Event phases: `ocr`, `mapped`, `review_required`, `sending`, `verified`, `failed`, `outcome_unknown`, `verification_failed`. A failed verification event retains the returned record link.
- `ConnectionDialog(master, on_connected: Callable[[FrappeClient, ConnectionInfo], None])` owns masked session entry and asynchronous Test Connection. `load_preferences() -> dict` / `save_preferences(site_url: str, auto_send: bool) -> None` persist only those named non-secret values in the user's normal app-data directory.
- `RDAReviewDialog(master, mapping: MappedRecord, on_send: Callable[[dict[str, object]], None])` exposes exact fieldnames, candidate values, issues, explicit omission, and revalidation before Send.

- [x] **Step 1: Add headless workflow tests before code.** A successful configured job must emit mapping, one sending event, and verified output. Issues or an absent connection must yield review guidance and zero creates. An expired session after a successful connection check must preserve mapped values. Test an unknown save outcome without a second create and a verification mismatch with the record link retained.
- [x] **Step 2: Add desktop tests before integration.** A successful capture automatically runs OCR and sending when configured; Escape/failed capture never sends. A capture made before engine discovery completes starts once, when the engine becomes ready. Browsing a file does not auto-send. Editing/omitting an issue revalidates the submitted payload. Replay a terminal event and assert no additional POST. Deliver an obsolete job result and a post-shutdown event and assert no new send. Re-extracting a sent capture must not auto-submit it again.
- [x] **Step 3: Run** `.venv\Scripts\python.exe -m unittest test_capture_workflow test_rda_upload_ui -v`; confirm failures demonstrate missing workflow behavior.
- [x] **Step 4: Implement the synchronous workflow** using the prior OCR/mapper/client interfaces. Emit progress and preserve extracted text/mapping on failures. Sending a corrected payload is explicit, separate from rerunning extraction.
- [x] **Step 5: Implement settings and review dialogs**, including a visible connection user/site, masked SID entry, Test Connection, editable mapped values, explicit omission, and JSON export. Persist no SID/CSRF token and do not prefill credentials from source files or old test artifacts. Never access Tk from a worker.
- [x] **Step 6: Integrate with `ocr_app.py`.** Add Connection Settings, an Auto-send captures toggle, mapped-results access, and Open Record. Begin a job from `_complete_capture` or defer it until engine readiness. Track the active job ID and sent state; ignore stale results and disable overlapping capture/send operations. Preserve manual text extraction and error recovery. Change offline/no-upload copy to accurately say OCR is local and mapped values are sent to the configured site.
- [x] **Step 7: Run** workflow/UI tests and all prior tests. Open the app at default/minimum sizes and visually verify the new controls and correction states. UI tests use the controlled client; they must not create live records during normal discovery.
- [x] **Step 8: Checkpoint** the working automatic pipeline and UI integration.

## Task 5: Packaging, live acceptance and user instructions

**Files:** Modify `build_windows.bat` and `README.md`; create opt-in `verify_rda_live.py`; extend `test_frappe_client.py` with packaging-resource checks only where executable behavior can be exercised.

**Interfaces:**
- `verify_rda_live.py --site https://skylink.dev.advtinni.com --image PATH --create-count 2` reads SID only from `SKYLINK_SESSION_ID` or a masked terminal prompt, uses the production OCR/mapper/client, and writes a credential-free field comparison report. Live writes occur only when this script is explicitly invoked; it is not a discovered unittest.
- The script stops for mapping issues instead of hardcoding corrections. If a local real source screenshot is unavailable, use a clearly identified rendered fixture and report that limitation.

- [x] **Step 1: Add the schema resource to the existing PyInstaller command** with `--add-data "rda_schema.json;."`. Test resource loading under both normal module resolution and an isolated `sys._MEIPASS` fixture. Preserve the current Tesseract bundling and avoid unrelated build changes.
- [x] **Step 2: Document setup and operation**: connection URL/SID, session expiration, automatic capture-to-save, correction/omission, new record on every intentional send, uncertain outcomes, and saved-field verification. Explain that only record values are transmitted and screenshots stay local. Document test and opt-in live verification commands.
- [x] **Step 3: Run** `.venv\Scripts\python.exe -m unittest discover -v` and `.venv\Scripts\python.exe -m compileall -q ocr_app.py ocr_core.py screen_capture.py rda_mapping.py frappe_client.py capture_workflow.py frappe_settings.py rda_review.py verify_rda_live.py`; require passing tests and compilation. Build and smoke-test the executable if PyInstaller is available; otherwise explicitly report that packaging has not been executed.
- [x] **Step 4: Run the authorized live acceptance test** with a valid in-memory session against the development site. Create two records intentionally using one identified fixture image. Fetch each independently, verify all submitted fields, confirm distinct record names despite the same Revenue Item ID, and confirm no existing record was updated. Do not delete created records automatically. Keep credentials out of all reports and console output.
- [x] **Step 5: Inspect the app and final reports.** Confirm the displayed saved-record links open the correct new records. Record extraction accuracy separately from API read-back results. If session access or a real screenshot fixture is unavailable, complete controlled tests and state the exact remaining live/accuracy limitation; do not call untested live behavior verified.
- [x] **Step 6: Request one focused final code review**, resolve blocking findings, rerun checks affected by changes, and open the updated app for the user. Include changed behavior, test results, record links, and any remaining validation limits in the handoff.

## Execution Handoff

Recommended execution method: **Native**. The five tasks share OCR, mapper,
client and queue interfaces, so one implementer can maintain consistency and
reuse the existing desktop test environment, followed by one independent review.

Alternative: **Subagent-driven**, with a separate implementer/reviewer per task;
this provides more review checkpoints at greater context and coordination cost.

Implementation starts after the user reviews this plan and chooses an execution
method. The approved design, duplicate policy, and site destination remain fixed.
