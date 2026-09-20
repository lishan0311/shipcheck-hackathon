"""Gmail API reader for a real Gmail or Google Workspace inbox."""

import base64
import hashlib
import html
import re
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import quote

import httpx


SUPPORTED_ATTACHMENTS = {'.txt', '.pdf', '.docx', '.xlsx'}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def plain_body(body: dict | None) -> str:
    """Convert a small HTML/text body object into readable plain text."""
    if not body:
        return ''
    content = str(body.get('content') or '')
    if str(body.get('contentType') or '').casefold() != 'html':
        return content.strip()
    content = re.sub(r'(?is)<(?:script|style).*?>.*?</(?:script|style)>', ' ', content)
    content = re.sub(r'(?i)<br\s*/?>|</p\s*>|</div\s*>|</li\s*>', '\n', content)
    content = re.sub(r'(?s)<[^>]+>', ' ', content)
    return '\n'.join(line.strip() for line in html.unescape(content).splitlines() if line.strip())


def decode_base64url(value: str) -> bytes:
    """Decode Gmail's URL-safe, usually unpadded base64 values."""
    value = value or ''
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def decode_header_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError):
        return value


class GmailMailbox:
    provider = 'gmail'

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 user_id: str = 'me', limit: int = 25, transport=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.user_id = user_id or 'me'
        self.mailbox = self.user_id
        self.limit = max(1, min(limit, 100))
        self.client = httpx.Client(timeout=60, transport=transport)
        self._token = ''
        self._token_expires = 0.0
        self._messages: dict[str, dict] = {}

    def close(self):
        self.client.close()

    def token(self) -> str:
        if self._token and time.monotonic() < self._token_expires - 60:
            return self._token
        response = self.client.post(
            'https://oauth2.googleapis.com/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token,
                'grant_type': 'refresh_token',
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload['access_token']
        self._token_expires = time.monotonic() + int(payload.get('expires_in', 3600))
        return self._token

    def request(self, path: str, **kwargs):
        headers = {'Authorization': f'Bearer {self.token()}', 'Accept': 'application/json'}
        headers.update(kwargs.pop('headers', {}))
        response = self.client.get(f'https://gmail.googleapis.com/gmail/v1{path}', headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    def send(self, recipient: str, subject: str, body: str, thread_id: str | None = None) -> dict:
        """Send one plain-text follow-up through the authenticated Gmail account."""
        message = EmailMessage()
        message['To'] = recipient
        message['Subject'] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii').rstrip('=')
        payload = {'raw': raw}
        if thread_id:
            payload['threadId'] = thread_id
        user = quote(self.user_id, safe='')
        headers = {'Authorization': f'Bearer {self.token()}', 'Accept': 'application/json'}
        response = self.client.post(
            f'https://gmail.googleapis.com/gmail/v1/users/{user}/messages/send',
            headers=headers, json=payload,
        )
        response.raise_for_status()
        result = response.json()
        return {
            'gmail_id': str(result.get('id') or ''),
            'gmail_thread_id': str(result.get('threadId') or thread_id or ''),
            'sent_at': datetime.now(timezone.utc).isoformat(),
        }

    def attachment_bytes(self, message_id: str, part: dict) -> bytes | None:
        filename = Path(str(part.get('filename') or '')).name
        if not filename or Path(filename).suffix.casefold() not in SUPPORTED_ATTACHMENTS:
            return None
        body = part.get('body') or {}
        size = int(body.get('size') or 0)
        if size > MAX_ATTACHMENT_BYTES:
            return None
        encoded = body.get('data')
        if not encoded and body.get('attachmentId'):
            user = quote(self.user_id, safe='')
            message = quote(message_id, safe='')
            attachment = quote(str(body['attachmentId']), safe='')
            payload = self.request(f'/users/{user}/messages/{message}/attachments/{attachment}')
            encoded = payload.get('data')
        if not encoded:
            return None
        try:
            content = decode_base64url(str(encoded))
        except (ValueError, TypeError):
            return None
        return content if 0 < len(content) <= MAX_ATTACHMENT_BYTES else None

    def parse_payload(self, message_id: str, payload: dict) -> tuple[str, list[tuple[str, bytes]]]:
        text_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[tuple[str, bytes]] = []

        def visit(part: dict):
            filename = Path(str(part.get('filename') or '')).name
            mime_type = str(part.get('mimeType') or '').casefold()
            if filename:
                content = self.attachment_bytes(message_id, part)
                if content is not None:
                    attachments.append((filename, content))
            elif mime_type in {'text/plain', 'text/html'}:
                encoded = (part.get('body') or {}).get('data')
                if encoded:
                    try:
                        value = decode_base64url(str(encoded)).decode('utf-8', errors='replace')
                        (html_parts if mime_type == 'text/html' else text_parts).append(value)
                    except (ValueError, TypeError):
                        pass
            for child in part.get('parts') or []:
                visit(child)

        visit(payload)
        if text_parts:
            body = '\n\n'.join(value.strip() for value in text_parts if value.strip())
        else:
            body = plain_body({'contentType': 'html', 'content': '\n'.join(html_parts)})
        return body or '(Empty message)', attachments

    def fetch_label(self, label: str) -> list[dict]:
        user = quote(self.user_id, safe='')
        listed = self.request(
            f'/users/{user}/messages',
            params={'maxResults': str(self.limit), 'labelIds': label},
        )
        messages = []
        for summary in listed.get('messages', []):
            gmail_id = str(summary.get('id') or '')
            if not gmail_id:
                continue
            if gmail_id in self._messages:
                messages.append(self._messages[gmail_id])
                continue
            item = self.request(
                f'/users/{user}/messages/{quote(gmail_id, safe="")}',
                params={'format': 'full'},
            )
            payload = item.get('payload') or {}
            headers = {
                str(header.get('name') or '').casefold(): decode_header_value(str(header.get('value') or ''))
                for header in payload.get('headers') or []
            }
            body, attachments = self.parse_payload(gmail_id, payload)
            _, sender = parseaddr(headers.get('from', ''))
            stable = headers.get('message-id') or gmail_id
            internal_date = str(item.get('internalDate') or '')
            try:
                message_time = datetime.fromtimestamp(int(internal_date) / 1000, timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                message_time = None
            message = {
                'email_id': 'mail_' + hashlib.sha256(stable.encode('utf-8')).hexdigest()[:16],
                'from': sender or headers.get('from') or 'unknown@gmail',
                'to': headers.get('to') or '',
                'subject': headers.get('subject') or '(No subject)',
                'body': body,
                'received_at': message_time,
                'sent_at': message_time,
                'attachments': attachments,
                'gmail_id': gmail_id,
                'gmail_thread_id': str(item.get('threadId') or ''),
                'rfc_message_id': headers.get('message-id') or '',
                'in_reply_to': headers.get('in-reply-to') or '',
                'references': headers.get('references') or '',
                'label_ids': item.get('labelIds') or [label],
            }
            self._messages[gmail_id] = message
            messages.append(message)
        return messages

    def fetch(self) -> list[dict]:
        return self.fetch_label('INBOX')

    def fetch_sent(self) -> list[dict]:
        return self.fetch_label('SENT')
