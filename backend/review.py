"""Human decisions create an auditable report without rewriting source documents."""

import copy

from .comparison import compare_email, normalize
from .ingestion import load_email
from .repository import timestamp
from .schemas import ReviewRequest


ROUTING_ACTIONS = {
    'SI_REQUEST': 'Prepare a new Shipping Instruction in the normal operations workflow.',
    'INVOICE_QUERY': 'Route the query to the finance or billing team.',
    'GENERAL': 'Route the message to the responsible operations queue.',
    'SPAM': 'No operational action is required.',
}


def comparison_action(result: dict) -> str:
    unknown = [name for name, field in result.get('fields', {}).items() if field.get('state') == 'UNKNOWN']
    defects = result.get('defect_fields', [])
    if unknown:
        if defects:
            return 'Ask the sender to confirm the missing or unclear SI information, and include the confirmed BL discrepancies in the follow-up.'
        return 'Ask the sender to provide or confirm the missing information before the draft BL is approved.'
    if defects:
        return 'Send the discrepancy summary to the carrier or BL issuer and request a revised draft Bill of Lading.'
    return 'No document correction is required. The draft can continue to the next operations step.'


def apply_review(base: dict, request: ReviewRequest, dataset) -> tuple[dict, dict]:
    result = copy.deepcopy(base['result'])
    previous_history = result.get('review_history', [])
    category = request.category or result.get('category')
    if category is None:
        raise ValueError('Confirm an email category before recording a decision.')

    decision = request.decision
    if category != 'BL_COMPARISON':
        # Preserve compatibility with reviews created before decision was explicit.
        if decision == 'CORRECT_EXTRACTION' and not request.corrections:
            decision = 'CONFIRM_CLASSIFICATION'
        if request.corrections:
            raise ValueError('Only comparison requests can have extraction corrections.')
        if decision != 'CONFIRM_CLASSIFICATION':
            raise ValueError('Use Confirm classification for an email that does not require document comparison.')
        result.update(
            category=category, comparison_status=None, fields={}, defect_fields=[], has_defect=None,
            review_reason=None, review_details=[], routing_status='CLASSIFIED_ONLY',
            review_outcome=decision, next_action=ROUTING_ACTIONS[category],
        )
    else:
        if result.get('category') != 'BL_COMPARISON' or not result.get('fields'):
            compared = compare_email(load_email(dataset, base['email_id']))
            compared.update(classification=result.get('classification'), category=category, routing_status='COMPARED')
            result = compared
        if decision == 'CORRECT_EXTRACTION' and not request.corrections:
            raise ValueError('Add at least one corrected extraction value.')
        if decision != 'CORRECT_EXTRACTION' and request.corrections:
            raise ValueError('Field corrections are only allowed when correcting an extraction error.')

        changes = []
        for correction in request.corrections:
            field = result['fields'].get(correction.field)
            if field is None or field[correction.side] is None:
                raise ValueError('Resolve missing or ambiguous documents before correcting their extraction.')
            before = copy.deepcopy(field[correction.side])
            label = 'Gross Weight (KG)' if correction.field == 'gross_weight_kg' else correction.field
            value = normalize(correction.field, correction.raw_value, label)
            field[correction.side] = {
                'raw_value': correction.raw_value, 'normalized_value': value, 'issue': None,
                'source': {'attachment_path': 'human_review', 'quote': correction.raw_value,
                           'locator': {'reviewer': request.reviewer, 'reason': request.reason}},
                'original_source': before.get('original_source') or before.get('source'),
            }
            changes.append({
                'field': correction.field, 'side': correction.side, 'before': before,
                'after': copy.deepcopy(field[correction.side]),
            })

        defects, unknown = [], []
        for name, field in result['fields'].items():
            field['resolution'] = None
            si, bl = field['si'], field['bl']
            if not si or not bl or si.get('issue') or bl.get('issue') or si.get('normalized_value') is None or bl.get('normalized_value') is None:
                field['state'] = 'UNKNOWN'
                unknown.append(name)
            else:
                field['state'] = 'MATCH' if si['normalized_value'] == bl['normalized_value'] else 'MISMATCH'
                if field['state'] == 'MISMATCH':
                    defects.append(name)

        structural_review = result.get('review_reason') in {'wrong_doc_type', 'missing_attachment', 'unreadable'}
        if decision == 'ACCEPT_EQUIVALENT':
            if unknown or structural_review:
                raise ValueError('Missing or unreadable fields cannot be accepted as equivalent. Request clarification or correct the extraction.')
            if not defects:
                raise ValueError('There are no extracted differences to accept as equivalent.')
            unsafe = [name for name in defects if name not in {'shipper', 'consignee', 'notify_party'}]
            if unsafe:
                raise ValueError('Counts, weights and ports cannot be waived as presentation differences.')
            for name in defects:
                result['fields'][name]['state'] = 'MATCH'
                result['fields'][name]['resolution'] = 'ACCEPTED_EQUIVALENT'
            changes.extend({'field': name, 'side': 'both', 'accepted_as_equivalent': True} for name in defects)
            defects = []
        elif decision == 'CONFIRM_DISCREPANCY' and not defects:
            raise ValueError('There is no extracted discrepancy to confirm.')

        result['defect_fields'] = defects
        if unknown or structural_review:
            result['comparison_status'] = 'NEEDS_REVIEW'
            result['has_defect'] = True if defects else None
            if not structural_review:
                result.update(
                    review_reason='missing_value',
                    review_details=[f'Unresolved field: {name}' for name in unknown],
                )
        else:
            result.update(
                comparison_status='MISMATCH' if defects else 'OK', has_defect=bool(defects),
                review_reason=None, review_details=[],
            )
        result.update(review_outcome=decision, next_action=comparison_action(result))

    audit = {
        'base_run_id': base['run_id'], 'reviewer': request.reviewer, 'reason': request.reason,
        'decision': decision, 'created_at': timestamp(),
        'category_before': base['result'].get('category'), 'category_after': category,
        'changes': locals().get('changes', []),
    }
    result.update(
        processing_status='COMPLETED', routing_source='human_review', error=None,
        review_history=previous_history + [audit],
    )
    return result, audit
