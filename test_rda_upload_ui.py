from pathlib import Path
import tempfile
import time
import unittest
import gc
import threading
import weakref
import os
from dataclasses import replace
from unittest.mock import patch
from PIL import Image
from ocr_app import OCRApp
from frappe_client import FrappeClient
from tests_support.frappe_fixture import FrappeFixture
from tests_support.rda_fixture import word_document


class RDAUploadUITests(unittest.TestCase):
    def setUp(self):
        self.settings_patch = patch('frappe_settings.save_preferences')
        try:
            self.settings_patch.start()
        except ModuleNotFoundError:
            self.fail('Connection settings are missing')
        self.addCleanup(self.settings_patch.stop)
        preferences = patch('frappe_settings.load_preferences', return_value={'site_url': 'https://skylink.example', 'auto_send': True})
        preferences.start()
        self.addCleanup(preferences.stop)
        with patch.object(OCRApp, '_load_engine', lambda app: None):
            self.app = OCRApp()
        self.app.engine = object()
        self.app.update()
        self.server = FrappeFixture()
        self.client = FrappeClient('https://skylink.example', self.server.sid, opener=self.server.opener())
        self.app._on_connected(self.client, self.client.test_connection())
        self.doc = word_document({'form_id': '0430', 'shipper_name': 'JAMES PARK'})

    def tearDown(self):
        if hasattr(self, 'app'):
            for task in self.app.tk.splitlist(self.app.tk.call('after', 'info')):
                self.app.after_cancel(task)
            self.app.destroy()
            del self.app
            gc.collect()

    def wait_done(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app.update()
            if not self.app.running:
                return
            time.sleep(.01)
        self.fail('Upload did not finish')

    def capture(self):
        with patch('capture_workflow.extract_document', return_value=self.doc):
            self.app._complete_capture(Image.new('RGB', (640, 300), 'white'))
            self.wait_done()

    def test_capture_automatically_creates_new_record(self):
        self.capture()
        self.assertEqual(self.server.post_count, 1)
        self.assertEqual(self.app._last_saved.stored['form_id'], '0430')
        self.capture()
        self.assertEqual(self.server.post_count, 2)
        self.assertEqual(len(self.server.documents), 2)

    def test_low_confidence_capture_does_not_open_review_or_confirmation(self):
        self.doc = replace(self.doc, words=tuple(replace(w, confidence=15) for w in self.doc.words))
        with patch('ocr_app.RDAReviewDialog') as review, patch('ocr_app.messagebox.askyesno') as confirmation:
            self.capture()
        self.assertEqual(self.server.post_count, 1)
        self.assertFalse(review.called)
        self.assertFalse(confirmation.called)
        self.assertIn('Saved and verified', self.app.status_var.get())

    def test_optional_review_hides_warnings_and_sends_without_acknowledgment(self):
        from rda_mapping import MappedRecord, MappingIssue
        from rda_review import RDAReviewDialog
        sent = []
        mapping = MappedRecord({'doctype': 'RDA Information', 'form_id': '0430', 'ship_date': 'bad'},
                               [MappingIssue('form_id', 'Low OCR confidence'), MappingIssue(None, 'Layout warning')])
        dialog = RDAReviewDialog(self.app, mapping, sent.append)
        self.assertNotIn('confidence', str(dialog.tree.item('form_id', 'values')))
        self.assertNotIn('warning', dialog.status.get().lower())
        dialog.send()
        self.assertEqual(sent, [mapping.payload])

    def test_capture_waits_for_engine_initialization_once(self):
        self.app.engine = None
        with patch('capture_workflow.extract_document', return_value=self.doc):
            self.app._complete_capture(Image.new('RGB', (640, 300), 'white'))
            self.assertEqual(self.server.post_count, 0)
            self.app.result_queue.put(('engine', object(), ['eng']))
            self.wait_done()
        self.assertEqual(self.server.post_count, 1)

    def test_cancel_browse_and_manual_reextract_never_auto_send(self):
        self.app._complete_capture(None)
        self.assertEqual(self.server.post_count, 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file.png'
            Image.new('RGB', (30, 30), 'white').save(path)
            with patch('ocr_app.filedialog.askopenfilename', return_value=str(path)):
                self.app.upload_btn.invoke()
            self.assertEqual(self.server.post_count, 0)
        self.capture()
        with patch('ocr_app.extract_text', return_value='plain text'):
            self.app.extract_btn.invoke()
            self.wait_done()
        self.assertEqual(self.server.post_count, 1)

    def test_replayed_or_stale_event_never_submits_another_record(self):
        from capture_workflow import WorkflowEvent
        self.capture()
        saved = self.app._last_saved
        current = self.app._upload_job.job_id
        self.app._handle_upload_event(WorkflowEvent(current, 'verified', saved))
        self.app._handle_upload_event(WorkflowEvent(current - 1, 'verified', saved))
        self.assertEqual(self.server.post_count, 1)
        self.assertIs(self.app._last_saved, saved)

    def test_correction_and_explicit_omission_revalidate_values(self):
        from rda_mapping import MappedRecord, MappingIssue
        from rda_review import RDAReviewDialog
        mapping = MappedRecord({'doctype': 'RDA Information', 'ship_date': 'bad', 'form_id': '0430'}, [MappingIssue('ship_date', 'Invalid date', 'bad')])
        sent = []
        dialog = RDAReviewDialog(self.app, mapping, sent.append)
        dialog.set_value('ship_date', '08/27/2026')
        dialog.set_value('form_id', '', omit=True)
        dialog.send()
        self.assertEqual(sent[0], {'doctype': 'RDA Information', 'ship_date': '2026-08-27'})

    def test_shutdown_ignores_late_worker_events(self):
        from capture_workflow import WorkflowEvent
        self.capture()
        job_id = self.app._upload_job.job_id
        saved = self.app._last_saved
        for task in self.app.tk.splitlist(self.app.tk.call('after', 'info')):
            self.app.after_cancel(task)
        app = self.app
        app.destroy()
        del self.app
        app._handle_upload_event(WorkflowEvent(job_id, 'verified', saved))
        self.assertEqual(self.server.post_count, 1)

    def test_connection_dialog_checks_api_credentials_without_saving_secrets(self):
        from frappe_settings import ConnectionDialog
        self.server.auth_mode = 'api'
        with patch('frappe_client.build_opener', side_effect=self.server.opener):
            dialog = ConnectionDialog(self.app, self.app._on_connected)
            dialog.api_key.set(self.server.api_key)
            dialog.api_secret.set(self.server.api_secret)
            dialog.test_connection()
            deadline = time.monotonic() + 3
            while dialog.winfo_exists() and time.monotonic() < deadline:
                self.app.update()
                time.sleep(.01)
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(dialog.api_key.get(), '')
        self.assertEqual(dialog.api_secret.get(), '')
        self.assertEqual(self.server.post_count, 0)

    def test_environment_api_credentials_connect_and_override_legacy_session(self):
        self.app.destroy()
        del self.app
        gc.collect()
        self.server.auth_mode = 'api'
        environment = {'SKYLINK_API_KEY': self.server.api_key, 'SKYLINK_API_SECRET': self.server.api_secret,
                       'SKYLINK_SESSION_ID': self.server.sid, 'SKYLINK_SITE_URL': 'https://skylink.example'}
        with patch.dict(os.environ, environment), patch('frappe_client.build_opener', side_effect=self.server.opener), patch.object(OCRApp, '_load_engine', lambda app: None):
            self.app = OCRApp()
            deadline = time.monotonic() + 3
            while self.app._frappe_client is None and time.monotonic() < deadline:
                self.app.update()
                time.sleep(.01)
            self.assertIsNotNone(self.app._frappe_client)
            self.assertFalse('SKYLINK_API_KEY' in os.environ, 'API key must be consumed')
            self.assertFalse('SKYLINK_API_SECRET' in os.environ, 'API secret must be consumed')
            self.assertFalse('SKYLINK_SESSION_ID' in os.environ, 'Legacy SID must be consumed')
        self.app.engine = object()
        self.capture()
        self.assertEqual(self.server.post_count, 1)

    def test_background_worker_does_not_retain_destroyed_tk_app(self):
        from capture_workflow import WorkflowEvent
        from rda_mapping import MappedRecord
        release = threading.Event()
        before = set(threading.enumerate())
        def worker(job, tool, client, emit):
            emit(WorkflowEvent(job.job_id, 'review_required', MappedRecord({'doctype': 'RDA Information', 'form_id': '0430'})))
            release.wait(5)
        reference = weakref.ref(self.app)
        with patch('ocr_app.run_capture_job', side_effect=worker):
            self.app._complete_capture(Image.new('RGB', (100, 100), 'white'))
            self.wait_done()
        for task in self.app.tk.splitlist(self.app.tk.call('after', 'info')):
            self.app.after_cancel(task)
        self.app.destroy()
        del self.app
        gc.collect()
        try:
            self.assertIsNone(reference(), 'Worker holds a Tk app reference after shutdown')
        finally:
            guard = reference()
            release.set()
            for thread in set(threading.enumerate()) - before:
                thread.join(2)
            del guard
            gc.collect()

    def test_old_review_callback_cannot_send_after_image_changes(self):
        self.capture()
        with patch('ocr_app.RDAReviewDialog') as dialog:
            self.app._open_review()
            callback = dialog.call_args.args[2]
        self.app._select_image(self.app.selected_image)
        self.assertFalse(callback({'doctype': 'RDA Information', 'form_id': '9999'}))
        self.assertEqual(self.server.post_count, 1)
        self.assertIsNone(self.app._mapping)

    def test_failed_engine_cannot_leave_new_capture_waiting_forever(self):
        self.app.engine = None
        with patch('ocr_app.messagebox.showerror'):
            self.app.result_queue.put(('engine_error', 'Engine unavailable'))
            self.app._drain_results()
        self.app._complete_capture(Image.new('RGB', (100, 100), 'white'))
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app._pending_upload)
        self.assertEqual(self.server.post_count, 0)

    def test_missing_languages_releases_pending_capture(self):
        self.app.engine = None
        self.app._complete_capture(Image.new('RGB', (100, 100), 'white'))
        with patch('ocr_app.messagebox.showwarning'):
            self.app.result_queue.put(('engine', object(), []))
            self.app._drain_results()
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app._pending_upload)

    def test_verification_details_show_expected_and_stored_field_values(self):
        self.server.mode = 'mismatch'
        self.capture()
        self.assertEqual(str(self.app.error_details_btn['state']), 'normal')
        self.app.error_details_btn.invoke()
        dialog = self.app._details_dialog
        values = dialog.tree.item('form_id', 'values')
        self.assertEqual(values, ('0430', '430'))
