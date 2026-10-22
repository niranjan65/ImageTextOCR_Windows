"""Section-aware mapping of local OCR evidence into RDA Information fields."""
from dataclasses import dataclass, field
from datetime import datetime, date
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import sys

from ocr_core import OCRDocument, OCRWord, word_lines


@dataclass(frozen=True)
class MappingIssue:
    fieldname: str | None
    message: str
    raw_value: str | None = None


@dataclass
class MappedRecord:
    payload: dict[str, object]
    issues: list[MappingIssue] = field(default_factory=list)
    evidence: dict[str, tuple[OCRWord, ...]] = field(default_factory=dict)


def load_schema() -> dict:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return json.loads((root / "rda_schema.json").read_text(encoding="utf-8"))


def _norm(text):
    normalized = re.sub(r"[^a-z0-9]", "", text.lower().replace('|', 'i').replace("#", "number"))
    # OCR can collapse a doubled letter in a label (Billing -> Biling).
    return re.sub(r'([a-z])\1+', r'\1', normalized)


def _box(words):
    return min(w.bbox[0] for w in words), min(w.bbox[1] for w in words), max(w.bbox[2] for w in words), max(w.bbox[3] for w in words)


def _hits(words, entries):
    """Longest non-overlapping label phrases on each OCR line."""
    hits = []
    aliases = [(key, _norm(alias)) for key, items in entries for alias in items if _norm(alias)]
    for line in word_lines(words):
        used = set()
        candidates = []
        for index in range(len(line)):
            for end in range(index + 1, min(len(line), index + 7) + 1):
                text = _norm(" ".join(w.content for w in line[index:end]))
                for key, alias in aliases:
                    if text == alias:
                        candidates.append((end - index, index, end, key, tuple(line[index:end])))
        for length, start, end, key, span in sorted(candidates, reverse=True, key=lambda item: item[0]):
            if not set(range(start, end)) & used:
                used.update(range(start, end))
                hits.append((key, span))
    return hits


def normalize_value(value, field):
    kind = field['fieldtype']
    if kind in ('Data', 'Link', 'Long Text', 'Small Text', 'Text'):
        if not isinstance(value, str):
            raise ValueError('must be text (identifiers retain leading zeros)')
        return value.strip()
    if kind == 'Date':
        if not isinstance(value, str):
            raise ValueError('must be a date')
        for pattern in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
            try:
                return datetime.strptime(value.strip(), pattern).date().isoformat()
            except ValueError:
                pass
        raise ValueError('invalid date; use YYYY-MM-DD or MM/DD/YYYY')
    if kind in ('Currency', 'Float', 'Int'):
        if isinstance(value, bool):
            raise ValueError('must be a number')
        raw = str(value).strip()
        if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', raw):
            raise ValueError('invalid number')
        amount = Decimal(raw.replace(',', ''))
        if not amount.is_finite():
            raise ValueError('number must be finite')
        if kind == 'Int':
            if amount != amount.to_integral_value():
                raise ValueError('must be a whole number')
            return int(amount)
        number = float(amount)
        if not math.isfinite(number):
            raise ValueError('number is too large')
        return number
    raise ValueError('unsupported field type')


def validate_payload(payload, schema=None):
    schema = schema or load_schema()
    fields = {f['fieldname']: f for f in schema['fields']}
    issues = []
    if payload.get('doctype') != 'RDA Information':
        issues.append(MappingIssue('doctype', 'Target must be RDA Information'))
    if not (set(payload) - {'doctype'}) & set(fields):
        issues.append(MappingIssue(None, 'No RDA values were recognized. Capture the labels and their values.'))
    for key, value in payload.items():
        if key == 'doctype':
            continue
        if key not in fields:
            issues.append(MappingIssue(key, 'Unknown RDA field', str(value)))
            continue
        try:
            normalized = normalize_value(value, fields[key])
            if normalized == '':
                raise ValueError('blank values should be explicitly omitted')
        except (ValueError, InvalidOperation) as error:
            issues.append(MappingIssue(key, str(error), str(value)))
    for field in fields.values():
        if field.get('reqd') and field['fieldname'] not in payload and not field.get('default'):
            issues.append(MappingIssue(field['fieldname'], 'Required field is missing'))
    return issues


