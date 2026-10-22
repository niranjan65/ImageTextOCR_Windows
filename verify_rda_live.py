"""Opt-in live create test. Each invocation may create new RDA records; never imported by discovery."""
import argparse
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path

from ocr_core import extract_document
from rda_mapping import map_rda_document
from frappe_client import DEFAULT_SITE, FrappeClient, FrappeError, VerificationError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Explicitly create and verify new RDA records from a local screenshot.')
    parser.add_argument('--site', default=DEFAULT_SITE)
    parser.add_argument('--image', required=True)
    parser.add_argument('--create-count', type=int, choices=(1, 2), default=1)
    parser.add_argument('--report', default='rda_upload_live_report.json')
    parser.add_argument('--synthetic-fixture', action='store_true')
    args = parser.parse_args(argv)
    report = {'site': args.site, 'source_image': str(args.image), 'source_kind': 'synthetic_fixture' if args.synthetic_fixture else 'local_screenshot', 'records': []}
    try:
        mapping = map_rda_document(extract_document(args.image))
        report['payload'] = mapping.payload
        report['mapping_issues'] = [asdict(i) for i in mapping.issues]
        api_key = os.environ.pop('SKYLINK_API_KEY', '')
        api_secret = os.environ.pop('SKYLINK_API_SECRET', '')
        sid = os.environ.pop('SKYLINK_SESSION_ID', '')
        if api_key or api_secret:
            client = FrappeClient(args.site, api_key=api_key, api_secret=api_secret)
        elif sid:
            client = FrappeClient(args.site, sid)
        else:
            client = FrappeClient(args.site, api_key=getpass.getpass('ERPNext API key (hidden): '),
                                  api_secret=getpass.getpass('ERPNext API secret (hidden): '))
        for _ in range(args.create_count):
            saved = client.create_and_verify(mapping.payload)
            comparisons = [{'fieldname': key, 'expected': value, 'actual': saved.stored.get(key)} for key, value in saved.submitted.items() if key != 'doctype']
            report['records'].append({'name': saved.name, 'url': saved.url, 'verified_fields': len(comparisons), 'field_comparisons': comparisons})
            print(f'Saved and verified {len(comparisons)} fields: {saved.url}')
        report['status'] = 'verified'
        report['distinct_record_names'] = len({r['name'] for r in report['records']}) == len(report['records'])
        return_code = 0
    except VerificationError as error:
        report.update(status='verification_failed', record_url=error.saved.url, mismatches=error.mismatches)
        print('Record created but verification failed: ' + error.saved.url)
        return_code = 1
    except FrappeError as error:
        report.update(status=type(error).__name__, error=str(error))
        print(str(error))
        return_code = 1
    except Exception:
        report.update(status='failed', error='Could not process the image or run verification.')
        print(report['error'])
        return_code = 1
    Path(args.report).write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('Report: ' + str(args.report))
    return return_code


if __name__ == '__main__':
    raise SystemExit(main())
