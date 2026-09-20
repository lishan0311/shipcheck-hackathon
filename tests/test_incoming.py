import base64
import json
from unittest.mock import Mock

from fastapi.testclient import TestClient

from backend.repository import MemoryRepository
from backend.server import create_app
from backend.settings import Settings


def test_incoming_email_is_first_auto_processed_and_downloadable(tmp_path):
    (tmp_path / 'dataset' / 'inbox').mkdir(parents=True)
    original = {'email_id': 'demo', 'from': 'old@example.com', 'subject': 'Old email', 'body': 'General update', 'attachments': []}
    (tmp_path / 'dataset' / 'inbox' / 'demo.json').write_text(json.dumps(original), encoding='utf-8')
    classifier = Mock()
    classifier.predict.return_value = {'predicted_category':'GENERAL','needs_review':False,'confidence':0.8,'review_details':[]}
    app = create_app(
        Settings(dataset=tmp_path/'dataset', incoming_dir=tmp_path/'live', demo=True),
        MemoryRepository(), classifier,
    )
    content = b'SHIPPING INSTRUCTION\nShipper: ACME'
    with TestClient(app) as client:
        response = client.post('/api/incoming-email', json={
            'from': 'sender@example.com', 'subject': 'A newly received email', 'body': 'Operational update.',
            'attachments': [{'filename':'sample.txt','content_base64':base64.b64encode(content).decode()}],
        })
        assert response.status_code == 200, response.text
        email_id = response.json()['email_id']
        assert response.json()['result']['category'] == 'GENERAL'
        assert client.get('/api/emails').json()['emails'][0]['email_id'] == email_id
        download = client.get(f'/api/emails/{email_id}/attachments/0')
        assert download.status_code == 200
        assert download.content == content
