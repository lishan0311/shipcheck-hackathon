"""Explicit one-time import of old SQLite reports into Supabase. Never deletes source."""
import argparse
import json
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ingestion import load_email
from backend.repository import SupabaseRepository
from backend.schemas import Report
from backend.settings import Settings


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path,default=Path('runtime/shipcheck.sqlite3'))
    parser.add_argument('--apply',action='store_true',help='Actually import; default only reports the row count')
    args=parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        rows=db.execute('SELECT email_id,result_json FROM runs ORDER BY id').fetchall()
    print(f'{len(rows)} legacy reports found. Source database remains unchanged.')
    if not args.apply:
        print('Use --apply once after configuring Supabase. Re-running imports duplicate reports.')
        return
    settings=Settings.from_env()
    if not settings.supabase_url or not settings.supabase_key:
        parser.error('Supabase must be configured before import.')
    repo=SupabaseRepository(settings.supabase_url,settings.supabase_key,settings.bucket)
    try:
        for email_id,payload in rows:
            repo.sync_email(load_email(settings.dataset,email_id,read_attachments=False)['email'],settings.dataset)
            repo.save(email_id,Report.model_validate(json.loads(payload)).model_dump())
    finally:
        repo.close()
    print('Import complete. Original reports remain in the source database.')

if __name__=='__main__':
    main()
