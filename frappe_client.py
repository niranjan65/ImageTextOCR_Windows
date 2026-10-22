"""Token/session-authenticated, create-only Frappe client with read-back verification."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from http.client import HTTPException
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from rda_mapping import load_schema, normalize_value

DEFAULT_SITE = 'https://skylink.dev.advtinni.com'


class FrappeError(Exception):
    pass


class SaveOutcomeUnknown(FrappeError):
    pass


@dataclass
class ConnectionInfo:
    user: str
    schema: dict


@dataclass
class SavedRecord:
    name: str
    url: str
    submitted: dict[str, object]
    stored: dict[str, object]


class VerificationError(FrappeError):
    def __init__(self, saved, mismatches):
        super().__init__('Record was created, but saved-field verification failed. Open the record before sending again.')
        self.saved = saved
        self.mismatches = mismatches


class _OriginRedirect(HTTPRedirectHandler):
    handler_order = 50
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.get_method() != 'GET':
            raise SaveOutcomeUnknown('The save redirected unexpectedly. Check the site before another explicit send.')
        parsed = urlsplit(urljoin(req.full_url, newurl))
        if (parsed.scheme, parsed.netloc.lower()) != self.origin:
            raise FrappeError('Refusing a redirect outside the configured HTTPS site.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def https_request(self, request):
        parsed = urlsplit(request.full_url)
        if (parsed.scheme, parsed.netloc.lower()) != self.origin:
            raise FrappeError('Refusing to send credentials outside the configured HTTPS site.')
        return request


class FrappeClient:
    def __init__(self, base_url, sid=None, timeout=20.0, opener=None, *, api_key=None, api_secret=None):
        parsed = urlsplit(base_url.strip())
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise FrappeError('Enter an HTTPS site URL without a path, credentials, query or fragment.')
        self.auth_mode = 'api' if api_key is not None or api_secret is not None else 'session'
        sid = sid.strip() if isinstance(sid, str) else ''
        if self.auth_mode == 'api':
            if sid:
                raise FrappeError('Choose API credentials or a session ID, not both.')
            if not all(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,512}', value.strip()) for value in (api_key, api_secret)):
                raise FrappeError('Enter both a valid API key and API secret.')
            api_key, api_secret = api_key.strip(), api_secret.strip()
        elif not re.fullmatch(r'[A-Za-z0-9_-]{16,512}', sid):
            raise FrappeError('Enter a valid existing session ID.')
        self.base_url = 'https://' + parsed.netloc.lower()
        self._sid = sid
        self._api_key = api_key or ''
        self._api_secret = api_secret or ''
        self._csrf = None
        self.timeout = timeout
        self._opener = opener or build_opener()
        self._opener.add_handler(_OriginRedirect(('https', parsed.netloc.lower())))

    def _safe(self, value):
        message = str(value)
        for secret in sorted(filter(None, (self._sid, self._api_key, self._api_secret, self._csrf)), key=len, reverse=True):
            message = message.replace(secret, '[redacted]')
        return re.sub(r'<[^>]*>', '', message)[:500]

    def _request(self, path, payload=None, cancelled=None):
        method = 'POST' if payload is not None else 'GET'
        headers = {'Accept': 'application/json'}
        if self.auth_mode == 'api':
            headers['Authorization'] = 'token ' + self._api_key + ':' + self._api_secret
        else:
            headers['Cookie'] = 'sid=' + self._sid
        data = None
        if payload is not None:
            headers.update({'Content-Type': 'application/json',
                            'Origin': self.base_url, 'Referer': self.base_url + '/desk'})
            if self.auth_mode == 'session':
                headers['X-Frappe-CSRF-Token'] = self._csrf
            data = json.dumps(payload, allow_nan=False).encode('utf-8')
        if payload is not None and cancelled is not None and cancelled.is_set():
            raise FrappeError('Upload cancelled before sending.')
        try:
            with self._opener.open(Request(self.base_url + path, data=data, headers=headers, method=method), timeout=self.timeout) as response:
                raw = response.read().decode('utf-8')
                return json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw
        except HTTPError as error:
            if payload is not None and (300 <= error.code < 400 or error.code >= 500 or error.code in (408, 429)):
                raise SaveOutcomeUnknown('The server did not confirm the save. Check the site before another explicit send.') from None
            if error.code == 401:
                reason = 'Authentication failed; check credentials in Connection Settings.'
            elif error.code == 403:
                reason = 'Permission denied; check API user access and credentials in Connection Settings.'
            else:
                reason = 'Request was rejected by Skylink.'
            raise FrappeError(f'{reason} HTTP {error.code}.') from None
        except (URLError, OSError, ValueError, HTTPException) as error:
            if payload is not None:
                raise SaveOutcomeUnknown('The save response was lost. The record may exist; check the site before sending again.') from None
            raise FrappeError('Could not read the configured site. Check the connection and credentials, then try again.') from None

    def test_connection(self):
        user_reply = self._request('/api/method/frappe.auth.get_logged_user')
        user = user_reply.get('message') if isinstance(user_reply, dict) else None
        if not user or user == 'Guest':
            raise FrappeError('Authentication failed. Check the credentials in Connection Settings.')
        reply = self._request('/api/resource/DocType/RDA%20Information')
        if not isinstance(reply, dict) or not isinstance(reply.get('data', {}).get('fields'), list):
            raise FrappeError('RDA Information is not accessible with these credentials.')
        return ConnectionInfo(self._safe(user), reply['data'])

    def create_and_verify(self, payload, cancelled=None):
        schema = load_schema()
        fields = {f['fieldname']: f for f in schema['fields']}
        if payload.get('doctype') != 'RDA Information' or any(key not in fields for key in payload if key != 'doctype'):
            raise FrappeError('Payload must target the configured RDA Information fields.')
        if not any(key != 'doctype' for key in payload):
            raise FrappeError('No captured field values are available to send.')
        submitted = {}
        for key, value in payload.items():
            if key == 'doctype':
                continue
            try:
                submitted[key] = normalize_value(value, fields[key])
            except (ValueError, InvalidOperation):
                # OCR uncertainty is not a send gate. ERPNext validates the raw value.
                submitted[key] = value
        submitted['doctype'] = 'RDA Information'
        self.test_connection()
        if self.auth_mode == 'session':
            html = self._request('/desk')
            match = re.search(r'frappe\.csrf_token\s*=\s*[\x22\x27]([^\x22\x27]+)', html) if isinstance(html, str) else None
            if not match:
                match = re.search(r'\x22csrf_token\x22\s*:\s*\x22([^\x22]+)', html) if isinstance(html, str) else None
            if not match:
                raise FrappeError('Session CSRF token is unavailable. Reconnect to Skylink.')
            self._csrf = match.group(1)
        reply = self._request('/api/resource/RDA%20Information', submitted, cancelled=cancelled)
        data = reply.get('data') if isinstance(reply, dict) else None
        name = data.get('name') if isinstance(data, dict) else None
        if not isinstance(name, str) or not name:
            raise SaveOutcomeUnknown('The server did not return a record name. Check the site before sending again.')
        saved = SavedRecord(name, self.base_url + '/desk/rda-information/' + quote(name, safe=''), submitted, {})
        try:
            fetched = self._request('/api/resource/RDA%20Information/' + quote(name, safe=''))
            saved.stored = fetched['data']
            if not isinstance(saved.stored, dict) or saved.stored.get('name') != name:
                raise ValueError('Unexpected saved document identity')
            mismatches = {}
            for key, expected in submitted.items():
                actual = saved.stored.get(key)
                if key != 'doctype' and fields[key]['fieldtype'] in ('Currency', 'Float', 'Int'):
                    try:
                        same = actual is not None and Decimal(str(expected)) == Decimal(str(actual))
                    except InvalidOperation:
                        same = type(actual) is type(expected) and actual == expected
                else:
                    same = type(actual) is type(expected) and actual == expected
                if not same:
                    mismatches[key] = {'expected': expected, 'actual': actual}
        except (FrappeError, ValueError, KeyError, TypeError, InvalidOperation):
            raise VerificationError(saved, {'verification': 'Could not fetch or compare the saved record.'}) from None
        if mismatches:
            raise VerificationError(saved, mismatches)
        return saved
