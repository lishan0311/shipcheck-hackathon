"""Supabase is the persistent store. MemoryRepository is an explicit local demo."""
import copy
import hashlib
import mimetypes
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx


class StaleReview(ValueError):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def compact_run(run):
    """Keep only fields needed by the inbox; full evidence stays in history."""
    result = run['result']
    classification = result.get('classification') or {}
    return {
        'run_id': run['run_id'], 'email_id': run['email_id'], 'created_at': run['created_at'],
        'result': {
            'processing_status': result['processing_status'], 'category': result.get('category'),
            'predicted_category': classification.get('predicted_category'),
            'confidence': classification.get('confidence'),
            'needs_category_review': bool(classification.get('needs_review')),
            'routing_status': result.get('routing_status', 'CLASSIFIED_ONLY'),
            'comparison_status': result.get('comparison_status'),
            'review_reason': result.get('review_reason'),
            'defect_fields': result.get('defect_fields', []),
            'review_details': result.get('review_details', []),
            'reviewed': result.get('routing_source') == 'human_review',
            'review_outcome': result.get('review_outcome'),
            'next_action': result.get('next_action'),
        },
    }


class MemoryRepository:
    mode = 'demo_memory'

    def __init__(self):
        self.runs = []
        self.jobs = {}
        self.emails = {}
        self.attachments = {}
        self.lock = threading.Lock()

    def sync_email(self, email, dataset):
        self.emails[email['email_id']] = copy.deepcopy(email)

    def start_job(self, email_id):
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = {'email_id': email_id, 'status': 'RUNNING'}
        return job_id

    def save(self, email_id, result, job_id=None, expected=None, review=None):
        with self.lock:
            history = self.history(email_id)
            if expected is not None and (not history or history[0]['run_id'] != expected):
                raise StaleReview('A newer report exists. Reload before saving your review.')
            run = {'run_id': str(uuid.uuid4()), 'email_id': email_id, 'created_at': timestamp(), 'result': copy.deepcopy(result)}
            self.runs.append(run)
            if job_id:
                self.jobs[job_id]['status'] = result['processing_status']
            return copy.deepcopy(run)

    def history(self, email_id):
        return copy.deepcopy([run for run in reversed(self.runs) if run['email_id'] == email_id])

    def latest_all(self, compact=False):
        latest = {run['email_id']: run for run in self.runs}
        return {email_id: copy.deepcopy(compact_run(run) if compact else run) for email_id, run in latest.items()}

    def close(self):
        pass


class SupabaseRepository:
    mode = 'supabase'

    def __init__(self, url, key, bucket, client=None):
        self.bucket = bucket
        self.client = client or httpx.Client(base_url=url, timeout=60, headers={'apikey': key, 'Authorization': f'Bearer {key}'})

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code == 409:
            raise StaleReview('A newer report exists. Reload before saving your review.')
        response.raise_for_status()
        return response.json() if response.content else None

    def sync_email(self, email, dataset):
        from .ingestion import _dataset_path
        self.request('POST', '/rest/v1/emails', params={'on_conflict': 'email_id'},
                     headers={'Prefer': 'resolution=merge-duplicates,return=minimal'},
                     json={'email_id': email['email_id'], 'payload': email})
        for relative in email['attachments']:
            file = _dataset_path(dataset.resolve(), relative)
            if not file.is_file():
                continue
            if file.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('Attachment exceeds the 20 MB processing limit.')
            content = file.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            object_path = f'{email["email_id"]}/{digest}/{file.name}'
            encoded = quote(object_path, safe='/')
            self.request('POST', f'/storage/v1/object/{quote(self.bucket, safe="")}/{encoded}',
                         content=content, headers={'Content-Type': mimetypes.guess_type(file.name)[0] or 'application/octet-stream', 'x-upsert': 'true'})
            self.request('POST', '/rest/v1/attachments', params={'on_conflict': 'email_id,path'},
                         headers={'Prefer': 'resolution=merge-duplicates,return=minimal'},
                         json={'email_id': email['email_id'], 'path': relative, 'object_path': object_path, 'sha256': digest, 'size_bytes': len(content)})

    def start_job(self, email_id):
        job_id = str(uuid.uuid4())
        self.request('POST', '/rest/v1/processing_jobs', json={'job_id': job_id, 'email_id': email_id, 'status': 'RUNNING'})
        return job_id

    def save(self, email_id, result, job_id=None, expected=None, review=None):
        return self.request('POST', '/rest/v1/rpc/persist_report', json={
            'p_email_id': email_id, 'p_result': result, 'p_job_id': job_id,
            'p_expected_run_id': expected, 'p_review': review,
        })

    def history(self, email_id):
        return self.request('GET', '/rest/v1/reports', params={'email_id': f'eq.{email_id}', 'order': 'sequence.desc', 'select': 'run_id,email_id,created_at,result'})

    def latest_all(self, compact=False):
        view = 'latest_report_summaries' if compact else 'latest_reports'
        try:
            rows = self.request('GET', f'/rest/v1/{view}', params={'select': 'run_id,email_id,created_at,result'})
        except httpx.HTTPStatusError as exc:
            if not compact or exc.response.status_code != 404:
                raise
            # Existing projects can keep working before migration 002 is run.
            rows = self.request('GET', '/rest/v1/latest_reports', params={'select': 'run_id,email_id,created_at,result'})
            rows = [compact_run(row) for row in rows]
        return {row['email_id']: row for row in rows}

    def close(self):
        self.client.close()
