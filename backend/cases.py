"""Case lifecycle helpers for outbound follow-up and inbound replies."""
import copy
import re

from .repository import timestamp


CASE_PATTERN = re.compile(r'\[SC-([A-Za-z0-9_-]+)\]', re.IGNORECASE)
REPLY_PREFIX = re.compile(r'^\s*(?:(?:re|fw|fwd)\s*[_:\-]\s*)+', re.IGNORECASE)
REFERENCE_PATTERN = re.compile(
    r'\b(?:[A-Z0-9]*[A-Z][A-Z0-9-]*\d[A-Z0-9-]*|\d{8,})\b', re.IGNORECASE,
)


def case_marker(email_id: str) -> str:
    return f'[SC-{email_id}]'


def referenced_email_id(subject: str = '', body: str = '') -> str | None:
    match = CASE_PATTERN.search(subject or '') or CASE_PATTERN.search(body or '')
    return match.group(1) if match else None


def conversation_subject(subject: str = '') -> str:
    """Return a stable key for Re/Fwd variants of the same subject."""
    value = REPLY_PREFIX.sub('', subject or '')
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def business_references(subject: str = '', body: str = '') -> set[str]:
    """Extract strong shipment/order identifiers for conservative fallback matching."""
    values = set()
    for match in REFERENCE_PATTERN.findall(f'{subject}\n{body}'.upper()):
        compact = match.strip('-_')
        if len(compact) >= 7 and (any(char.isalpha() for char in compact) or len(compact) >= 8):
            values.add(compact)
    return values


def start_case(result: dict, email_id: str, contact_to: str) -> dict:
    """Create follow-up state after a human confirms external action is needed."""
    value = copy.deepcopy(result)
    now = timestamp()
    value['routing_status'] = 'FOLLOW_UP_REQUIRED'
    value['next_action'] = 'Contact the sender with the confirmed discrepancy or information request.'
    value['case_tracking'] = {
        'case_id': f'SC-{email_id}', 'status': 'FOLLOW_UP_REQUIRED',
        'contact_to': contact_to, 'contacted_at': None, 'responded_at': None,
        'closed_at': None, 'gmail_thread_id': None, 'response_email_ids': [],
        'history': [{'event': 'FOLLOW_UP_REQUIRED', 'created_at': now}],
    }
    return value


def mark_sent(result: dict, message: dict) -> dict:
    value = copy.deepcopy(result)
    tracking = copy.deepcopy(value.get('case_tracking') or {})
    if not tracking or tracking.get('status') not in {'FOLLOW_UP_REQUIRED', 'WAITING_FOR_RESPONSE'}:
        return value
    if tracking.get('status') == 'WAITING_FOR_RESPONSE':
        return value
    at = message.get('sent_at') or timestamp()
    tracking.update(
        status='WAITING_FOR_RESPONSE', contacted_at=at,
        gmail_thread_id=message.get('gmail_thread_id') or tracking.get('gmail_thread_id'),
        sent_message_id=message.get('gmail_id'),
    )
    tracking.setdefault('history', []).append({'event': 'CONTACTED', 'created_at': at})
    value.update(
        routing_status='WAITING_FOR_RESPONSE', case_tracking=tracking,
        next_action='Waiting for the sender to reply. Follow up if the case becomes overdue.',
    )
    return value


def mark_response(result: dict, message: dict) -> dict:
    value = copy.deepcopy(result)
    tracking = copy.deepcopy(value.get('case_tracking') or {})
    if not tracking or tracking.get('status') == 'COMPLETED':
        return value
    response_id = str(message.get('email_id') or '')
    if response_id in tracking.get('response_email_ids', []):
        return value
    at = message.get('received_at') or timestamp()
    tracking['status'] = 'RESPONSE_RECEIVED'
    tracking['responded_at'] = at
    tracking['gmail_thread_id'] = message.get('gmail_thread_id') or tracking.get('gmail_thread_id')
    tracking.setdefault('response_email_ids', []).append(response_id)
    tracking.setdefault('history', []).append({'event': 'RESPONSE_RECEIVED', 'created_at': at, 'email_id': response_id})
    value.update(
        routing_status='RESPONSE_RECEIVED', case_tracking=tracking,
        next_action='Review the sender response and complete the case or send another follow-up.',
    )
    return value


def link_response(result: dict, parent_email_id: str) -> dict:
    value = copy.deepcopy(result)
    value['routing_status'] = f'CASE_RESPONSE:{parent_email_id}'
    value['case_parent_email_id'] = parent_email_id
    # A message linked into another case is correspondence, not a second active
    # case. Clear any stale lifecycle state left by an earlier manual reprocess.
    value['case_tracking'] = None
    value['next_action'] = None
    return value


def complete_case(result: dict) -> dict:
    value = copy.deepcopy(result)
    tracking = copy.deepcopy(value.get('case_tracking') or {})
    if not tracking:
        raise ValueError('This email does not have an active follow-up case.')
    if tracking.get('status') == 'COMPLETED':
        return value
    now = timestamp()
    tracking.update(status='COMPLETED', closed_at=now)
    tracking.setdefault('history', []).append({'event': 'COMPLETED', 'created_at': now})
    value.update(
        routing_status='COMPLETED', case_tracking=tracking,
        next_action='Case completed. No further action is required.',
    )
    return value


def auto_complete(result: dict) -> dict:
    """Close a comparison automatically once all seven fields align."""
    value = copy.deepcopy(result)
    if value.get('comparison_status') != 'OK':
        return value
    now = timestamp()
    tracking = copy.deepcopy(value.get('case_tracking'))
    if tracking:
        if tracking.get('status') != 'COMPLETED':
            tracking.update(status='COMPLETED', closed_at=now)
            tracking.setdefault('history', []).append({
                'event': 'AUTO_COMPLETED', 'created_at': now,
                'reason': 'All seven comparison fields aligned.',
            })
        value['case_tracking'] = tracking
    value.update(
        routing_status='COMPLETED',
        next_action='All seven fields align. This case was completed automatically.',
    )
    return value
