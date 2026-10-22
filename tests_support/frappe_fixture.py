"""Stateful HTTP fixture: real urllib requests, no external networking."""
from email.message import Message
from io import BytesIO
import json
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from http.client import IncompleteRead


class FrappeFixture(BaseHandler):
    handler_order = 100
    def __init__(self):
        from rda_mapping import load_schema
        self.schema = load_schema()
        self.documents = {}
        self.requests = []
        self.mode = None
        self.sid = "fixture-session-secret"
        self.api_key = 'fixture-api-key'
        self.api_secret = 'fixture-api-secret'
        self.auth_mode = 'session'
        self.on_schema = None
        self.on_desk = None

    def response(self, request, body, status=200, location=None):
        headers = Message()
        headers['Content-Type'] = 'text/html' if isinstance(body, str) else 'application/json'
        if location:
            headers['Location'] = location
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        response = addinfourl(BytesIO(raw), headers, request.full_url, status)
        response.msg = 'Fixture'
        return response

    def https_open(self, request):
        self.requests.append(request)
        assert urlsplit(request.full_url).netloc == 'skylink.example', 'Credential left permitted origin'
        if self.auth_mode == 'api':
            assert request.get_header('Authorization') == 'token fixture-api-key:fixture-api-secret'
            assert request.get_header('Cookie') is None
            assert request.get_header('X-frappe-csrf-token') is None
        else:
            assert request.get_header('Cookie') == 'sid=' + self.sid
            assert request.get_header('Authorization') is None
        path = unquote(urlsplit(request.full_url).path)
        if self.mode == 'redirect':
            return self.response(request, {}, 302, 'https://other.example/steal')
        if path.endswith('get_logged_user'):
            return self.response(request, {'message': 'Guest' if self.mode == 'guest' else 'tester@example.com'})
        if path == '/api/resource/DocType/RDA Information':
            if self.on_schema:
                self.on_schema()
            return self.response(request, {'data': self.schema})
        if path in ('/desk', '/app'):
            if self.on_desk:
                self.on_desk()
            return self.response(request, '<script>frappe.csrf_token = "fixture-csrf";</script>')
        if path == '/api/resource/Currency/USD':
            if self.mode == 'missing_link':
                return self.response(request, {'exc_type': 'DoesNotExistError'}, 404)
            return self.response(request, {'data': {'name': 'USD'}})
        if path == '/api/resource/RDA Information' and request.method == 'POST':
            if self.auth_mode == 'session':
                assert request.get_header('X-frappe-csrf-token') == 'fixture-csrf'
            if self.mode == 'expired':
                return self.response(request, {'exc_type': 'AuthenticationError'}, 401)
            if self.mode == 'denied':
                return self.response(request, {'exc_type': 'PermissionError'}, 403)
            if self.mode == 'invalid_values':
                return self.response(request, {'exc_type': 'ValidationError'}, 422)
            name = 'new-' + str(len(self.documents) + 1)
            self.documents[name] = {**json.loads(request.data), 'name': name}
            if self.mode == 'lost':
                raise OSError('Response lost after insertion')
            if self.mode == 'malformed_post':
                return self.response(request, {'data': None})
            if self.mode in ('post_redirect', 'post_307', 'post_308'):
                status = {'post_redirect': 302, 'post_307': 307, 'post_308': 308}[self.mode]
                return self.response(request, {}, status, 'https://other.example/after-insert')
            return self.response(request, {'data': self.documents[name]})
        if path.startswith('/api/resource/RDA Information/'):
            if self.mode == 'truncated_verify':
                raise IncompleteRead(b'{"data":', 20)
            name = path.rsplit('/', 1)[1]
            data = dict(self.documents[name])
            if self.mode == 'malformed_get':
                return self.response(request, {'data': None})
            if self.mode == 'bad_number':
                data['net_amount'] = 'not-a-number'
            if self.mode == 'mismatch':
                data['form_id'] = '430'
            return self.response(request, {'data': data})
        return self.response(request, {'exc_type': 'DoesNotExistError'}, 404)

    def opener(self):
        return build_opener(self)

    @property
    def post_count(self):
        return sum(r.method == 'POST' for r in self.requests)
