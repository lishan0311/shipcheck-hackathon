"""FastAPI application for an automatically processed shipping inbox."""
import base64
import binascii
import copy
import json
import logging
import mimetypes
import re
import threading
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from email.utils import parseaddr
from pathlib import Path

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from model.classifier import DEFAULT_MODEL, EmailClassifier
from .ai_assist import GeminiAssistant
from .cases import (
    auto_complete, business_references, case_marker, complete_case, conversation_subject, link_response,
    mark_response, mark_sent, referenced_email_id, start_case,
)
from .comparison import compare_email, document_type
from .ingestion import _dataset_path, load_email
from .mailbox import GmailMailbox
from .pipeline import process_email
from .repository import MemoryRepository, SupabaseRepository, StaleReview, timestamp
from .review import apply_review
from .schemas import ArchiveRequest, BatchRequest, BatchStatus, Email, EmailDetail, FollowUpBatchRequest, InboxResponse, IncomingEmail, Report, ReviewRequest, Run
from .settings import ROOT, Settings

log = logging.getLogger(__name__)


def create_app(settings=None, repository=None, classifier=None, mailbox_client=None):
    settings = settings or Settings.from_env()
    repo = repository
    if repo is None:
        if settings.supabase_url and settings.supabase_key:
            repo = SupabaseRepository(settings.supabase_url, settings.supabase_key, settings.bucket)
        elif settings.demo:
            repo = MemoryRepository()
    model = classifier
    ai_assistant = GeminiAssistant(
        settings.gemini_api_key, settings.gemini_model, settings.gemini_timeout_seconds, settings.gemini_max_requests,
    )
    mailbox = mailbox_client
    mailbox_settings_complete = all((settings.gmail_client_id, settings.gmail_client_secret,
                                     settings.gmail_refresh_token))
    if mailbox is None and settings.mail_provider == 'gmail' and mailbox_settings_complete:
        mailbox = GmailMailbox(
            settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token,
            settings.gmail_user_id, settings.mail_sync_limit,
        )
    process_lock = threading.RLock()
    batch_lock = threading.Lock()
    stop_event = threading.Event()
    batch_thread = [None]
    batch_state = {
        'running': False, 'total': 0, 'completed': 0, 'failed': 0, 'skipped': 0,
        'current_email_id': None, 'started_at': None, 'finished_at': None,
    }
    mailbox_lock = threading.Lock()
    mailbox_thread = [None]
    mailbox_state = {
        'provider': settings.mail_provider or None,
        'configured': mailbox is not None,
        'connected': False,
        'mailbox': getattr(mailbox, 'mailbox', None),
        'syncing': False, 'imported': 0, 'last_sync_at': None, 'last_error': None,
    }

    # Metadata in the participant bundle is immutable. Cache it once instead
    # of parsing all 520 JSON files on every browser refresh.
    email_index, index_errors, email_sources = [], [], {}
    index_lock = threading.RLock()
    for source in (settings.incoming_dir, settings.dataset):
        for file in sorted((source / 'inbox').glob('*.json'), reverse=True):
            try:
                record = load_email(source, file.stem, read_attachments=False)
                email = Email.model_validate(record['email']).model_dump(by_alias=True)
                if email['email_id'] in email_sources:
                    continue
                email_index.append({
                    'email_id': email['email_id'], 'from': email['from'], 'subject': email['subject'],
                    'attachment_count': len(email['attachments']),
                })
                email_sources[email['email_id']] = source
            except ValueError as exc:
                index_errors.append({'file': file.name, 'error': str(exc)})
    def read_email(email_id, attachments=False):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', email_id):
            raise HTTPException(422, 'Invalid email ID.')
        with index_lock:
            source = email_sources.get(email_id)
        if source is None:
            raise HTTPException(404, 'Email not found.')
        try:
            record = load_email(source, email_id, read_attachments=attachments)
            record['email'] = Email.model_validate(record['email']).model_dump(by_alias=True)
            return record
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def validated(result):
        return Report.model_validate(result).model_dump(exclude_none=False)

    def store_incoming(email_id, sender, subject, body, decoded, received_at=None):
        """Write a provider message to the normal ingestion format once."""
        with index_lock:
            if email_id in email_sources:
                return False
        root = settings.incoming_dir.resolve()
        (root / 'inbox').mkdir(parents=True, exist_ok=True)
        (root / 'attachments').mkdir(parents=True, exist_ok=True)
        relative_paths = []
        for index, (name, content) in enumerate(decoded):
            safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('._') or f'attachment_{index}.txt'
            relative = f'attachments/{email_id}_{index}_{safe_name}'
            _dataset_path(root, relative).write_bytes(content)
            relative_paths.append(relative)
        email = {'email_id': email_id, 'from': sender, 'subject': subject,
                 'body': body, 'attachments': relative_paths, 'received_at': received_at}
        Email.model_validate(email)
        inbox_file = _dataset_path(root, f'inbox/{email_id}.json')
        temp_file = inbox_file.with_suffix('.tmp')
        temp_file.write_text(json.dumps(email, ensure_ascii=False, indent=2), encoding='utf-8')
        temp_file.replace(inbox_file)
        with index_lock:
            if email_id in email_sources:
                return False
            email_sources[email_id] = root
            email_index.insert(0, {'email_id': email_id, 'from': sender, 'subject': subject,
                                   'attachment_count': len(relative_paths)})
        return True

    def process_one(email_id):
        nonlocal model
        email = read_email(email_id)['email']
        with index_lock:
            source = email_sources[email_id]
        with process_lock:
            repo.sync_email(email, source)
            job_id = repo.start_job(email_id)
            try:
                if model is None:
                    model = EmailClassifier()
                result = validated(process_email(
                    source, email_id, model, ai_assistant=ai_assistant,
                    ai_min_confidence=settings.gemini_min_confidence,
                ))
            except Exception as exc:
                log.exception('Processing failed for %s', email_id)
                result = validated({
                    'email_id': email_id, 'processing_status': 'FAILED', 'routing_status': 'FAILED',
                    'error': {'message': 'Processing failed. Check server logs and retry.'},
                })
                repo.save(email_id, result, job_id=job_id)
                raise RuntimeError('Processing failed. A failed run was saved; you can retry.') from exc
            return repo.save(email_id, result, job_id=job_id)

    def save_case_change(email_id, change):
        """Append a lifecycle update as a normal immutable report version."""
        with process_lock:
            history = repo.history(email_id)
            if not history:
                return None
            base = history[0]
            result = validated(change(base['result']))
            if result == base['result']:
                return base
            return repo.save(email_id, result, expected=base['run_id'])

    def recognized_documents(email_id):
        """Return readable SI/BL documents grouped by type for one message."""
        record = read_email(email_id, True)
        grouped = {'SI': [], 'BL': []}
        for document in record['documents']:
            if document['status'] != 'READ' or not document.get('text'):
                continue
            kind = document_type(document['text'])
            if kind:
                grouped[kind].append({
                    'email_id': email_id, 'path': document['path'],
                    'document': document,
                })
        return grouped

    def initialize_case_documents(result, email_id):
        grouped = recognized_documents(email_id)
        tracking = result.get('case_tracking') or {}
        tracking['active_documents'] = {
            kind: [{'email_id': item['email_id'], 'path': item['path']} for item in items]
            for kind, items in grouped.items() if items
        }
        result['case_tracking'] = tracking
        return result

    def follow_up_body(result):
        labels = {
            'shipper': 'Shipper', 'consignee': 'Consignee', 'notify_party': 'Notify party',
            'port_of_loading': 'Port of loading', 'port_of_discharge': 'Port of discharge',
            'container_count': 'Container count', 'gross_weight_kg': 'Gross weight (kg)',
        }
        issues = []
        for name, field in (result.get('fields') or {}).items():
            if field.get('state') == 'MATCH':
                continue
            si = ((field.get('si') or {}).get('raw_value') or 'Not available').strip()
            bl = ((field.get('bl') or {}).get('raw_value') or 'Not available').strip()
            issues.append(f"- {labels.get(name, name)}: SI - {si} | Draft BL - {bl}")
        return '\n'.join([
            'Hello,', '',
            'We reviewed the draft Bill of Lading against the Shipping Instruction.', '',
            'Please review the following items:', *(issues or ['- Required information could not be confirmed.']), '',
            'Please reply with the missing information or a revised draft before finalisation.', '',
            'Regards,', 'Shipping Operations',
        ])

    def compare_case_response(result, parent_id, response_id, message):
        """Re-run comparison with the newest SI/BL attachment per document type."""
        existing_tracking = result.get('case_tracking') or {}
        if response_id in existing_tracking.get('response_email_ids', []):
            return result
        updated = mark_response(result, message)
        if updated.get('category') != 'BL_COMPARISON':
            return updated
        tracking = updated.get('case_tracking') or {}
        active = copy.deepcopy(tracking.get('active_documents') or {})
        if not active:
            initial = recognized_documents(parent_id)
            active = {
                kind: [{'email_id': item['email_id'], 'path': item['path']} for item in items]
                for kind, items in initial.items() if items
            }
        response_documents = recognized_documents(response_id)
        has_new_document = False
        for kind, items in response_documents.items():
            if items:
                has_new_document = True
                active[kind] = [{'email_id': item['email_id'], 'path': item['path']} for item in items]
        tracking['active_documents'] = active
        updated['case_tracking'] = tracking
        if not has_new_document:
            return updated

        selected = []
        for descriptors in active.values():
            for descriptor in descriptors:
                source = read_email(descriptor['email_id'], True)
                document = next((item for item in source['documents'] if item['path'] == descriptor['path']), None)
                if document:
                    document = copy.deepcopy(document)
                    document['path'] = f"{descriptor['email_id']}/{document['path']}"
                    selected.append(document)
        parent = read_email(parent_id)['email']
        compared = compare_email({'email': parent, 'documents': selected})
        compared.update(
            category='BL_COMPARISON', classification=updated.get('classification'),
            routing_source='case_response', routing_status='RESPONSE_RECEIVED',
            case_tracking=tracking, review_history=updated.get('review_history', []),
            review_outcome=updated.get('review_outcome'),
            next_action='Review the comparison against the latest case attachments, then complete the case or contact the sender again.',
        )
        return auto_complete(compared)

    def run_batch(force=False, email_ids=None):
        try:
            existing = repo.latest_all(compact=True)
            with index_lock:
                archived_ids = repo.archived_email_ids()
                indexed_ids = [item['email_id'] for item in email_index if item['email_id'] not in archived_ids]
            indexed_set = set(indexed_ids)
            if email_ids is not None:
                # Keep the supplied order, discard stale IDs and process each email once.
                targets = list(dict.fromkeys(email_id for email_id in email_ids if email_id in indexed_set))
                skipped = 0
            else:
                targets = indexed_ids if force else [email_id for email_id in indexed_ids if email_id not in existing]
                skipped = len(indexed_ids) - len(targets)
            with batch_lock:
                batch_state.update(
                    running=True, total=len(targets) if email_ids is not None else len(indexed_ids), completed=0, failed=0,
                    skipped=skipped, current_email_id=None,
                    started_at=timestamp(), finished_at=None,
                )
            for email_id in targets:
                if stop_event.is_set():
                    break
                with batch_lock:
                    batch_state['current_email_id'] = email_id
                try:
                    process_one(email_id)
                    with batch_lock:
                        batch_state['completed'] += 1
                except Exception:
                    log.exception('Automatic inbox processing failed for %s', email_id)
                    with batch_lock:
                        batch_state['failed'] += 1
        except Exception:
            log.exception('Automatic inbox processing could not start')
            with batch_lock:
                batch_state['failed'] += 1
        finally:
            with batch_lock:
                batch_state.update(running=False, current_email_id=None, finished_at=timestamp())

    def start_batch(force=False, email_ids=None):
        with batch_lock:
            if batch_state['running'] or (batch_thread[0] and batch_thread[0].is_alive()):
                return copy.deepcopy(batch_state)
            thread = threading.Thread(target=run_batch, args=(force, email_ids), name='inbox-auto-processor', daemon=True)
            batch_thread[0] = thread
            thread.start()
            return copy.deepcopy(batch_state)

    def sync_mailbox():
        if mailbox is None:
            raise RuntimeError('Gmail mailbox is not configured.')
        if not mailbox_lock.acquire(blocking=False):
            return copy.deepcopy(mailbox_state)
        try:
            mailbox_state.update(syncing=True, last_error=None)
            messages = mailbox.fetch()
            sent_messages = mailbox.fetch_sent() if callable(getattr(mailbox, 'fetch_sent', None)) else []
            imported = 0
            latest = repo.latest_all(compact=True)
            # Apply the automatic-completion rule to older response results too.
            for email_id, run in list(latest.items()):
                result = run.get('result', {})
                if result.get('routing_status') == 'RESPONSE_RECEIVED' and result.get('comparison_status') == 'OK':
                    saved = save_case_change(email_id, auto_complete)
                    if saved:
                        latest[email_id] = saved
            thread_cases = {}
            active_case_ids = [email_id for email_id, run in latest.items()
                               if run.get('result', {}).get('routing_status') in {
                                   'FOLLOW_UP_REQUIRED', 'WAITING_FOR_RESPONSE', 'RESPONSE_RECEIVED'}]
            subject_cases, reference_cases = {}, {}
            for email_id in active_case_ids:
                history = repo.history(email_id)
                tracking = history[0]['result'].get('case_tracking') if history else None
                if tracking and tracking.get('gmail_thread_id'):
                    thread_cases[str(tracking['gmail_thread_id'])] = email_id
                case_email = read_email(email_id)['email']
                subject_key = conversation_subject(case_email.get('subject', ''))
                if subject_key:
                    subject_cases.setdefault(subject_key, []).append(email_id)
                for reference in business_references(case_email.get('subject', ''), case_email.get('body', '')):
                    reference_cases.setdefault(reference, []).append(email_id)

            def matched_parent(message):
                explicit = referenced_email_id(message.get('subject', ''), message.get('body', ''))
                if explicit in active_case_ids:
                    return explicit
                threaded = thread_cases.get(str(message.get('gmail_thread_id') or ''))
                if threaded:
                    return threaded
                subject_key = conversation_subject(message.get('subject', ''))
                subject_matches = subject_cases.get(subject_key, []) if subject_key else []
                if len(subject_matches) == 1:
                    return subject_matches[0]
                candidates = set()
                for reference in business_references(message.get('subject', ''), message.get('body', '')):
                    matches = reference_cases.get(reference, [])
                    if len(matches) == 1:
                        candidates.add(matches[0])
                return next(iter(candidates)) if len(candidates) == 1 else None

            for message in sent_messages:
                parent_id = matched_parent(message)
                if parent_id and parent_id in latest:
                    save_case_change(parent_id, lambda result, item=message: mark_sent(result, item))
            # Gmail returns newest first. Insert oldest first so the newest
            # message remains at the top of the local inbox.
            for message in reversed(messages):
                created = store_incoming(
                    message['email_id'], message['from'], message['subject'],
                    message['body'], message['attachments'], message.get('received_at'),
                )
                if created:
                    imported += 1
                    if message['email_id'] not in latest:
                        process_one(message['email_id'])
                parent_id = matched_parent(message)
                if parent_id and parent_id != message['email_id'] and parent_id in latest:
                    child_history = repo.history(message['email_id'])
                    child_result = child_history[0]['result'] if child_history else {}
                    child_parent = child_result.get('case_parent_email_id')
                    if child_parent != parent_id or child_result.get('case_tracking'):
                        save_case_change(message['email_id'], lambda result, parent=parent_id: link_response(result, parent))
                    save_case_change(parent_id, lambda result, item=message, parent=parent_id,
                                     response=message['email_id']: compare_case_response(result, parent, response, item))
            mailbox_state.update(connected=True, syncing=False, imported=imported,
                                 last_sync_at=timestamp(), last_error=None)
            return copy.deepcopy(mailbox_state)
        except Exception as exc:
            log.exception('Gmail mailbox synchronization failed')
            mailbox_state.update(connected=False, syncing=False, last_sync_at=timestamp(),
                                 last_error='Gmail synchronization failed. Check OAuth credentials and Gmail API access.')
            raise RuntimeError(mailbox_state['last_error']) from exc
        finally:
            mailbox_lock.release()

    def mailbox_loop():
        while not stop_event.is_set():
            try:
                sync_mailbox()
            except RuntimeError:
                pass
            if stop_event.wait(settings.mail_poll_seconds):
                break

    @asynccontextmanager
    async def lifespan(app):
        if repo is None:
            raise RuntimeError('Configure Supabase, or explicitly enable demo mode for local development.')
        if settings.auto_process:
            start_batch()
        if mailbox is not None:
            mailbox_thread[0] = threading.Thread(target=mailbox_loop, name='gmail-mailbox-sync', daemon=True)
            mailbox_thread[0].start()
        yield
        stop_event.set()
        if batch_thread[0] and batch_thread[0].is_alive():
            batch_thread[0].join(timeout=5)
        if mailbox_thread[0] and mailbox_thread[0].is_alive():
            mailbox_thread[0].join(timeout=5)
        if mailbox is not None:
            mailbox.close()
        repo.close()

    app = FastAPI(title='ShipCheck API', version='0.3.0', lifespan=lifespan)
    origins = ['http://localhost:5173', 'http://127.0.0.1:5173']
    if settings.frontend_origin:
        origins.append(settings.frontend_origin)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(set(origins)), allow_methods=['GET', 'POST'],
        allow_headers=['Content-Type', 'Authorization'],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.exception_handler(httpx.HTTPError)
    async def storage_error(request, exc):
        log.error('Supabase request failed: %s', type(exc).__name__)
        return JSONResponse(status_code=503, content={'detail': 'Supabase is unavailable. Check backend credentials and migrations.'})

    @app.exception_handler(StaleReview)
    async def stale_review(request, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    def authorize(request: Request):
        if repo is None:
            raise HTTPException(503, 'Supabase is not configured.')

    @app.get('/api/health')
    def health():
        return {
            'status': 'ok' if repo else 'not_configured',
            'storage_mode': repo.mode if repo else 'not_configured',
            'persistent': repo is not None and repo.mode == 'supabase',
            'model_available': model is not None or DEFAULT_MODEL.is_file(),
            'requires_access_token': False,
            'mailbox_provider': mailbox_state['provider'],
            'mailbox_configured': mailbox_state['configured'],
            'ai_assistant': ai_assistant.status(),
        }

    @app.get('/api/mailbox/status', dependencies=[Depends(authorize)])
    def mailbox_status():
        return copy.deepcopy(mailbox_state)

    @app.get('/api/analytics', dependencies=[Depends(authorize)])
    def analytics():
        """Aggregate saved reports for the operational analytics dashboard."""
        latest = repo.latest_all(compact=True)
        with index_lock:
            ids = [item['email_id'] for item in email_index]
        reports = [latest[email_id]['result'] for email_id in ids if email_id in latest
                   and not str(latest[email_id]['result'].get('routing_status', '')).startswith('CASE_RESPONSE:')]
        outcomes = Counter()
        categories = Counter()
        mismatch_fields = Counter()
        review_reasons = Counter()
        workflows = Counter()
        for report in reports:
            category = report.get('category') or report.get('predicted_category')
            if category:
                categories[category] += 1
            comparison = report.get('comparison_status')
            if comparison == 'MISMATCH':
                outcomes['MISMATCH'] += 1
                mismatch_fields.update(report.get('defect_fields') or [])
            elif comparison == 'NEEDS_REVIEW':
                outcomes['NEEDS_REVIEW'] += 1
                if report.get('review_reason'):
                    review_reasons[report['review_reason']] += 1
            elif report.get('processing_status') == 'COMPLETED' and category:
                outcomes['OK'] += 1
            else:
                outcomes['UNPROCESSED'] += 1
            workflows[report.get('routing_status') or 'PROCESSING'] += 1

        def validation_file(name):
            # Published evaluation artifacts are immutable results produced by the
            # organizer-compatible scorer. `runtime/` remains a local override for
            # re-running an evaluation; Render reads the versioned artifact instead.
            paths = (ROOT / 'runtime' / name, ROOT / 'model' / 'artifacts' / name)
            try:
                path = next(candidate for candidate in paths if candidate.is_file())
                data = json.loads(path.read_text(encoding='utf-8'))
                classification = data.get('classification', {})
                model_only = classification.get('model_only', {})
                pipeline = classification.get('rules_plus_model', {})
                score = data.get('organizer_score', {})
                reliability = score.get('reliability', {})
                return {
                    'available': True,
                    'model_accuracy': model_only.get('accuracy'),
                    'model_macro_f1': model_only.get('macro_f1'),
                    'pipeline_accuracy': pipeline.get('accuracy'),
                    'pipeline_macro_f1': pipeline.get('macro_f1'),
                    'field_f1': score.get('stage3', {}).get('field_f1'),
                    'end_to_end': score.get('end_to_end', {}).get('rate'),
                    'review_precision': reliability.get('escalation_precision'),
                    'review_recall': reliability.get('escalation_recall'),
                    'review_f1': reliability.get('escalation_f1'),
                    'final_score': score.get('final_score'),
                    'email_count': score.get('n_emails'),
                    'source': 'Organizer-compatible scorer',
                }
            except (StopIteration, OSError, UnicodeError, json.JSONDecodeError):
                return {'available': False}

        return {
            'total_emails': len(ids), 'processed_emails': len(reports),
            'outcomes': {key: outcomes.get(key, 0) for key in ('OK', 'MISMATCH', 'NEEDS_REVIEW', 'UNPROCESSED')},
            'categories': dict(categories), 'mismatch_fields': dict(mismatch_fields),
            'review_reasons': {key: review_reasons.get(key, 0) for key in ('wrong_doc_type', 'missing_attachment', 'unreadable', 'missing_value')},
            'workflows': dict(workflows), 'ai_assistant': ai_assistant.status(),
            'validation': {
                'supplied_dataset': validation_file('evaluation-current.json'),
                'independent_holdout': validation_file('evaluation-holdout-seed-73.json'),
            },
        }

    @app.post('/api/mailbox/sync', dependencies=[Depends(authorize)])
    def mailbox_sync():
        try:
            return sync_mailbox()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post('/api/cases/follow-ups', dependencies=[Depends(authorize)])
    def send_follow_ups(request: FollowUpBatchRequest):
        if mailbox is None or not callable(getattr(mailbox, 'send', None)):
            raise HTTPException(503, 'Gmail sending is not configured.')
        results = []
        for email_id in request.email_ids:
            try:
                email = read_email(email_id)['email']
                history = repo.history(email_id)
                if not history:
                    raise ValueError('Case report was not found.')
                report = history[0]['result']
                tracking = report.get('case_tracking') or {}
                if report.get('routing_status') != 'FOLLOW_UP_REQUIRED' or tracking.get('status') != 'FOLLOW_UP_REQUIRED':
                    raise ValueError('Case is not ready for follow-up.')
                recipient = parseaddr(str(tracking.get('contact_to') or email['from']))[1]
                if not recipient or '@' not in recipient:
                    raise ValueError('Recipient email address is invalid.')
                subject = f"{case_marker(email_id)} Re: {email['subject']}"
                sent = mailbox.send(
                    recipient, subject, follow_up_body(report),
                    tracking.get('gmail_thread_id'),
                )
                save_case_change(email_id, lambda result, message=sent: mark_sent(result, message))
                results.append({'email_id': email_id, 'recipient': recipient, 'status': 'SENT'})
            except httpx.HTTPStatusError as exc:
                permission_error = exc.response.status_code in {401, 403}
                results.append({
                    'email_id': email_id, 'status': 'FAILED',
                    'error': 'Gmail send permission is missing. Reauthorize Gmail and retry.' if permission_error
                    else 'Gmail could not send this follow-up. Retry later.',
                })
            except (ValueError, HTTPException) as exc:
                results.append({'email_id': email_id, 'status': 'FAILED', 'error': str(getattr(exc, 'detail', exc))})
        sent_count = sum(item['status'] == 'SENT' for item in results)
        return {
            'requested': len(request.email_ids), 'sent': sent_count,
            'failed': len(results) - sent_count, 'results': results,
        }

    @app.get('/api/batch', response_model=BatchStatus, dependencies=[Depends(authorize)])
    def batch():
        with batch_lock:
            return copy.deepcopy(batch_state)

    @app.post('/api/batch/start', response_model=BatchStatus, dependencies=[Depends(authorize)])
    def batch_start(force: bool = False, request: BatchRequest | None = None):
        requested_force = request.force if request and request.force is not None else force
        return start_batch(force=requested_force, email_ids=request.email_ids if request else None)

    def indexed_inbox(archived=False):
        latest = repo.latest_all(compact=True)
        archived_ids = repo.archived_email_ids()
        with index_lock:
            items = copy.deepcopy(email_index)
        return {
            'emails': [{**item, 'latest': latest.get(item['email_id'])} for item in items
                       if (item['email_id'] in archived_ids) == archived
                       and not str((latest.get(item['email_id']) or {}).get('result', {}).get('routing_status', '')).startswith('CASE_RESPONSE:')],
            'errors': index_errors,
        }

    @app.get('/api/emails', response_model=InboxResponse, dependencies=[Depends(authorize)])
    def emails():
        return indexed_inbox()

    @app.get('/api/archived', response_model=InboxResponse, dependencies=[Depends(authorize)])
    def archived_emails():
        return indexed_inbox(archived=True)

    @app.post('/api/emails/archive', dependencies=[Depends(authorize)])
    def archive_emails(request: ArchiveRequest):
        with index_lock:
            known_ids = {item['email_id'] for item in email_index}
        selected = [email_id for email_id in request.email_ids if email_id in known_ids]
        repo.set_archived(selected, True)
        return {'updated': len(selected)}

    @app.post('/api/emails/restore', dependencies=[Depends(authorize)])
    def restore_emails(request: ArchiveRequest):
        with index_lock:
            known_ids = {item['email_id'] for item in email_index}
        selected = [email_id for email_id in request.email_ids if email_id in known_ids]
        repo.set_archived(selected, False)
        return {'updated': len(selected)}

    @app.post('/api/incoming-email', response_model=Run, dependencies=[Depends(authorize)])
    def incoming_email(request: IncomingEmail):
        """Provider-neutral webhook contract for optional external integrations."""
        allowed = {'.txt', '.pdf', '.docx', '.xlsx'}
        decoded = []
        total_size = 0
        for item in request.attachments:
            name = Path(item.filename).name
            if not name or Path(name).suffix.lower() not in allowed:
                raise HTTPException(422, f'Unsupported attachment: {item.filename}')
            try:
                content = base64.b64decode(item.content_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(422, f'Invalid attachment encoding: {name}') from exc
            if not content or len(content) > 20 * 1024 * 1024:
                raise HTTPException(422, f'Attachment must be between 1 byte and 20 MB: {name}')
            total_size += len(content)
            decoded.append((name, content))
        if total_size > 40 * 1024 * 1024:
            raise HTTPException(422, 'Combined attachments exceed 40 MB.')

        email_id = f'live_{uuid.uuid4().hex[:12]}'
        store_incoming(email_id, request.sender, request.subject, request.body, decoded)
        return process_one(email_id)

    @app.get('/api/emails/{email_id}', response_model=EmailDetail, dependencies=[Depends(authorize)])
    def email_detail(email_id: str):
        history = repo.history(email_id)
        children = []
        if history and history[0]['result'].get('case_tracking'):
            latest = repo.latest_all(compact=True)
            prefix = f'CASE_RESPONSE:{email_id}'
            for child_id, run in latest.items():
                if str(run.get('result', {}).get('routing_status', '')) != prefix:
                    continue
                child_record = read_email(child_id, True)
                child = child_record['email']
                children.append({
                    'email_id': child_id, 'from': child['from'], 'subject': child['subject'],
                    'body': child['body'], 'received_at': child.get('received_at'),
                    'documents': child_record['documents'],
                })
            children.sort(key=lambda item: item.get('received_at') or '')
        return {**read_email(email_id, True), 'history': history, 'case_messages': children}

    @app.get('/api/emails/{email_id}/attachments/{attachment_index}', dependencies=[Depends(authorize)])
    def attachment(email_id: str, attachment_index: int):
        email = read_email(email_id)['email']
        if attachment_index < 0 or attachment_index >= len(email['attachments']):
            raise HTTPException(404, 'Attachment not found.')
        try:
            with index_lock:
                source = email_sources[email_id]
            file = _dataset_path(source.resolve(), email['attachments'][attachment_index])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not file.is_file():
            raise HTTPException(404, 'Attachment file is missing.')
        return FileResponse(file, filename=file.name, media_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')

    @app.post('/api/emails/{email_id}/process', response_model=Run, dependencies=[Depends(authorize)])
    def process(email_id: str):
        try:
            return process_one(email_id)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post('/api/emails/{email_id}/review', response_model=Run, dependencies=[Depends(authorize)])
    def review(email_id: str, request: ReviewRequest):
        email = read_email(email_id)['email']
        with index_lock:
            source = email_sources[email_id]
        with process_lock:
            history = repo.history(email_id)
            if not history or history[0]['run_id'] != request.base_run_id:
                raise HTTPException(409, 'This report changed. Reload before reviewing it.')
            if history[0]['result']['processing_status'] == 'FAILED':
                raise HTTPException(422, 'Retry the failed run before reviewing it.')
            try:
                result, audit = apply_review(history[0], request, source)
                if request.decision in {'CONFIRM_DISCREPANCY', 'REQUEST_CLARIFICATION'}:
                    result = start_case(result, email_id, email['from'])
                    result = initialize_case_documents(result, email_id)
                result = auto_complete(result)
                result = validated(result)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            repo.sync_email(email, source)
            return repo.save(email_id, result, expected=request.base_run_id, review=audit)

    @app.post('/api/emails/{email_id}/case/complete', response_model=Run, dependencies=[Depends(authorize)])
    def case_complete(email_id: str):
        read_email(email_id)
        try:
            saved = save_case_change(email_id, complete_case)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if saved is None:
            raise HTTPException(404, 'Case not found.')
        return saved

    dist = ROOT / 'frontend' / 'dist'
    if (dist / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
    if (dist / 'icons').is_dir():
        app.mount('/icons', StaticFiles(directory=dist / 'icons'), name='icons')
    if (dist / 'brand').is_dir():
        app.mount('/brand', StaticFiles(directory=dist / 'brand'), name='brand')

    @app.get('/favicon.svg', include_in_schema=False)
    def favicon():
        file = dist / 'favicon.svg'
        if not file.is_file():
            raise HTTPException(404, 'Not found.')
        return FileResponse(file, media_type='image/svg+xml')

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        if path.startswith('api/emails/') and path.endswith(('/process', '/review')):
            raise HTTPException(405, 'Use POST for this endpoint.')
        if path.startswith('api/') or Path(path).suffix:
            raise HTTPException(404, 'Not found.')
        index = dist / 'index.html'
        if not index.is_file():
            raise HTTPException(503, 'Frontend is not built. Run npm run build in frontend.')
        return FileResponse(index)

    return app


app = create_app()
