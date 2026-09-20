import base64
import json
import time
from unittest.mock import Mock
import httpx
from fastapi.testclient import TestClient

from backend.mailbox import GmailMailbox, plain_body
from backend.repository import MemoryRepository
from backend.server import create_app
from backend.settings import Settings


def test_html_mail_body_becomes_readable_text():
    body = {'contentType': 'html', 'content': '<p>Hello &amp; welcome</p><div>Second line</div>'}
    assert plain_body(body) == 'Hello & welcome\nSecond line'


def test_gmail_mailbox_reads_real_message_and_supported_attachment():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            assert request.method == 'POST'
            return httpx.Response(200, json={'access_token': 'test-token', 'expires_in': 3600})
        assert request.headers['Authorization'] == 'Bearer test-token'
        if request.url.path.endswith('/users/ops@example.com/messages'):
            assert request.url.params['labelIds'] == 'INBOX'
            return httpx.Response(200, json={'messages': [{'id': 'gmail-message-1'}]})
        if request.url.path.endswith('/messages/gmail-message-1'):
            return httpx.Response(200, json={
                'id': 'gmail-message-1', 'internalDate': '1789905600000',
                'payload': {
                    'mimeType': 'multipart/mixed',
                    'headers': [
                        {'name': 'Message-ID', 'value': '<stable@example.com>'},
                        {'name': 'From', 'value': 'Sender Name <sender@example.com>'},
                        {'name': 'Subject', 'value': 'Check SI and BL'},
                    ],
                    'parts': [
                        {'mimeType': 'text/plain', 'body': {
                            'data': base64.urlsafe_b64encode(b'Please compare.').decode().rstrip('='),
                        }},
                        {'mimeType': 'text/plain', 'filename': 'SI.txt',
                         'body': {'attachmentId': 'attachment-1', 'size': 20}},
                        {'mimeType': 'image/png', 'filename': 'logo.png',
                         'body': {'attachmentId': 'inline-1', 'size': 4}},
                    ],
                },
            })
        if request.url.path.endswith('/attachments/attachment-1'):
            return httpx.Response(200, json={
                'data': base64.urlsafe_b64encode(b'SHIPPING INSTRUCTION').decode().rstrip('='),
                'size': 20,
            })
        return httpx.Response(404)

    mailbox = GmailMailbox(
        'client', 'secret', 'refresh-token', 'ops@example.com',
        transport=httpx.MockTransport(handler),
    )
    try:
        first = mailbox.fetch()
        second = mailbox.fetch()
    finally:
        mailbox.close()

    assert first == second
    assert len(first) == 1
    assert first[0]['email_id'].startswith('mail_')
    assert first[0]['from'] == 'sender@example.com'
    assert first[0]['attachments'] == [('SI.txt', b'SHIPPING INSTRUCTION')]
    # The cached access token is reused for the second synchronization.
    assert sum(request.url.host == 'oauth2.googleapis.com' for request in seen) == 1
    # Gmail messages are immutable, so polling fetches details and attachments once.
    assert sum(request.url.path.endswith('/messages/gmail-message-1') for request in seen) == 1
    assert sum(request.url.path.endswith('/attachments/attachment-1') for request in seen) == 1


def test_gmail_mailbox_sends_reviewed_follow_up():
    def handler(request: httpx.Request):
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'send-token', 'expires_in': 3600})
        assert request.method == 'POST'
        assert request.url.path.endswith('/users/ops@example.com/messages/send')
        payload = json.loads(request.content)
        decoded = base64.urlsafe_b64decode(payload['raw'] + '=' * (-len(payload['raw']) % 4)).decode()
        assert 'To: sender@example.com' in decoded
        assert 'Subject: [SC-demo] Re: Check draft BL' in decoded
        assert 'Please revise the container count.' in decoded
        return httpx.Response(200, json={'id': 'sent-1', 'threadId': 'thread-1'})

    mailbox = GmailMailbox(
        'client', 'secret', 'refresh-token', 'ops@example.com',
        transport=httpx.MockTransport(handler),
    )
    try:
        sent = mailbox.send(
            'sender@example.com', '[SC-demo] Re: Check draft BL',
            'Please revise the container count.',
        )
    finally:
        mailbox.close()
    assert sent['gmail_id'] == 'sent-1'
    assert sent['gmail_thread_id'] == 'thread-1'


