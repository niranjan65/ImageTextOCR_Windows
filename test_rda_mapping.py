import importlib.util
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from ocr_core import OCRDocument, OCRWord, extract_document
from tests_support.rda_fixture import word_document, render_rda_fixture


class RDAMappingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("rda_mapping"), "RDA mapper is missing")
        import rda_mapping
        self.mapper = rda_mapping
        self.values = json.loads(Path("rda_information_extracted.json").read_text(encoding="utf-8"))
        self.values = {k: ("08/27/2026" if "date" in k else v) for k, v in self.values.items() if k != "doctype"}

    def test_section_labels_map_all_49_fields_without_inventing_blanks(self):
        result = self.mapper.map_rda_document(word_document(self.values))
        self.assertEqual(result.issues, [])
        expected = json.loads(Path("rda_information_extracted.json").read_text(encoding="utf-8"))
        self.assertEqual(result.payload, expected)
        self.assertNotIn("bill_to_name", result.payload)

    def test_mapping_uses_new_capture_values_at_different_scale_and_origin(self):
        self.values.update(shipper_name="ALICE CHEN", recipient_name="BOB HILL", pickup_type="X", form_id="0099", revenue_item_id="2230000850298001")
        result = self.mapper.map_rda_document(word_document(self.values, scale=2, shift=(40, 35)))
        self.assertEqual(result.issues, [])
        self.assertEqual(result.payload["shipper_name"], "ALICE CHEN")
        self.assertEqual(result.payload["recipient_name"], "BOB HILL")
        self.assertEqual(result.payload["pickup_type"], "X")
        self.assertEqual(result.payload["form_id"], "0099")
        self.assertEqual(result.payload["revenue_item_id"], "2230000850298001")

    def test_low_confidence_identifier_and_invalid_date_block_send(self):
        self.values["transaction_ship_date"] = "02/31/2026"
        doc = word_document(self.values)
        doc = replace(doc, words=tuple(replace(w, confidence=25) if w.content == "0430" else w for w in doc.words))
        result = self.mapper.map_rda_document(doc)
        self.assertIn("form_id", [i.fieldname for i in result.issues])
        self.assertIn("transaction_ship_date", [i.fieldname for i in result.issues])

    def test_unrelated_or_ambiguous_capture_does_not_map_names(self):
        doc = OCRDocument("Name: JAMES PARK", (OCRWord("Name:", (10, 10, 65, 30), 99), OCRWord("JAMES", (85, 10, 140, 30), 99)), 300, 100)
        result = self.mapper.map_rda_document(doc)
        self.assertTrue(result.issues)
        self.assertNotIn("shipper_name", result.payload)
        self.assertNotIn("recipient_name", result.payload)

    def test_competing_assignments_are_flagged(self):
        doc = word_document(self.values)
        # Add a second Form ID line between the last transaction row and Invoice.
        extras = (OCRWord("Form", (15, 325, 60, 347), 99), OCRWord("ID:", (65, 325, 95, 347), 99), OCRWord("9999", (225, 325, 280, 347), 99))
        result = self.mapper.map_rda_document(replace(doc, words=doc.words + extras))
        self.assertIn("form_id", [i.fieldname for i in result.issues])

    def test_live_schema_resource_loads_from_packaged_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            schema = self.mapper.load_schema()
            Path(directory, "rda_schema.json").write_text(json.dumps(schema), encoding="utf-8")
            with patch.object(sys, "_MEIPASS", directory, create=True):
                self.assertEqual(len(self.mapper.load_schema()["fields"]), 100)

    def test_actual_ocr_maps_generated_rda_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rda.png"
            render_rda_fixture(path, self.values)
            result = self.mapper.map_rda_document(extract_document(path))
            self.assertEqual(result.payload.get("shipper_name"), "JAMES PARK")
            self.assertEqual(result.payload.get("recipient_name"), "TRINNEE PECUNDO")
            self.assertEqual(result.payload.get("form_id"), "0430")
            self.assertEqual(result.payload.get("revenue_item_id"), "2230000850298458")
            self.assertEqual(result.payload.get("net_amount"), 108.28)

    def test_unknown_and_invalid_values_fail_validation(self):
        issues = self.mapper.validate_payload({"doctype": "RDA Information", "bogus": "a", "net_amount": "abc", "ship_date": "bad"})
        self.assertEqual({i.fieldname for i in issues}, {"bogus", "net_amount", "ship_date"})
        self.assertTrue(self.mapper.validate_payload({"doctype": "RDA Information"}))

    def test_missing_recipient_heading_never_reassigns_recipient_to_shipper(self):
        doc = word_document({'recipient_name': 'BOB HILL'})
        doc = replace(doc, words=tuple(w for w in doc.words if not (w.bbox[1] == 520 and w.bbox[0] >= 680)))
        result = self.mapper.map_rda_document(doc)
        self.assertNotEqual(result.payload.get('shipper_name'), 'BOB HILL')
        self.assertTrue(result.issues)

    def test_missing_final_summary_heading_cannot_fill_previous_flag(self):
        doc = word_document({'stage': 'Expected'})
        doc = replace(doc, words=tuple(w for w in doc.words if not (w.content == 'Stage' and w.bbox[1] == 12)))
        result = self.mapper.map_rda_document(doc)
        self.assertNotEqual(result.payload.get('ors_flag'), 'Expected')
        self.assertTrue(result.issues)

    def test_party_state_zip_and_country_share_one_row(self):
        doc = word_document({})
        # Actual source layout: three labels/values in one party row.
        row = [('State:', 15, 'CA', 115), ('Zip:', 255, '90210', 315), ('Cntry/Terr:', 420, 'US', 540)]
        words = [w for w in doc.words if not (w.bbox[1] >= 760 and w.bbox[1] < 850 and w.bbox[0] < 680)]
        for label, lx, value, vx in row:
            words.extend((OCRWord(label, (lx, 770, lx+(40 if label == 'Zip:' else 85), 792), 99), OCRWord(value, (vx, 770, vx+50, 792), 99)))
        result = self.mapper.map_rda_document(replace(doc, words=tuple(words)))
        self.assertEqual(result.payload.get('shipper_state'), 'CA')
        self.assertEqual(result.payload.get('shipper_zip_code'), '90210')
        self.assertEqual(result.payload.get('shipper_country'), 'US')
