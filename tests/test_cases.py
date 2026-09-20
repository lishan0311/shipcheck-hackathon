from backend.cases import (
    auto_complete, business_references, complete_case, conversation_subject, link_response,
    mark_response, mark_sent, referenced_email_id, start_case,
)


def base_result():
    return {
        'email_id': 'email_520', 'processing_status': 'COMPLETED',
        'category': 'BL_COMPARISON', 'routing_status': 'COMPARED',
        'comparison_status': 'MISMATCH', 'fields': {}, 'defect_fields': [],
    }


def test_case_reference_requires_explicit_marker():
    assert referenced_email_id('[SC-email_520] Re: draft BL') == 'email_520'
    assert referenced_email_id('Re: draft BL', 'Reference [SC-email_004]') == 'email_004'
    assert referenced_email_id('Re: draft BL') is None


def test_subject_and_business_references_support_safe_reply_matching():
    assert conversation_subject('RE_ AFEMY - 5RCY-68239 - 5250074840') == conversation_subject(
        'Re: AFEMY - 5RCY-68239 - 5250074840'
    )
    assert business_references('AFEMY - 5RCY-68239 - 5250074840') == {
        '5RCY-68239', '5250074840',
    }


def test_follow_up_lifecycle_is_auditable():
    started = start_case(base_result(), 'email_520', 'sender@example.com')
    assert started['routing_status'] == 'FOLLOW_UP_REQUIRED'
    assert started['case_tracking']['case_id'] == 'SC-email_520'

    sent = mark_sent(started, {
        'gmail_id': 'sent-1', 'gmail_thread_id': 'thread-1',
        'sent_at': '2026-09-20T12:00:00+00:00',
    })
    assert sent['routing_status'] == 'WAITING_FOR_RESPONSE'
    assert sent['case_tracking']['contacted_at'] == '2026-09-20T12:00:00+00:00'

    response = mark_response(sent, {
        'email_id': 'mail_reply', 'gmail_thread_id': 'thread-1',
        'received_at': '2026-09-20T13:00:00+00:00',
    })
    assert response['routing_status'] == 'RESPONSE_RECEIVED'
    assert response['case_tracking']['response_email_ids'] == ['mail_reply']

    completed = complete_case(response)
    assert completed['routing_status'] == 'COMPLETED'
    assert completed['case_tracking']['closed_at']
    assert [item['event'] for item in completed['case_tracking']['history']] == [
        'FOLLOW_UP_REQUIRED', 'CONTACTED', 'RESPONSE_RECEIVED', 'COMPLETED',
    ]


def test_response_email_is_linked_without_overwriting_it():
    response = base_result() | {'case_tracking': {'case_id': 'SC-old'}, 'next_action': 'Old action'}
    linked = link_response(response, 'email_520')
    assert linked['routing_status'] == 'CASE_RESPONSE:email_520'
    assert linked['case_parent_email_id'] == 'email_520'
    assert linked['case_tracking'] is None
    assert linked['next_action'] is None


def test_all_aligned_fields_complete_a_case_automatically():
    started = start_case(base_result(), 'email_520', 'sender@example.com')
    started['comparison_status'] = 'OK'
    completed = auto_complete(started)
    assert completed['routing_status'] == 'COMPLETED'
    assert completed['case_tracking']['status'] == 'COMPLETED'
    assert completed['case_tracking']['history'][-1]['event'] == 'AUTO_COMPLETED'
