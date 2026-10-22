# Automatic screenshot-to-RDA upload

Date: 2026-10-22

## Approved intent

The user wants the existing Capture Screenshot action to extract the captured
values and send them automatically to the RDA Information DocType at
https://skylink.dev.advtinni.com/. The user explicitly chose **always create a
new record**, including when the Revenue Item ID already exists. Existing
records must never be updated by this workflow.

The user approved local extraction tailored to the RDA layout already shared,
section-aware mapping, correction of ambiguous values, connection settings,
verification after saving, and a link to the saved document.

## Current application

The Tkinter app captures a selected desktop region into a temporary PNG. It
currently requires Extract Text to run local Tesseract OCR and displays editable
plain text. Capture selection, cancellation, errors, cleanup, screen coordinates,
and real OCR are covered by 15 desktop tests.

The supplied DocType has 100 data fields. Its live schema was previously checked.
The manually prepared example populated 49 fields and was saved and read back
successfully through the Frappe REST API. That example is test reference data;
it must not be reused as the output for subsequent captures.

## User workflow

1. Open Connection Settings and enter the Skylink URL and an existing session ID.
   A Test Connection action checks the logged-in user and access to the DocType.
2. Automatic sending is enabled for screenshot captures once the connection is
   configured. Show the destination and automatic-send state in the main window.
3. Click Capture Screenshot, drag an area, and release. Cancellation preserves
   the previous image and results and never starts an upload.
4. Start OCR automatically after a successful capture. If engine discovery is
   still in progress, retain that capture and start when the engine is ready.
5. Map the current capture into a JSON document using actual DocType fieldnames.
   Display the extracted text, mapped values, and any issues.
6. If mapping and validation succeed, create one new RDA Information document.
   Fetch it independently and compare every submitted field.
7. Show Saved and verified, the document name, and an Open Record action only
   when the read-back comparison succeeds.

Browse image and ordinary text extraction remain available. Choosing a file does
not silently upload it. Users can disable automatic sending and explicitly send
a reviewed capture. Re-running text extraction on an already sent capture does
not silently submit the same capture again; another explicit send or a new
capture is a separate intentional submission.

## Local extraction and mapping

Use local Tesseract word boxes, including positions and confidence, through the
installed PyOCR adapter. Keep the current plain-text extraction API compatible.
Word coordinates allow the mapper to distinguish adjacent columns and repeated
labels rather than relying on flattened OCR line order.

Use section titles and label/header aliases for the supplied RDA screen layout:
RDA Summary, Transaction Information, Invoice Information, Shipper Information,
Recipient Information, Bill To Information, Payment, Service, Services Rendered,
and General. Match labels within their section and column. For example, Name
in Shipper Information maps to shipper_name, while Name in Recipient Information
maps to recipient_name. Column breaks do not end a section.

Store the allowlisted schema and aliases as a packaged local resource. No layout
field (Section Break or Column Break), arbitrary OCR key, or DocType definition
metadata may enter a record payload. Match the live schema before sending.

Normalize dates to YYYY-MM-DD and numeric Currency, Float, and Int fields to
JSON numbers. Preserve Data fields as strings, including leading zeros, long
identifiers, account numbers, and postal codes. Split a value such as 108.28 USD
into net_amount and currency only where its section and label justify that
mapping. Do not infer a country, currency, name, or other value from an unrelated
section. Blank or unseen fields are omitted, not filled from the sample.

The previously user-confirmed pickup type C belongs only to the example fixture.
Subsequent captures must supply their own pickup type.

Require at least one reliably mapped data field and recognizable RDA labels or
headers. Invalid dates/numbers, competing assignments to one field, low-confidence
values, and ambiguous section assignments stop automatic sending. Present each
issue with its candidate field/value for correction or explicit omission.
User edits must pass the same schema/type checks before an explicit Send action.
An omitted field must be visibly marked as omitted. No OCR confidence heuristic
is presented as proof that a value is correct.

