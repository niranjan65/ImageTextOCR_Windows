import importlib.util
import unittest
from threading import Event
from tests_support.frappe_fixture import FrappeFixture


class FrappeClientTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('frappe_client'), 'Frappe client is missing')
        import frappe_client
        self.module = frappe_client
        self.server = FrappeFixture()
        self.client = frappe_client.FrappeClient('https://skylink.example', self.server.sid, opener=self.server.opener())
        self.payload = {'doctype': 'RDA Information', 'revenue_item_id': '2230000850298458', 'form_id': '0430', 'net_amount': 108.28, 'currency': 'USD'}

    def test_create_fetch_verify_preserves_identifiers_and_numeric_values(self):
        saved = self.client.create_and_verify(self.payload)
        self.assertEqual(saved.stored['form_id'], '0430')
        self.assertEqual(saved.stored['net_amount'], 108.28)
        self.assertEqual(self.server.post_count, 1)
        self.assertTrue(saved.url.startswith('https://skylink.example/desk/rda-information/'))

    def test_two_intentional_submissions_always_create_distinct_records(self):
        first = self.client.create_and_verify(self.payload)
        second = self.client.create_and_verify(self.payload)
        self.assertNotEqual(first.name, second.name)
        self.assertEqual(self.server.post_count, 2)
        self.assertFalse(any(r.method in ('PUT', 'PATCH', 'DELETE') for r in self.server.requests))

    def test_lost_insert_response_is_unknown_and_is_never_retried(self):
        self.server.mode = 'lost'
        with self.assertRaises(self.module.SaveOutcomeUnknown):
            self.client.create_and_verify(self.payload)
        self.assertEqual(len(self.server.documents), 1)
        self.assertEqual(self.server.post_count, 1)

    def test_verification_mismatch_keeps_saved_record_link(self):
        self.server.mode = 'mismatch'
        with self.assertRaises(self.module.VerificationError) as context:
            self.client.create_and_verify(self.payload)
        self.assertIn('form_id', context.exception.mismatches)
        self.assertIn('/new-1', context.exception.saved.url)
        self.assertEqual(self.server.post_count, 1)

    def test_guest_expired_and_denied_sessions_are_clear_definitive_errors(self):
        for mode in ('guest', 'expired', 'denied'):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaises(self.module.FrappeError) as context:
                    self.client.create_and_verify(self.payload)
                self.assertNotIn(self.server.sid, str(context.exception))
                self.assertEqual(len(self.server.documents), 0)

    def test_https_and_origin_checks_prevent_credential_forwarding(self):
        with self.assertRaises(self.module.FrappeError):
            self.module.FrappeClient('http://skylink.example', self.server.sid)
        self.server.mode = 'redirect'
        with self.assertRaises(self.module.FrappeError):
            self.client.test_connection()
        self.assertEqual(len(self.server.requests), 1)

    def test_field_types_links_and_required_values_are_left_to_erpnext(self):
        field = next(f for f in self.server.schema['fields'] if f['fieldname'] == 'form_id')
        field['fieldtype'] = 'Int'
        self.client.create_and_verify(self.payload)
        field['fieldtype'] = 'Data'
        self.server.mode = 'missing_link'
        self.server.schema['fields'].append({'fieldname': 'new_required', 'fieldtype': 'Data', 'reqd': 1})
        self.client.create_and_verify(self.payload)
        self.assertEqual(self.server.post_count, 2)
        self.assertFalse(any('/Currency/' in r.full_url for r in self.server.requests))

    def test_invalid_date_and_amount_are_posted_as_captured(self):
        saved = self.client.create_and_verify({'doctype': 'RDA Information', 'ship_date': 'not-a-date', 'net_amount': 'OCR text'})
        self.assertEqual(saved.stored['ship_date'], 'not-a-date')
        self.assertEqual(saved.stored['net_amount'], 'OCR text')
        self.assertEqual(self.server.post_count, 1)

    def test_erpnext_rejection_is_reported_after_one_send_without_retry(self):
        self.server.mode = 'invalid_values'
        with self.assertRaises(self.module.FrappeError) as caught:
            self.client.create_and_verify({'doctype': 'RDA Information', 'ship_date': 'not-a-date'})
        self.assertIn('422', str(caught.exception))
        self.assertEqual(self.server.post_count, 1)
        self.assertEqual(len(self.server.documents), 0)

    def test_unknown_field_is_rejected_before_network_or_post(self):
        with self.assertRaises(self.module.FrappeError):
            self.client.create_and_verify({**self.payload, 'bogus': 'test'})
        self.assertEqual(self.server.requests, [])

    def test_malformed_insert_response_is_unknown_without_retry(self):
        self.server.mode = 'malformed_post'
        with self.assertRaises(self.module.SaveOutcomeUnknown):
            self.client.create_and_verify(self.payload)
        self.assertEqual(self.server.post_count, 1)

    def test_malformed_saved_data_keeps_record_link_for_verification(self):
        for mode in ('malformed_get', 'bad_number'):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaises(self.module.VerificationError) as context:
                    self.client.create_and_verify(self.payload)
                self.assertTrue(context.exception.saved.url)

    def test_insert_redirect_is_unknown_and_not_followed_or_retried(self):
        for mode in ('post_redirect', 'post_307', 'post_308'):
            self.server.mode = mode
            with self.subTest(mode=mode), self.assertRaises(self.module.SaveOutcomeUnknown):
                self.client.create_and_verify(self.payload)
        self.assertEqual(self.server.post_count, 3)
        self.assertEqual(len(self.server.documents), 3)

    def test_truncated_verification_keeps_known_saved_record_link(self):
        self.server.mode = 'truncated_verify'
        with self.assertRaises(self.module.VerificationError) as context:
            self.client.create_and_verify(self.payload)
        self.assertTrue(context.exception.saved.url.endswith('/new-1'))
        self.assertEqual(self.server.post_count, 1)


