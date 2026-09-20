"""Report Gmail-imported records without changing local or Supabase data."""

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.settings import Settings


def main():
    settings = Settings.from_env()
    local_inbox = settings.incoming_dir / 'inbox'
    local_attachments = settings.incoming_dir / 'attachments'
    local_records = list(local_inbox.glob('mail_*.json')) if local_inbox.exists() else []
    local_files = list(local_attachments.glob('mail_*')) if local_attachments.exists() else []
    dataset_records = list((settings.dataset / 'inbox').glob('email_*.json'))
    print(f'Dataset records: {len(dataset_records)}')
    print(f'Local Gmail records: {len(local_records)}')
    print(f'Local Gmail attachments: {len(local_files)}')
    if not (settings.supabase_url and settings.supabase_key):
        print('Supabase: not configured')
        return
    headers = {'apikey': settings.supabase_key, 'Authorization': f'Bearer {settings.supabase_key}'}
    with httpx.Client(base_url=settings.supabase_url, headers=headers, timeout=30) as client:
        print('Supabase Gmail-related rows:')
        for table in ('emails', 'attachments', 'processing_jobs', 'reports', 'reviews'):
            response = client.get(f'/rest/v1/{table}', params={
                'select': 'email_id', 'email_id': 'like.mail_*',
            })
            response.raise_for_status()
            print(f'  {table}: {len(response.json())}')


if __name__ == '__main__':
    main()