## Connection and REST client

Prefill https://skylink.dev.advtinni.com/ and fix the destination DocType to RDA
Information. Require HTTPS. Keep the SID and CSRF token in memory; do not place
them in source, packaged files, saved JSON, logs, exception messages, or URLs.
Persist only non-secret preferences such as the site URL and automatic-send
setting. The connection dialog masks the session ID.

Authenticate with the SID cookie, check frappe.auth.get_logged_user, and obtain
the session's CSRF token through the authenticated Desk page. Respect normal
Frappe permissions and CSRF checks. Follow redirects only within the configured
HTTPS origin; never forward credentials to another host. Validate live schema
fields/types and Link targets used by the payload before POST.

Create with POST /api/resource/RDA%20Information and verify with an independent
GET of the returned document name. Compare dates and Data fields exactly and
numeric fields numerically. This workflow does not deduplicate by Revenue Item
ID, PUT an existing document, change permissions, or modify the DocType schema.

Use bounded network timeouts. Safe reads may be retried, but a POST must not be
automatically retried after a timeout or uncertain response because the server
may already have inserted a new record. Show Save outcome unknown in that case,
retain the payload, and direct the user to check the site before another explicit
send. A failed verification must show the returned record link and mismatched
fields rather than claiming success or inserting a replacement.

## Application structure and state

Keep screen_capture.py responsible for region selection. Extend ocr_core.py with
positioned OCR output, add a focused RDA mapping/validation module and schema
resource, and isolate authenticated REST operations in a Frappe client module.
ocr_app.py coordinates these pieces and contains the connection/review controls.

Use explicit capture, OCR, review, sending, verified, failed, and outcome-unknown
states. Associate worker results with their capture so stale results cannot
trigger a save for another image. Disable overlapping capture/send actions while
work is active. Worker threads must communicate through the existing result
queue; they must not manipulate Tk widgets. Closing the app must not trigger
another submission or expose credentials.

Update the UI's offline/no-upload wording to distinguish local OCR from sending
mapped field values to the configured Skylink server. Screenshots themselves
remain local; only the mapped record JSON is transmitted.

Include the schema resource in the existing PyInstaller build and document
connection setup, capture-to-save behavior, correction, session expiration, and
the distinction between a failed request and an uncertain save outcome.

## Verification and acceptance

- Keep all existing capture tests passing.
- Test section/column mapping with word-box fixtures containing repeated labels,
  empty values, leading zeros, long IDs, dates, and currencies.
- Exercise actual Tesseract against rendered RDA fixtures. Add real source
  screenshots as regression fixtures when available as local image files. Clearly
  distinguish synthetic-fixture checks from accuracy on real captured screens.
- Test correction and omission, schema drift, empty/partial/unrecognized captures,
  stale worker results, and a capture made before OCR initialization completes.
- Test REST behavior against a controlled HTTP fixture: authenticated headers,
  CSRF, permission/session failures, link validation, origin confinement, one POST
  per intended submission, uncertain writes, and read-back mismatches.
- Run a live create-and-read-back test on the authorized Skylink development site
  using a valid session. Confirm that two intentional submissions create distinct
  names even when their Revenue Item IDs match, with no existing document updated.
- Report extraction accuracy and saved-field verification separately. A successful
  API round trip alone does not establish that OCR read the screenshot correctly.

Done means a configured app can take an RDA capture through local extraction,
mapping, new-record creation, and successful read-back verification automatically,
while routing ambiguous captures and failed/uncertain requests to actionable UI
states instead of silently sending guesses or retrying inserts.

## Scope boundaries

This change targets screenshots of the supplied RDA interface. Arbitrary invoice
layouts, handwriting, AI/cloud extraction, schema editing, existing-record updates,
and uploading screenshot files are outside this workflow.

## Repository note

This workspace is not a Git repository. The design is saved as a local file;
there is no existing branch or commit to update.
