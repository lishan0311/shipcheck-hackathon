"""Measure category agreement against human-reviewed Supabase decisions."""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.repository import SupabaseRepository
from backend.settings import Settings
from model.classifier import CATEGORIES


def calculate(rows: list[dict]) -> dict:
    latest = {}
    for row in rows:
        audit = row.get('audit') or {}
        actual = audit.get('category_after')
        predicted = audit.get('category_before')
        if actual in CATEGORIES:
            latest[row['email_id']] = (predicted, actual)
    pairs = list(latest.values())
    confusion = {actual: Counter() for actual in CATEGORIES}
    for predicted, actual in pairs:
        confusion[actual][predicted or 'UNRESOLVED'] += 1
    accuracy = sum(predicted == actual for predicted, actual in pairs) / len(pairs) if pairs else 0.0
    per_category = {}
    for category in CATEGORIES:
        tp = sum(predicted == category and actual == category for predicted, actual in pairs)
        fp = sum(predicted == category and actual != category for predicted, actual in pairs)
        fn = sum(predicted != category and actual == category for predicted, actual in pairs)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_category[category] = {'precision': precision, 'recall': recall, 'f1': f1,
                                  'reviewed': sum(actual == category for _, actual in pairs)}
    macro_f1 = sum(item['f1'] for item in per_category.values()) / len(CATEGORIES)
    return {'reviewed_emails': len(pairs), 'accuracy': accuracy, 'macro_f1': macro_f1,
            'per_category': per_category,
            'confusion': {category: dict(values) for category, values in confusion.items()}}


def main() -> int:
    settings = Settings.from_env()
    if not settings.supabase_url or not settings.supabase_key:
        raise SystemExit('Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first.')
    repo = SupabaseRepository(settings.supabase_url, settings.supabase_key, settings.bucket)
    try:
        rows = repo.request('GET', '/rest/v1/reviews', params={
            'select': 'email_id,audit,created_at', 'order': 'created_at.asc',
        })
    finally:
        repo.close()
    result = calculate(rows)
    print(json.dumps(result, indent=2))
    if result['reviewed_emails'] < 50:
        print('\nCaution: review at least 50 randomly sampled emails across all five categories before treating this as a useful live estimate.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