def test_server_imports_real_mailbox_message_and_processes_it(tmp_path):
    (tmp_path / 'inbox').mkdir()
    (tmp_path / 'inbox/existing.json').write_text(json.dumps({
        'email_id': 'existing', 'from': 'old@example.com', 'subject': 'Old',
        'body': 'Old message', 'attachments': [],
    }), encoding='utf-8')

    class FakeMailbox:
        mailbox = 'ops@example.com'
        def fetch(self):
            return [{'email_id': 'mail_real_1', 'from': 'sender@example.com',
                     'subject': 'New operations update', 'body': 'Vessel arrived.',
                     'attachments': [], 'received_at': '2026-09-20T12:00:00Z'}]
        def close(self):
            pass

    classifier = Mock()
    classifier.predict.return_value = {
        'predicted_category': 'GENERAL', 'needs_review': False,
        'confidence': 0.9, 'review_details': [],
    }
    settings = Settings(dataset=tmp_path, incoming_dir=tmp_path / 'live', demo=True,
                        mail_provider='gmail', gmail_user_id='ops@example.com')
    repo = MemoryRepository()
    with TestClient(create_app(settings, repo, classifier, FakeMailbox())) as client:
        deadline = time.monotonic() + 3
        while not repo.history('mail_real_1') and time.monotonic() < deadline:
            time.sleep(0.01)
        inbox = client.get('/api/emails').json()['emails']
        status = client.get('/api/mailbox/status').json()
    assert inbox[0]['email_id'] == 'mail_real_1'
    assert repo.history('mail_real_1')[0]['result']['category'] == 'GENERAL'
    assert status['connected'] is True


def test_case_response_uses_latest_bl_and_keeps_reply_attachments(tmp_path):
    (tmp_path / 'inbox').mkdir()
    (tmp_path / 'attachments').mkdir()
    si = 'SHIPPING INSTRUCTION\nShipper: A\nConsignee: B\nNotify: C\nPOL: D\nPOD: E\nContainer Count: 3\nGross Weight (KG): 22000'
    old_bl = si.replace('SHIPPING INSTRUCTION', 'BILL OF LADING (DRAFT)').replace('Container Count: 3', 'Container Count: 4')
    new_bl = si.replace('SHIPPING INSTRUCTION', 'BILL OF LADING (DRAFT)')
    (tmp_path / 'attachments/si.txt').write_text(si, encoding='utf-8')
    (tmp_path / 'attachments/bl.txt').write_text(old_bl, encoding='utf-8')
    (tmp_path / 'inbox/demo.json').write_text(json.dumps({
        'email_id': 'demo', 'from': 'sender@example.com', 'subject': 'Check draft BL',
        'body': 'Please compare.', 'attachments': ['attachments/si.txt', 'attachments/bl.txt'],
    }), encoding='utf-8')

    class CaseMailbox:
        mailbox = 'ops@example.com'
        inbox = []
        sent = []
        outbox = []
        def fetch(self): return list(self.inbox)
        def fetch_sent(self): return list(self.sent)
        def send(self, recipient, subject, body, thread_id=None):
            self.outbox.append({'recipient': recipient, 'subject': subject, 'body': body})
            return {
                'gmail_id': 'sent_1', 'gmail_thread_id': 'thread_1',
                'sent_at': '2026-09-20T12:00:00+00:00',
            }
        def close(self): pass

    mailbox = CaseMailbox()
    classifier = Mock()
    classifier.predict.return_value = {
        'predicted_category': 'BL_COMPARISON', 'needs_review': False,
        'confidence': 0.95, 'review_details': [],
    }
    settings = Settings(dataset=tmp_path, incoming_dir=tmp_path / 'live', demo=True,
                        mail_provider='gmail', gmail_user_id='ops@example.com')
    with TestClient(create_app(settings, MemoryRepository(), classifier, mailbox)) as client:
        base = client.post('/api/emails/demo/process').json()
        reviewed = client.post('/api/emails/demo/review', json={
            'base_run_id': base['run_id'], 'reviewer': 'Operator',
            'reason': 'Container count discrepancy confirmed', 'category': 'BL_COMPARISON',
            'decision': 'CONFIRM_DISCREPANCY', 'corrections': [],
        })
        assert reviewed.status_code == 200, reviewed.text
        batch = client.post('/api/cases/follow-ups', json={'email_ids': ['demo']})
        assert batch.status_code == 200, batch.text
        assert batch.json()['sent'] == 1
        assert mailbox.outbox[0]['recipient'] == 'sender@example.com'
        assert mailbox.outbox[0]['subject'].startswith('[SC-demo]')
        mailbox.inbox = [{
            'email_id': 'mail_reply_1', 'from': 'sender@example.com',
            'subject': 'Re: Check draft BL', 'body': 'Please find the revised BL.',
            'attachments': [('revised_bl.txt', new_bl.encode())],
            'gmail_id': 'reply_1', 'gmail_thread_id': 'different_thread',
            'received_at': '2026-09-20T13:00:00+00:00',
        }]
        client.post('/api/mailbox/sync').raise_for_status()
        detail = client.get('/api/emails/demo').json()
        inbox = client.get('/api/emails').json()['emails']

    latest = detail['history'][0]['result']
    assert latest['routing_status'] == 'COMPLETED'
    assert latest['comparison_status'] == 'OK'
    assert latest['case_tracking']['status'] == 'COMPLETED'
    assert latest['case_tracking']['history'][-1]['event'] == 'AUTO_COMPLETED'
    assert 'mail_reply_1/' in latest['fields']['container_count']['bl']['source']['attachment_path']
    assert detail['case_messages'][0]['documents'][0]['path'].endswith('revised_bl.txt')
    assert all(item['email_id'] != 'mail_reply_1' for item in inbox)
