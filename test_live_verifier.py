import importlib.util
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageFont
from ocr_core import extract_text
from tests_support.frappe_fixture import FrappeFixture
from tests_support.rda_fixture import word_document
from frappe_client import FrappeClient


class LiveVerifierTests(unittest.TestCase):
    def test_api_verifier_sends_low_confidence_capture_without_recording_tokens(self):
        import verify_rda_live
        server = FrappeFixture()
        server.auth_mode = 'api'
        environment = {'SKYLINK_API_KEY': server.api_key, 'SKYLINK_API_SECRET': server.api_secret,
                       'SKYLINK_SESSION_ID': server.sid}
        document = word_document({'form_id': '0430'})
        document = replace(document, words=tuple(replace(w, confidence=10) for w in document.words))
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'api-report.json'
            with patch.dict(os.environ, environment), patch('frappe_client.build_opener', side_effect=server.opener), patch('verify_rda_live.extract_document', return_value=document):
                code = verify_rda_live.main(['--site', 'https://skylink.example', '--image', 'fixture.png', '--report', str(report)])
                self.assertFalse('SKYLINK_API_KEY' in os.environ, 'API key environment variable must be consumed')
                self.assertFalse('SKYLINK_API_SECRET' in os.environ, 'API secret environment variable must be consumed')
            self.assertEqual(code, 0)
            text = report.read_text(encoding='utf-8')
            self.assertNotIn(server.api_key, text)
            self.assertNotIn(server.api_secret, text)
            self.assertEqual(json.loads(text)['status'], 'verified')
            self.assertEqual(server.post_count, 1)

    def test_opt_in_verifier_creates_requested_count_without_recording_sid(self):
        self.assertIsNotNone(importlib.util.find_spec('verify_rda_live'), 'Opt-in live verifier missing')
        import verify_rda_live
        server = FrappeFixture()
        client = FrappeClient('https://skylink.example', server.sid, opener=server.opener())
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            with patch.dict(os.environ, {'SKYLINK_SESSION_ID': server.sid}), patch('verify_rda_live.FrappeClient', return_value=client), patch('verify_rda_live.extract_document', return_value=word_document({'form_id': '0430'})):
                code = verify_rda_live.main(['--site', 'https://skylink.example', '--image', 'fixture.png', '--create-count', '2', '--report', str(report), '--synthetic-fixture'])
            self.assertEqual(code, 0)
            text = report.read_text(encoding='utf-8')
            self.assertNotIn(server.sid, text)
            self.assertEqual(len(json.loads(text)['records']), 2)
            self.assertEqual(server.post_count, 2)

    def test_bundled_engine_can_read_its_packaged_english_model(self):
        source = Path('C:/Program Files/Tesseract-OCR')
        if not (source / 'tesseract.exe').exists():
            self.skipTest('Installed Windows Tesseract required for bundle verification')
        with tempfile.TemporaryDirectory() as directory:
            bundled = Path(directory) / 'tesseract'
            (bundled / 'tessdata').mkdir(parents=True)
            for file in [source / 'tesseract.exe', *source.glob('*.dll')]:
                shutil.copy2(file, bundled / file.name)
            shutil.copy2(source / 'tessdata/eng.traineddata', bundled / 'tessdata/eng.traineddata')
            path = Path(directory) / 'text.png'
            image = Image.new('RGB', (700, 180), 'white')
            ImageDraw.Draw(image).text((25, 50), 'BUNDLE 0430', font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 40), fill='black')
            image.save(path)
            with patch.object(sys, '_MEIPASS', directory, create=True), patch.dict(os.environ):
                self.assertIn('BUNDLE 0430', extract_text(path))

    def test_preferences_persist_only_url_and_auto_send(self):
        import frappe_settings
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            with patch('frappe_settings._preference_path', return_value=path):
                frappe_settings.save_preferences('https://skylink.example', True)
                self.assertEqual(json.loads(path.read_text()), {'site_url': 'https://skylink.example', 'auto_send': True})

    def test_non_object_preferences_fall_back_to_safe_defaults(self):
        import frappe_settings
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text('[]', encoding='utf-8')
            with patch('frappe_settings._preference_path', return_value=path):
                self.assertTrue(frappe_settings.load_preferences()['auto_send'])
