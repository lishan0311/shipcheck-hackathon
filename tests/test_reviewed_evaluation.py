from scripts.evaluate_reviewed_categories import calculate


def test_reviewed_category_metrics_use_latest_human_decision():
    rows = [
        {'email_id': 'a', 'audit': {'category_before': 'GENERAL', 'category_after': 'SPAM'}},
        {'email_id': 'a', 'audit': {'category_before': 'SPAM', 'category_after': 'SPAM'}},
        {'email_id': 'b', 'audit': {'category_before': 'GENERAL', 'category_after': 'GENERAL'}},
        {'email_id': 'ignored', 'audit': {}},
    ]
    result = calculate(rows)
    assert result['reviewed_emails'] == 2
    assert result['accuracy'] == 1.0
    assert result['per_category']['SPAM']['reviewed'] == 1
