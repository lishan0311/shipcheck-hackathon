"""Create a Gmail OAuth refresh token locally for ShipCheck.

Configure GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in the root .env first, then
run this script on the computer where a browser is available. The refresh token
is printed only to this terminal and can optionally be written to .env.
"""

import argparse
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / '.env'
REDIRECT_URI = 'http://127.0.0.1:8765/callback'
SCOPE = 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send'


def update_env(name: str, value: str):
    lines = ENV_FILE.read_text(encoding='utf-8').splitlines() if ENV_FILE.exists() else []
    replacement = f'{name}={value}'
    updated, found = [], False
    for line in lines:
        if line.startswith(name + '='):
            updated.append(replacement)
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(replacement)
    ENV_FILE.write_text('\n'.join(updated) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Authorize ShipCheck to read Gmail and send reviewed follow-ups.')
    parser.add_argument('--write-env', action='store_true', help='Save the refresh token to the root .env file.')
    args = parser.parse_args()
    values = dotenv_values(ENV_FILE)
    client_id = str(values.get('GMAIL_CLIENT_ID') or '').strip()
    client_secret = str(values.get('GMAIL_CLIENT_SECRET') or '').strip()
    if not client_id or not client_secret:
        raise SystemExit('Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env first.')

    state = secrets.token_urlsafe(32)
    result: dict[str, str] = {}
    ready = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            if query.get('state', [''])[0] != state:
                self.send_response(400)
                message = 'Authorization state did not match. Close this tab and try again.'
                result['error'] = 'state_mismatch'
                ready.set()
            elif query.get('error'):
                self.send_response(400)
                message = 'Gmail authorization was not granted. Close this tab and try again.'
                result['error'] = query['error'][0]
                ready.set()
            elif query.get('code'):
                self.send_response(200)
                message = 'Gmail authorization succeeded. You can close this tab and return to the terminal.'
                result['code'] = query['code'][0]
                ready.set()
            else:
                self.send_response(400)
                message = 'Missing authorization code. Close this tab and try again.'
            encoded = message.encode('utf-8')
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_):
            return

    params = {
        'client_id': client_id,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPE,
        'access_type': 'offline',
        'prompt': 'select_account consent',
        'state': state,
    }
    authorization_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
    server = HTTPServer(('127.0.0.1', 8765), CallbackHandler)
    server.timeout = 5
    print('Opening Google authorization in your browser...')
    print('If it does not open, visit this URL:\n' + authorization_url)
    webbrowser.open(authorization_url)
    deadline = time.monotonic() + 300
    while not ready.is_set() and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if not ready.is_set():
        raise SystemExit('Authorization timed out after five minutes. Run the command again.')
    if 'code' not in result:
        raise SystemExit('Authorization failed: ' + result.get('error', 'unknown error'))

    response = httpx.post('https://oauth2.googleapis.com/token', data={
        'code': result['code'],
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code',
    }, timeout=60)
    response.raise_for_status()
    token = str(response.json().get('refresh_token') or '')
    if not token:
        raise SystemExit('Google did not return a refresh token. Revoke the app grant and run again with consent.')
    if args.write_env:
        update_env('GMAIL_REFRESH_TOKEN', token)
        print('Saved GMAIL_REFRESH_TOKEN to .env. Restart ShipCheck to connect Gmail.')
    else:
        print('\nGMAIL_REFRESH_TOKEN=' + token)
        print('\nCopy this line into the root .env, keep it private, and restart ShipCheck.')


if __name__ == '__main__':
    main()
