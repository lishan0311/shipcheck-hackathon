"""Optional Gemini fallback for uncertain email routing.

The deterministic classifier stays the default. This module is deliberately
fail-closed: quota, network and response errors leave a case in human review
instead of changing its category or interrupting inbox processing.
"""
import json
import threading

import httpx

from model.classifier import CATEGORIES, email_text


class GeminiAssistant:
    def __init__(self, api_key, model='gemini-2.5-flash-lite', timeout_seconds=8, max_requests=20, client=None):
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self.max_requests = max_requests
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.request_count = 0
        self.consecutive_failures = 0
        self.disabled_reason = None
        self.lock = threading.Lock()

    @property
    def enabled(self):
        return bool(self.api_key and self.model and self.max_requests > 0 and not self.disabled_reason)

    def _disable(self, reason):
        self.disabled_reason = reason

    def _request(self, email):
        text = email_text(email)
        prompt = (
            'Classify this shipping-operations email into exactly one category. '
            'Use only the provided subject and body. Do not infer facts from sender names.\n\n'
            f'Subject: {email.get("subject", "")}\n\nBody:\n{text[:12000]}'
        )
        schema = {
            'type': 'object',
            'properties': {
                'category': {'type': 'string', 'enum': list(CATEGORIES)},
                'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                'rationale': {'type': 'string'},
            },
            'required': ['category', 'confidence', 'rationale'],
        }
        response = self.client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent',
            headers={'x-goog-api-key': self.api_key, 'Content-Type': 'application/json'},
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json', 'responseSchema': schema},
            },
        )
        if response.status_code == 429:
            self._disable('Gemini quota or rate limit reached; using human review until the service restarts.')
            return None
        if response.status_code in (401, 403):
            self._disable('Gemini credentials were rejected; using human review.')
            return None
        response.raise_for_status()
        payload = response.json()
        parts = payload.get('candidates', [{}])[0].get('content', {}).get('parts', [])
        text = ''.join(part.get('text', '') for part in parts)
        result = json.loads(text)
        if result.get('category') not in CATEGORIES:
            raise ValueError('Gemini returned an unsupported category.')
        confidence = float(result.get('confidence'))
        if not 0 <= confidence <= 1:
            raise ValueError('Gemini returned an invalid confidence.')
        rationale = str(result.get('rationale', '')).strip()
        if not rationale:
            raise ValueError('Gemini returned no rationale.')
        return {'category': result['category'], 'confidence': confidence, 'rationale': rationale}

    def _suggest_fields_request(self, kind, text, unresolved_fields):
        schema = {
            'type': 'object',
            'properties': {
                'fields': {
                    'type': 'object',
                    'properties': {
                        field: {
                            'type': 'object',
                            'properties': {
                                'value': {'type': 'string'},
                                'evidence': {'type': 'string'},
                            },
                            'required': ['value', 'evidence'],
                        }
                        for field in unresolved_fields
                    },
                },
            },
            'required': ['fields'],
        }
        prompt = (
            f'This is a {kind} shipping document. Extract only these fields when their exact value is visible: '
            f'{", ".join(unresolved_fields)}. Return no field when uncertain. Evidence must be a short exact quote '
            'from the document and must contain the proposed value. Do not infer or correct text.\n\n'
            f'Document text:\n{text[:20000]}'
        )
        response = self.client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent',
            headers={'x-goog-api-key': self.api_key, 'Content-Type': 'application/json'},
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0, 'responseMimeType': 'application/json', 'responseSchema': schema},
            },
        )
        if response.status_code == 429:
            self._disable('Gemini quota or rate limit reached; using human review until the service restarts.')
            return None
        if response.status_code in (401, 403):
            self._disable('Gemini credentials were rejected; using human review.')
            return None
        response.raise_for_status()
        payload = response.json()
        parts = payload.get('candidates', [{}])[0].get('content', {}).get('parts', [])
        response_text = ''.join(part.get('text', '') for part in parts)
        output = json.loads(response_text).get('fields', {})
        if not isinstance(output, dict):
            raise ValueError('Gemini returned invalid field suggestions.')
        return output

    def suggest_category(self, email):
        """Return a validated suggestion, or None when fallback is unavailable."""
        with self.lock:
            if not self.enabled:
                return None
            if self.request_count >= self.max_requests:
                self._disable(f'Gemini call limit ({self.max_requests}) reached; using human review.')
                return None
            self.request_count += 1
        try:
            suggestion = self._request(email)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            with self.lock:
                self.consecutive_failures += 1
                if self.consecutive_failures >= 3:
                    self._disable('Gemini failed three times; using human review until the service restarts.')
            return None
        with self.lock:
            self.consecutive_failures = 0
        return suggestion

    def suggest_fields(self, kind, text, unresolved_fields):
        """Suggest only missing fields. The caller verifies text evidence."""
        if not unresolved_fields:
            return {}
        with self.lock:
            if not self.enabled:
                return None
            if self.request_count >= self.max_requests:
                self._disable(f'Gemini call limit ({self.max_requests}) reached; using human review.')
                return None
            self.request_count += 1
        try:
            suggestion = self._suggest_fields_request(kind, text, unresolved_fields)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            with self.lock:
                self.consecutive_failures += 1
                if self.consecutive_failures >= 3:
                    self._disable('Gemini failed three times; using human review until the service restarts.')
            return None
        with self.lock:
            self.consecutive_failures = 0
        return suggestion

    def status(self):
        return {
            'configured': bool(self.api_key),
            'enabled': self.enabled,
            'model': self.model if self.api_key else None,
            'requests_used': self.request_count,
            'request_limit': self.max_requests,
            'disabled_reason': self.disabled_reason,
        }
