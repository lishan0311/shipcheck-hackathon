"""Verify deployment configuration without printing secrets or changing data.

Run locally before deploying, or from a Render shell after deploying:
    .venv\\Scripts\\python.exe scripts\\deployment_preflight.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.mailbox import GmailMailbox
from backend.repository import SupabaseRepository
from backend.settings import Settings


def check(label: str, action) -> bool:
    try:
        detail = action()
        print(f'PASS  {label}' + (f': {detail}' if detail else ''))
        return True
    except Exception as exc:  # A preflight tool should report every failed dependency.
        print(f'FAIL  {label}: {type(exc).__name__}: {exc}')
        return False


def main() -> int:
    settings = Settings.from_env()
    passed = []

    passed.append(check('Production mode', lambda: (
        'ALLOW_DEMO_MODE=false' if not settings.demo else (_ for _ in ()).throw(
            RuntimeError('Set ALLOW_DEMO_MODE=false before deploying.'))
    )))

    def probe_supabase() -> str:
        if not (settings.supabase_url and settings.supabase_key):
            raise RuntimeError('SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing.')
        repo = SupabaseRepository(settings.supabase_url, settings.supabase_key, settings.bucket)
        try:
            try:
                rows = repo.request(
                    'GET', '/rest/v1/latest_report_summaries',
                    params={'select': 'email_id,result', 'limit': '1'},
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise RuntimeError(
                        'The latest_report_summaries view is missing. Run '
                        'supabase/migrations/002_inbox_summary.sql and then '
                        '003_review_outcome_summary.sql in the Supabase SQL editor.'
                    ) from exc
                raise
            return f'connected; summary view available; {len(rows)} sample row returned'
        finally:
            repo.close()

    passed.append(check('Supabase database', probe_supabase))

    def probe_gmail() -> str:
        values = (settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token)
        if settings.mail_provider != 'gmail' or not all(values):
            raise RuntimeError('Gmail OAuth configuration is incomplete.')
        mailbox = GmailMailbox(*values, settings.gmail_user_id, settings.mail_sync_limit)
        try:
            profile = mailbox.request('/users/me/profile')
            return f'authorized mailbox; {profile.get("emailAddress") or settings.gmail_user_id}'
        finally:
            mailbox.close()

    passed.append(check('Gmail refresh token', probe_gmail))
    passed.append(check('Gemini fallback', lambda: (
        f'configured for {settings.gemini_model}' if settings.gemini_api_key else 'not configured (safe deterministic fallback remains active)'
    )))

    if all(passed):
        print('\nReady for deployment.')
        return 0
    print('\nDeployment preflight failed. Fix the items above before sharing the service URL.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
