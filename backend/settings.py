import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


@dataclass
class Settings:
    dataset: Path = ROOT / 'sdoc-hackathon-bundle'
    incoming_dir: Path = ROOT / 'runtime' / 'live-mailbox'
    supabase_url: str = ''
    supabase_key: str = ''
    bucket: str = 'shipping-documents'
    demo: bool = False
    frontend_origin: str = ''
    access_token: str = ''
    auto_process: bool = False
    mail_provider: str = ''
    gmail_client_id: str = ''
    gmail_client_secret: str = ''
    gmail_refresh_token: str = ''
    gmail_user_id: str = 'me'
    mail_poll_seconds: int = 15
    mail_sync_limit: int = 25
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-2.5-flash-lite'
    gemini_timeout_seconds: int = 8
    gemini_max_requests: int = 20
    gemini_min_confidence: float = 0.90

    @classmethod
    def from_env(cls):
        return cls(
            dataset=Path(os.getenv('DATASET_PATH', str(ROOT / 'sdoc-hackathon-bundle'))),
            incoming_dir=Path(os.getenv('INCOMING_EMAIL_DIR', str(ROOT / 'runtime' / 'live-mailbox'))),
            supabase_url=os.getenv('SUPABASE_URL', '').rstrip('/'),
            supabase_key=os.getenv('SUPABASE_SERVICE_ROLE_KEY', ''),
            bucket=os.getenv('SUPABASE_BUCKET', 'shipping-documents'),
            demo=os.getenv('ALLOW_DEMO_MODE', 'false').lower() == 'true',
            frontend_origin=os.getenv('FRONTEND_ORIGIN', ''),
            access_token=os.getenv('APP_ACCESS_TOKEN', ''),
            auto_process=os.getenv('AUTO_PROCESS_INBOX', 'false').lower() == 'true',
            mail_provider=os.getenv('MAIL_PROVIDER', '').strip().lower(),
            gmail_client_id=os.getenv('GMAIL_CLIENT_ID', '').strip(),
            gmail_client_secret=os.getenv('GMAIL_CLIENT_SECRET', '').strip(),
            gmail_refresh_token=os.getenv('GMAIL_REFRESH_TOKEN', '').strip(),
            gmail_user_id=os.getenv('GMAIL_USER_ID', 'me').strip() or 'me',
            mail_poll_seconds=max(10, int(os.getenv('MAIL_POLL_SECONDS', '15'))),
            mail_sync_limit=max(1, min(100, int(os.getenv('MAIL_SYNC_LIMIT', '25')))),
            gemini_api_key=os.getenv('GEMINI_API_KEY', '').strip(),
            gemini_model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite').strip() or 'gemini-2.5-flash-lite',
            gemini_timeout_seconds=max(3, min(30, int(os.getenv('GEMINI_TIMEOUT_SECONDS', '8')))),
            gemini_max_requests=max(0, min(500, int(os.getenv('GEMINI_MAX_REQUESTS', '20')))),
            gemini_min_confidence=max(0.5, min(1, float(os.getenv('GEMINI_MIN_CONFIDENCE', '0.90')))),
        )
