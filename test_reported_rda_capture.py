"""Regression tests using the actual capture that mixed headings into values."""
from pathlib import Path
from dataclasses import replace
import json
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageFont

from ocr_core import extract_document
from rda_mapping import map_rda_document
from ocr_core import OCRWord

SOURCE = Path('tests_support/fixtures/reported_rda_capture.png')


class ReportedCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = extract_document(SOURCE)
        cls.mapping = map_rda_document(cls.document)

    def test_wrapped_summary_columns_return_values_without_header_text(self):
        expected = {
            'lob': '00002', 'co': '002', 'transaction_type': 'S',
            'ship_date': '2026-08-27', 'tendered_date': '2026-08-27',
            'revenue_date': '2026-08-27', 'origin_station': 'HHRKN',
            'destination_station': 'POMA', 'payor_code': '2',
            'summary_bill_to_account_number': '204819935',
            'bill_to_customer_name': 'PNG AIR FREIGHT LIMITED',
            'revenue_item_id': '2230000850298458', 'device_flag': 'INET', 'stage': 'Expected',
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(self.mapping.payload.get(key), value)
        self.assertNotIn('ors_flag', self.mapping.payload)
        self.assertNotIn('summary_invoice_number', self.mapping.payload)
        self.assertFalse(any('invalid date' in i.message for i in self.mapping.issues))

    def test_pipe_in_section_heading_does_not_omit_shipper_and_billing_cycle(self):
        expected = {'shipper_name': 'JAMES PARK', 'shipper_account_number': '976466357',
                    'shipper_city': 'TORRANCE', 'shipper_state': 'CA',
                    'shipper_zip_code': '90501', 'shipper_country': 'US', 'billing_cycle': '99'}
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(self.mapping.payload.get(key), value)

    def test_all_48_unambiguous_values_match_source_reference_and_pickup_stays_flagged(self):
        expected = json.loads(Path('rda_information_extracted.json').read_text(encoding='utf-8'))
        for key, value in expected.items():
            if key != 'pickup_type':
                with self.subTest(field=key):
                    self.assertEqual(self.mapping.payload.get(key), value)
        self.assertIn('pickup_type', [i.fieldname for i in self.mapping.issues])
        self.assertEqual(len(self.mapping.payload)-1, 49)

    def test_unreadable_grid_heading_omits_only_its_own_cell_and_blocks_send(self):
        table = self.document.tables[0]
        cells = list(table.cells)
        cells[1] = replace(cells[1], header=(OCRWord('Unreadable', cells[1].header[0].bbox, 99),))
        changed = replace(self.document, tables=(replace(table, cells=tuple(cells)),))
        mapping = map_rda_document(changed)
        self.assertNotIn('co', mapping.payload)
        self.assertEqual(mapping.payload['lob'], '00002')
        self.assertEqual(mapping.payload['transaction_type'], 'S')
        self.assertTrue(any(i.fieldname is None for i in mapping.issues))

    def test_capture_sends_all_49_fields_as_extracted_without_review(self):
        from capture_workflow import CaptureJob, run_capture_job
        from frappe_client import FrappeClient
        from tests_support.frappe_fixture import FrappeFixture
        server = FrappeFixture()
        server.auth_mode = 'api'
        client = FrappeClient('https://skylink.example', api_key=server.api_key, api_secret=server.api_secret, opener=server.opener())
        job = CaptureJob(1, SOURCE, 'eng', True)
        events = []
        with patch('capture_workflow.extract_document', return_value=self.document):
            run_capture_job(job, object(), client, events.append)
        self.assertEqual(events[-1].phase, 'verified')
        self.assertEqual(server.post_count, 1)
        self.assertFalse(any(e.phase == 'review_required' for e in events))
        self.assertEqual({k: events[-1].data.stored[k] for k in self.mapping.payload}, self.mapping.payload)
        self.assertEqual(events[-1].data.stored['pickup_type'], '0')

    def test_same_grid_reads_changed_identifiers_and_dates_from_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.open(SOURCE).convert('RGB')
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 10)
            draw.rectangle((39,46,58,88), fill='white')
            draw.text((39,62), '007', font=font, fill=(77,19,139))
            draw.rectangle((97,46,156,88), fill='white')
            draw.text((97,62), '09/12/2027', font=font, fill=(77,19,139))
            path = Path(directory) / 'changed.png'
            image.save(path)
            mapped = map_rda_document(extract_document(path))
            self.assertEqual(mapped.payload.get('co'), '007')
            self.assertEqual(mapped.payload.get('ship_date'), '2027-09-12')
