from unittest.mock import Mock

from backend.ai_assist import GeminiAssistant
from backend.comparison import apply_ai_field_suggestions, extract_fields
from backend.pipeline import process_email


def test_no_api_key_never_calls_gemini():
    client = Mock()
    assistant = GeminiAssistant('', client=client)
    assert assistant.suggest_category({'subject': 'Invoice query', 'body': 'Please check charges'}) is None
    assert not client.post.called
    assert assistant.status()['configured'] is False


def test_rate_limit_disables_fallback_without_raising():
    response = Mock(status_code=429)
    client = Mock()
    client.post.return_value = response
    assistant = GeminiAssistant('test-key', client=client)
    assert assistant.suggest_category({'subject': 'Invoice query', 'body': 'Please check charges'}) is None
    assert assistant.status()['enabled'] is False
    assert 'quota' in assistant.status()['disabled_reason'].lower()
    assert assistant.suggest_category({'subject': 'Another', 'body': 'message'}) is None
    assert client.post.call_count == 1


def test_high_confidence_ai_suggestion_resolves_only_an_uncertain_classifier():
    classifier = Mock()
    classifier.predict.return_value = {
        'predicted_category': 'GENERAL', 'confidence': 0.35, 'needs_review': True,
        'review_details': ['Low confidence'], 'decision_source': 'tfidf_logistic_regression',
    }
    assistant = Mock()
    assistant.model = 'gemini-test'
    assistant.suggest_category.return_value = {
        'category': 'INVOICE_QUERY', 'confidence': 0.96, 'rationale': 'The email asks about billing charges.',
    }
    from unittest.mock import patch
    with patch('backend.pipeline.load_email', return_value={'email': {'subject': 'Billing charge question', 'body': 'Please explain this invoice'}}):
        result = process_email('demo', 'demo_001', classifier, ai_assistant=assistant)
    assert result['category'] == 'INVOICE_QUERY'
    assert result['routing_source'] == 'gemini_fallback'
    assert result['classification']['ai_assistance']['provider'] == 'gemini'


def test_low_confidence_ai_suggestion_stays_in_human_review():
    classifier = Mock()
    classifier.predict.return_value = {
        'predicted_category': 'GENERAL', 'confidence': 0.35, 'needs_review': True,
        'review_details': ['Low confidence'], 'decision_source': 'tfidf_logistic_regression',
    }
    assistant = Mock()
    assistant.suggest_category.return_value = {
        'category': 'INVOICE_QUERY', 'confidence': 0.72, 'rationale': 'Likely a billing question.',
    }
    from unittest.mock import patch
    with patch('backend.pipeline.load_email', return_value={'email': {'subject': 'Billing charge question', 'body': 'Please explain this invoice'}}):
        result = process_email('demo', 'demo_001', classifier, ai_assistant=assistant)
    assert result['category'] is None
    assert result['routing_status'] == 'CLASSIFICATION_REVIEW'
    assert 'below the automatic-routing threshold' in result['classification']['review_details'][-1]


def test_ai_field_suggestion_requires_value_and_evidence_in_the_attachment():
    text = '''Shipping Instruction
Shipper: APRIL FINE PAPER TRADING
Consignee: KPP-ANTALIS (SINGAPORE) PTE. LTD.
NORTH STAR LOGISTICS
Port of Loading: PORT KLANG
Port of Discharge: SINGAPORE
Containers: 2 x 40HC
Gross Weight: 22000 KG
'''
    assistant = Mock()
    assistant.suggest_fields.return_value = {
        'notify_party': {'value': 'NORTH STAR LOGISTICS', 'evidence': 'NORTH STAR LOGISTICS'},
        'shipper': {'value': 'INVENTED COMPANY', 'evidence': 'INVENTED COMPANY'},
    }
    extracted = apply_ai_field_suggestions(text, 'attachments/demo.txt', extract_fields(text, 'attachments/demo.txt'), 'SI', assistant)
    assert extracted['notify_party']['normalized_value'] == 'north star logistics'
    assert extracted['notify_party']['source']['locator']['method'] == 'gemini_verified'
    assert extracted['shipper']['raw_value'] == 'APRIL FINE PAPER TRADING'


def test_ai_field_suggestion_never_replaces_a_deterministic_value():
    text = 'Shipping Instruction\nShipper: APRIL FINE PAPER TRADING\n'
    assistant = Mock()
    assistant.suggest_fields.return_value = {'shipper': {'value': 'APRIL FINE PAPER TRADING', 'evidence': 'Shipper: APRIL FINE PAPER TRADING'}}
    extracted = apply_ai_field_suggestions(text, 'attachments/demo.txt', extract_fields(text, 'attachments/demo.txt'), 'SI', assistant)
    assert extracted['shipper']['source']['locator'].get('method') != 'gemini_verified'