def map_rda_document(document: OCRDocument, schema=None, minimum_confidence=80.0) -> MappedRecord:
    schema = schema or load_schema()
    fields = {f['fieldname']: f for f in schema['fields']}
    result = MappedRecord({'doctype': 'RDA Information'})
    sections = list(dict.fromkeys(f['section'] for f in fields.values() if f['section'] != 'RDA Summary'))
    headers = _hits(document.words, [(s, [s]) for s in sections])
    field_labels = _hits(document.words, [(key, f['aliases']) for key, f in fields.items() if f['section'] != 'RDA Summary'])
    label_words = {w for _, span in field_labels if any(':' in w.content for w in span) for w in span}
    headers = [(name, span) for name, span in headers if not set(span) & label_words]
    accounted = {w for _, span in headers for w in span}
    rects = []
    for name, span in headers:
        x, y, right, bottom = _box(span)
        padding = (bottom - y) * 0.6
        next_x = [min(w.bbox[0] for w in words) - padding for other, words in headers
                  if other != name and abs(min(w.bbox[1] for w in words) - y) < padding and min(w.bbox[0] for w in words) > x]
        if name in ('Shipper Information', 'Recipient Information', 'Bill To Information'):
            # Repeated panel boundaries remain valid when one heading is unreadable.
            next_x.extend(_box(words)[0] - padding for _, words in headers if _box(words)[0] > x + padding)
        left = max(0, x - padding)
        end_x = min(next_x, default=document.width)
        next_y = [min(w.bbox[1] for w in words) for _, words in headers
                  if min(w.bbox[1] for w in words) > bottom and left <= min(w.bbox[0] for w in words) < end_x]
        rects.append((name, left, bottom, end_x, min(next_y, default=document.height)))

    def assign(key, words):
        if not words:
            return
        raw = ' '.join(w.content for w in words).strip()
        field = fields[key]
        currency = None
        if field['fieldtype'] == 'Currency':
            match = re.fullmatch(r'(.+?)\s+([A-Z]{3})', raw)
            if match:
                raw, currency = match.groups()
        try:
            value = normalize_value(raw, field)
        except (ValueError, InvalidOperation) as error:
            value = raw
            result.issues.append(MappingIssue(key, str(error), raw))
        if key in result.payload and result.payload[key] != value:
            result.issues.append(MappingIssue(key, 'Competing values; review before sending', raw))
            return
        result.payload[key] = value
        result.evidence[key] = tuple(words)
        if any(w.confidence < minimum_confidence for w in words):
            result.issues.append(MappingIssue(key, 'Low OCR confidence; verify the value', raw))
        if currency and field.get('options') in fields:
            currency_key = field['options']
            if currency_key in result.payload and result.payload[currency_key] != currency:
                result.issues.append(MappingIssue(currency_key, 'Competing currencies', currency))
            else:
                result.payload[currency_key] = currency
                result.evidence[currency_key] = tuple(words)

    for section, left, top, right, bottom in rects:
        words = [w for w in document.words if left <= w.bbox[0] < right and top < w.bbox[1] < bottom]
        labels = _hits(words, [(key, field['aliases']) for key, field in fields.items() if field['section'] == section])
        if section in ('Shipper Information', 'Recipient Information', 'Bill To Information'):
            primary = [(key, span) for key, span in labels if key.endswith(('_name', '_account_number', '_company', '_address_line_1', '_city', '_phone_number'))]
            starts = sorted({_box(span)[0] for _, span in primary})
            if len(starts) > 1 and starts[-1] - starts[0] > (right-left) * .3:
                right = min(x for x in starts if x > starts[0] + (right-left)*.3) - 1
                words = [w for w in words if w.bbox[0] < right]
                labels = [(key, span) for key, span in labels if _box(span)[0] < right]
                result.issues.append(MappingIssue(None, 'An adjacent party panel has no readable heading; recapture or review omitted values.'))
        for key, span in labels:
            x1, y1, x2, y2 = _box(span)
            accounted.update(span)
            same_row = [(other, label) for other, label in labels if abs(_box(label)[1] - y1) < (y2-y1)*.6]
            end = min((_box(label)[0] for _, label in same_row if _box(label)[0] > x2), default=right)
            values = sorted((w for w in words if x2 < w.bbox[0] < end and abs((w.bbox[1]+w.bbox[3])/2-(y1+y2)/2) < (y2-y1)*.65), key=lambda w: w.bbox[0])
            for index in range(1, len(values)):
                if values[index].bbox[0] - values[index-1].bbox[2] > max(10, (y2-y1)*5):
                    values = values[:index]
                    break
            assign(key, values)
            accounted.update(values)

    # Labels outside known sections must never silently inherit a neighboring panel.
    body_words = [w for w in document.words if w.bbox[1] >= min((_box(s)[1] for _, s in headers), default=0)]
    all_labels = _hits(body_words, [(key, f['aliases']) for key, f in fields.items() if f['section'] != 'RDA Summary'])
    if any(any(':' in w.content for w in span) and not set(span).issubset(accounted) for _, span in all_labels):
        result.issues.append(MappingIssue(None, 'Some field labels have no readable section heading; recapture or review omitted values.'))

    # Summary values are below their column headings, above the first body section.
    first_body = min((_box(span)[1] for _, span in headers), default=0)
    summary_words = [w for w in document.words if w.bbox[3] < first_body]
    if document.tables:
        summary_fields = {key: field for key, field in fields.items() if field['section'] == 'RDA Summary'}
        for table in document.tables:
            for cell in table.cells:
                if not cell.values:
                    continue
                header = ' '.join(w.content for w in cell.header)
                header_norm = _norm(header).removesuffix('number')
                candidates = []
                for key, field in summary_fields.items():
                    aliases = [_norm(alias).removesuffix('number') for alias in field['aliases']]
                    score = max((1. if header_norm == alias else SequenceMatcher(None, header_norm, alias).ratio()
                                 if min(len(header_norm),len(alias)) >= 5 else 0.) for alias in aliases)
                    candidates.append((score, key))
                candidates.sort(reverse=True)
                if candidates[0][0] < .82 or candidates[0][0] - candidates[1][0] < .08:
                    result.issues.append(MappingIssue(None, 'A populated summary cell has an unreadable heading; review or recapture.', header))
                    continue
                key = candidates[0][1]
                values = cell.values
                # OCR may insert spaces within one numeric identifier's line.
                identifiers = ('lob', 'co', 'summary_bill_to_account_number', 'summary_invoice_number', 'revenue_item_id')
                if key in identifiers and len(values) > 1 and all(w.content.isdecimal() for w in values):
                    values = (OCRWord(''.join(w.content for w in values), _box(values), min(w.confidence for w in values)),)
                assign(key, values)
    elif summary_words:
        summary_fields = [(key, field['aliases']) for key, field in fields.items() if field['section'] == 'RDA Summary']
        summary_hits = _hits(summary_words, summary_fields)
        # Only the top header band may define column labels.
        if summary_hits:
            first_y = min(_box(span)[1] for _, span in summary_hits)
            height = min(_box(span)[3]-_box(span)[1] for _, span in summary_hits)
            header_hits = [(key, span) for key, span in summary_hits if _box(span)[1] < first_y + height*2.8]
            header_hits.sort(key=lambda item: _box(item[1])[0])
            order = [key for key, _ in summary_fields]
            positions = [order.index(key) for key, _ in header_hits]
            if any(b-a != 1 for a, b in zip(positions, positions[1:])):
                result.issues.append(MappingIssue(None, 'Some summary column headings are unreadable; review the mapped values or recapture.'))
            header_end = max((_box(span)[3] for _, span in header_hits), default=first_body)
            for index, (key, span) in enumerate(header_hits):
                if index == len(header_hits)-1 and key != order[-1]:
                    result.issues.append(MappingIssue(None, 'The final summary heading is unreadable; the last unbounded column was omitted.'))
                    continue
                left = _box(span)[0] - height * .4
                right = _box(header_hits[index+1][1])[0] - height*.4 if index+1 < len(header_hits) else document.width
                values = sorted((w for w in summary_words if left <= w.bbox[0] < right and w.bbox[1] > header_end + height*.25), key=lambda w: (w.bbox[1], w.bbox[0]))
                assign(key, values)
    result.issues.extend(validate_payload(result.payload, schema))
    return result