class APICredentialTests(unittest.TestCase):
    def setUp(self):
        import frappe_client
        self.module = frappe_client
        self.server = FrappeFixture()
        self.server.auth_mode = 'api'
        self.payload = {'doctype': 'RDA Information', 'form_id': '0430'}

    def client(self, **overrides):
        options = {'api_key': self.server.api_key, 'api_secret': self.server.api_secret}
        options.update(overrides)
        return self.module.FrappeClient('https://skylink.example', opener=self.server.opener(), **options)

    def test_token_creates_and_verifies_without_session_or_desk_csrf(self):
        client = self.client()
        first = client.create_and_verify(self.payload)
        second = client.create_and_verify(self.payload)
        self.assertEqual(first.stored['form_id'], '0430')
        self.assertNotEqual(first.name, second.name)
        self.assertEqual(self.server.post_count, 2)
        self.assertFalse(any('/desk' in r.full_url for r in self.server.requests))

    def test_partial_invalid_or_mixed_credentials_fail_before_requests(self):
        for options in ({'api_secret': ''}, {'api_key': ''}, {'api_key': 'bad\nheader'}, {'api_secret': 'bad:secret'}, {'sid': self.server.sid}):
            with self.subTest(options=list(options)), self.assertRaises(self.module.FrappeError):
                self.client(**options)
        self.assertEqual(self.server.requests, [])

    def test_token_redirect_does_not_forward_credentials(self):
        self.server.mode = 'redirect'
        with self.assertRaises(self.module.FrappeError):
            self.client().test_connection()
        self.assertEqual(len(self.server.requests), 1)

    def test_cancel_during_token_preflight_prevents_post(self):
        cancelled = Event()
        self.server.on_schema = cancelled.set
        with self.assertRaises(self.module.FrappeError):
            self.client().create_and_verify(self.payload, cancelled=cancelled)
        self.assertEqual(self.server.post_count, 0)

    def test_lost_token_save_is_unknown_without_retry(self):
        self.server.mode = 'lost'
        with self.assertRaises(self.module.SaveOutcomeUnknown):
            self.client().create_and_verify(self.payload)
        self.assertEqual(self.server.post_count, 1)
        self.assertEqual(len(self.server.documents), 1)

    def test_credentials_are_redacted_in_displayed_user(self):
        client = self.client()
        self.assertEqual(client._safe(self.server.api_key + ' ' + self.server.api_secret), '[redacted] [redacted]')

    def test_api_permission_denial_is_clear_without_exposing_credentials(self):
        self.server.mode = 'denied'
        with self.assertRaises(self.module.FrappeError) as caught:
            self.client().create_and_verify(self.payload)
        self.assertIn('permission', str(caught.exception).lower())
        self.assertNotIn(self.server.api_secret, str(caught.exception))
        self.assertEqual(len(self.server.documents), 0)
