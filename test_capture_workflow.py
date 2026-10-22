import importlib.util
import unittest
from pathlib import Path
from dataclasses import replace
import tempfile
from unittest.mock import patch
from frappe_client import FrappeClient
from tests_support.frappe_fixture import FrappeFixture
from tests_support.rda_fixture import word_document
from tests_support.rda_fixture import render_rda_fixture


class CaptureWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('capture_workflow'), 'Capture workflow missing')
        import capture_workflow
        self.module = capture_workflow
        self.server = FrappeFixture()
        self.client = FrappeClient('https://skylink.example', self.server.sid, opener=self.server.opener())
        self.doc = word_document({'form_id': '0430', 'shipper_name': 'JAMES PARK'})
        self.events = []
        self.job = capture_workflow.CaptureJob(1, Path('fixture.png'), 'eng', True)

    def run_job(self, client=True):
        with patch('capture_workflow.extract_document', return_value=self.doc):
            self.module.run_capture_job(self.job, object(), self.client if client else None, self.events.append)

    def test_automatic_capture_creates_and_verifies_once(self):
        self.run_job()
        self.assertEqual(self.server.post_count, 1)
        self.assertEqual(self.events[-1].phase, 'verified')
        self.assertEqual(self.events[-1].data.stored['form_id'], '0430')

    def test_unconfigured_capture_stays_available_without_sending(self):
        self.run_job(False)
        self.assertEqual(self.events[-1].phase, 'review_required')
        self.assertEqual(self.server.post_count, 0)

    def test_invalid_looking_captured_date_is_sent_without_review(self):
        self.doc = word_document({'transaction_ship_date': 'bad'})
        self.run_job()
        self.assertEqual(self.events[-1].phase, 'verified')
        self.assertEqual(self.events[-1].data.stored['transaction_ship_date'], 'bad')
        self.assertEqual(self.server.post_count, 1)

    def test_low_confidence_values_send_as_captured_without_confirmation(self):
        self.doc = replace(self.doc, words=tuple(replace(w, confidence=20) for w in self.doc.words))
        self.run_job()
        self.assertEqual(self.events[-1].phase, 'verified')
        self.assertEqual(self.events[-1].data.stored['form_id'], '0430')
        self.assertFalse(any(e.phase == 'review_required' for e in self.events))

    def test_expired_session_retains_mapped_values(self):
        self.server.mode = 'expired'
        self.run_job()
        self.assertEqual(self.events[-1].phase, 'failed')
        mapping = next(e.data for e in self.events if e.phase == 'mapped')
        self.assertEqual(mapping.payload['form_id'], '0430')

    def test_unknown_save_and_verification_failure_are_distinct(self):
        for mode, phase in [('lost', 'outcome_unknown'), ('mismatch', 'verification_failed')]:
            self.server.mode = mode
            self.events.clear()
            self.run_job()
            self.assertEqual(self.events[-1].phase, phase)
            if mode == 'mismatch':
                self.assertTrue(self.events[-1].data.saved.url)
        self.assertEqual(self.server.post_count, 2)

    def test_cancelled_job_cannot_start_a_send(self):
        self.job.cancelled.set()
        self.run_job()
        self.assertEqual(self.server.post_count, 0)

    def test_actual_tesseract_capture_maps_creates_and_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'generated_rda.png'
            render_rda_fixture(path, {'form_id': '0430', 'shipper_name': 'JAMES PARK'})
            from ocr_core import get_ocr_engine
            job = self.module.CaptureJob(7, path, 'eng', True)
            self.module.run_capture_job(job, get_ocr_engine(), self.client, self.events.append)
            self.assertEqual(self.events[-1].phase, 'verified')
            self.assertEqual(self.events[-1].data.stored['shipper_name'], 'JAMES PARK')
            self.assertEqual(self.server.post_count, 1)

    def test_unexpected_send_exception_still_emits_terminal_state(self):
        with patch.object(self.client, 'create_and_verify', side_effect=RuntimeError('unexpected response')):
            self.module.send_reviewed_job(self.job, {'doctype': 'RDA Information', 'form_id': '0430'}, self.client, self.events.append)
        self.assertEqual(self.events[-1].phase, 'outcome_unknown')

    def test_shutdown_during_http_preflight_prevents_post(self):
        self.server.on_desk = self.job.cancelled.set
        self.run_job()
        self.assertEqual(self.server.post_count, 0)
        self.assertEqual(self.server.documents, {})
