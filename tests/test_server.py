import json
from unittest.mock import Mock
import time
import pytest
from fastapi.testclient import TestClient
from backend.repository import MemoryRepository
from backend.server import create_app
from backend.settings import Settings


@pytest.fixture
def environment(tmp_path):
    (tmp_path / 'inbox').mkdir()
    email = {'email_id': 'demo', 'from': 'demo@example.com', 'subject': 'Compare', 'body': 'Check SI and BL', 'attachments': ['attachments/missing.txt']}
    (tmp_path / 'inbox/demo.json').write_text(json.dumps(email), encoding='utf-8')
    classifier = Mock()
    classifier.predict.return_value = {'predicted_category':'BL_COMPARISON','needs_review':False,'confidence':0.8,'review_details':[]}
    repo = MemoryRepository()
    app = create_app(Settings(dataset=tmp_path, incoming_dir=tmp_path / 'live', demo=True), repo, classifier)
    with TestClient(app) as client:
        yield client, repo, classifier, tmp_path


def test_api_process_and_history(environment):
    client, repo, _, _ = environment
    assert client.get('/api/emails').json()['emails'][0]['latest'] is None
    first = client.post('/api/emails/demo/process').json()
    assert first['result']['comparison_status'] == 'NEEDS_REVIEW'
    second = client.post('/api/emails/demo/process').json()
    assert first['run_id'] != second['run_id']
    assert len(client.get('/api/emails/demo').json()['history']) == 2
    assert client.get('/api/emails').json()['emails'][0]['latest']['run_id'] == second['run_id']
    assert list(repo.jobs.values())[-1]['status'] == 'COMPLETED'


def test_force_batch_reprocesses_existing_reports(environment):
    client, repo, _, _ = environment
    client.post('/api/emails/demo/process').raise_for_status()
    client.post('/api/batch/start?force=true').raise_for_status()
    deadline = time.monotonic() + 3
    while len(repo.history('demo')) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(repo.history('demo')) == 2


def test_selected_batch_reprocesses_only_selected_inbox_emails(environment):
    client, repo, _, _ = environment
    client.post('/api/emails/demo/process').raise_for_status()
    response = client.post('/api/batch/start', json={'force': True, 'email_ids': ['demo', 'missing', 'demo']})
    assert response.status_code == 200
    deadline = time.monotonic() + 3
    while len(repo.history('demo')) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(repo.history('demo')) == 2
    batch = client.get('/api/batch').json()
    assert batch['total'] == 1
    assert batch['skipped'] == 0


def test_archive_hides_an_email_without_deleting_its_report(environment):
    client, repo, _, _ = environment
    client.post('/api/emails/demo/process').raise_for_status()
    assert len(repo.history('demo')) == 1

    archived = client.post('/api/emails/archive', json={'email_ids': ['demo']})
    assert archived.status_code == 200
    assert archived.json()['updated'] == 1
    assert client.get('/api/emails').json()['emails'] == []
    assert [item['email_id'] for item in client.get('/api/archived').json()['emails']] == ['demo']
    assert len(repo.history('demo')) == 1

    restored = client.post('/api/emails/restore', json={'email_ids': ['demo']})
    assert restored.status_code == 200
    assert [item['email_id'] for item in client.get('/api/emails').json()['emails']] == ['demo']
    assert client.get('/api/archived').json()['emails'] == []


def test_analytics_returns_operational_aggregates(environment):
    client, _, _, _, = environment
    client.post('/api/emails/demo/process').raise_for_status()
    response = client.get('/api/analytics')
    assert response.status_code == 200
    payload = response.json()
    assert payload['total_emails'] == 1
    assert payload['outcomes']['NEEDS_REVIEW'] == 1
    assert payload['review_reasons']['missing_attachment'] == 1
    supplied = payload['validation']['supplied_dataset']
    assert supplied['available'] is True
    assert supplied['pipeline_macro_f1'] == 1.0
    assert supplied['field_f1'] == 1.0
    assert supplied['review_precision'] == 1.0


def test_failed_processing_can_retry(environment):
    client, repo, classifier, _ = environment
    classifier.predict.side_effect = RuntimeError('test failure')
    assert client.post('/api/emails/demo/process').status_code == 503
    assert repo.history('demo')[0]['result']['processing_status'] == 'FAILED'
    classifier.predict.side_effect = None
    assert client.post('/api/emails/demo/process').status_code == 200


def test_noncomparison_and_api_validation(environment):
    client, _, classifier, _ = environment
    classifier.predict.return_value.update(predicted_category='GENERAL')
    result = client.post('/api/emails/demo/process').json()['result']
    assert result['comparison_status'] is None
    assert result['routing_status'] == 'CLASSIFIED_ONLY'
    assert client.get('/api/emails/missing').status_code == 404
    assert client.get('/api/emails/demo/process').status_code == 405
    assert client.post('/api/emails/demo/review',json={}).status_code == 422
    assert client.get('/api/health').json()['storage_mode'] == 'demo_memory'


def test_category_review_preserves_original_and_rejects_stale_update(environment):
    client, repo, classifier, _ = environment
    classifier.predict.return_value.update(needs_review=True, review_details=['Confirm category'])
    original = client.post('/api/emails/demo/process').json()
    payload={'base_run_id':original['run_id'],'category':'GENERAL','reviewer':'Test operator','reason':'Operational update confirmed','corrections':[]}
    response=client.post('/api/emails/demo/review',json=payload)
    assert response.status_code == 200, response.text
    reviewed=response.json()
    assert reviewed['result']['category']=='GENERAL'
    assert reviewed['result']['routing_source']=='human_review'
    assert reviewed['result']['review_history'][0]['base_run_id']==original['run_id']
    assert repo.history('demo')[1]['result']['category'] is None
    assert client.post('/api/emails/demo/review',json=payload).status_code == 409


def test_workspace_opens_without_access_token_and_keeps_origin_restricted(environment):
    _, repo, classifier, root = environment
    with TestClient(create_app(Settings(dataset=root,demo=True,access_token='demo-secret'),repo,classifier)) as client:
        assert client.get('/api/emails').status_code==200
        response=client.options('/api/emails',headers={'Origin':'https://foreign.example','Access-Control-Request-Method':'GET'})
        assert 'access-control-allow-origin' not in response.headers


def test_real_model_new_backend_contract():
    from model.classifier import EmailClassifier
    from pathlib import Path
    model_path=Path('model/artifacts/email_classifier.joblib')
    if not model_path.exists():
        pytest.skip('Train the model to run the artifact integration test.')
    repo=MemoryRepository()
    with TestClient(create_app(Settings(dataset=Path('sdoc-hackathon-bundle'),demo=True),repo,EmailClassifier())) as client:
        response=client.post('/api/emails/email_001/process')
        assert response.status_code==200,response.text
        assert response.json()['result']['comparison_status']=='OK'

