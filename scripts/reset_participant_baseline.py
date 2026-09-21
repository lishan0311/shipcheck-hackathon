"""Restore or clear reports for the supplied 520-email dataset.

The original emails and attachments stay in Supabase. Human decisions, case
responses, reprocessing history and processing jobs are removed. Use --apply
only after reviewing the printed counts.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.repository import SupabaseRepository
from backend.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description='Restore or clear the participant inbox reports.')
    parser.add_argument('--apply', action='store_true', help='Apply the selected deletion after the dry-run review.')
    parser.add_argument('--fresh', action='store_true', help='Remove every saved report so the current pipeline can process all 520 emails again.')
    args = parser.parse_args()
    settings = Settings.from_env()
    expected = len(list((settings.dataset / 'inbox').glob('email_*.json')))
    if expected != 520:
        raise SystemExit('Safety check failed: expected exactly 520 participant files. Nothing was changed.')
    if not (settings.supabase_url and settings.supabase_key):
        raise SystemExit('Supabase is not configured. Nothing was changed.')

    repo = SupabaseRepository(settings.supabase_url, settings.supabase_key, settings.bucket)
    try:
        reports = repo.request('GET', '/rest/v1/reports', params={
            'select': 'run_id,email_id,sequence,result', 'email_id': 'like.email_*',
            'order': 'email_id.asc,sequence.asc',
        })
        reviews = repo.request('GET', '/rest/v1/reviews', params={
            'select': 'review_id', 'email_id': 'like.email_*',
        })
        jobs = repo.request('GET', '/rest/v1/processing_jobs', params={
            'select': 'job_id', 'email_id': 'like.email_*',
        })
        grouped: dict[str, list[dict]] = defaultdict(list)
        for report in reports:
            grouped[report['email_id']].append(report)
        if not args.fresh and (len(grouped) != 520 or any(not values for values in grouped.values())):
            raise SystemExit('Safety check failed: every participant email must have a report. Nothing was changed.')
        if args.fresh:
            kept: list[dict] = []
            remove = reports
        else:
            kept = [values[0] for values in grouped.values()]
            invalid = [report['email_id'] for report in kept if (report.get('result') or {}).get('routing_source') in {'human_review', 'case_response'}]
            if invalid:
                raise SystemExit('Safety check failed: an earliest report is not automated. Nothing was changed.')
            remove = [report for values in grouped.values() for report in values[1:]]
        print(f'Protected participant emails: {expected}')
        print(f"{'Reports kept' if args.fresh else 'Automated baseline reports kept'}: {len(kept)}")
        print(f"{'All saved reports' if args.fresh else 'Later report versions'} selected for deletion: {len(remove)}")
        print(f'Human review audit records selected for deletion: {len(reviews)}')
        print(f'Processing jobs selected for deletion: {len(jobs)}')
        if not args.apply:
            print('Dry run only. Re-run with --apply to make these changes.')
            return

        repo.request('DELETE', '/rest/v1/reviews', params={'email_id': 'like.email_*'}, headers={'Prefer': 'return=minimal'})
        for report in remove:
            repo.request('DELETE', '/rest/v1/reports', params={'run_id': f"eq.{report['run_id']}"}, headers={'Prefer': 'return=minimal'})
        repo.request('DELETE', '/rest/v1/processing_jobs', params={'email_id': 'like.email_*'}, headers={'Prefer': 'return=minimal'})
        print('Saved reports cleared.' if args.fresh else 'Baseline restored.')
        print('Original emails and attachments were not changed.')
    finally:
        repo.close()


if __name__ == '__main__':
    main()
