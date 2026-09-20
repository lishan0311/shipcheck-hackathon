"""Remove only Gmail-imported ``mail_*`` records; preserve the 520-email bundle."""

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.settings import Settings


def main():
    parser = argparse.ArgumentParser(description='Remove Gmail-imported mail_* records only.')
    parser.add_argument('--apply', action='store_true', help='Perform the deletions. Without this flag, show counts only.')
    args = parser.parse_args()
    settings = Settings.from_env()
    dataset_count = len(list((settings.dataset / 'inbox').glob('email_*.json')))
    inbox = settings.incoming_dir / 'inbox'
    attachment_dir = settings.incoming_dir / 'attachments'
    local_records = list(inbox.glob('mail_*.json')) if inbox.exists() else []
    local_files = list(attachment_dir.glob('mail_*')) if attachment_dir.exists() else []
    print(f'Protected participant records: {dataset_count}')
    print(f'Gmail records selected for deletion: {len(local_records)}')
    print(f'Gmail attachment files selected for deletion: {len(local_files)}')
    if dataset_count != 520:
        raise SystemExit('Safety check failed: expected exactly 520 participant records. Nothing was deleted.')
    if not (settings.supabase_url and settings.supabase_key):
        raise SystemExit('Supabase is not configured. Nothing was deleted.')

    headers = {'apikey': settings.supabase_key, 'Authorization': f'Bearer {settings.supabase_key}'}
    with httpx.Client(base_url=settings.supabase_url, headers=headers, timeout=60) as client:
        attachment_response = client.get('/rest/v1/attachments', params={
            'select': 'object_path', 'email_id': 'like.mail_*',
        })
        attachment_response.raise_for_status()
        object_paths = [row['object_path'] for row in attachment_response.json()]
        counts = {}
        for table in ('emails', 'attachments', 'processing_jobs', 'reports', 'reviews'):
            response = client.get(f'/rest/v1/{table}', params={
                'select': 'email_id', 'email_id': 'like.mail_*',
            })
            response.raise_for_status()
            counts[table] = len(response.json())
        print('Supabase rows selected: ' + ', '.join(f'{key}={value}' for key, value in counts.items()))
        if not args.apply:
            print('Dry run only. Re-run with --apply to delete these mail_* records.')
            return
        if object_paths:
            response = client.request(
                'DELETE', f'/storage/v1/object/{quote(settings.bucket, safe="")}',
                json={'prefixes': object_paths},
            )
            response.raise_for_status()
        for table in ('reviews', 'reports', 'processing_jobs', 'attachments', 'emails'):
            response = client.delete(
                f'/rest/v1/{table}', params={'email_id': 'like.mail_*'},
                headers={'Prefer': 'return=minimal'},
            )
            response.raise_for_status()
    for file in local_files + local_records:
        file.unlink(missing_ok=True)
    print('Cleanup complete. The 520 participant records were not changed.')


if __name__ == '__main__':
    main()
