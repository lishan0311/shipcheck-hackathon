# Architecture review and next priorities

This review treats other teams' public repository pages as implementation
references. The organizer problem statement, rules and supplied data schema
remain the source of requirements.

## Result semantics

- `MISMATCH`: both documents were readable and comparable, and at least one of
  the seven required fields differs. This is a confirmed candidate correction.
- `NEEDS_REVIEW`: the system could not compare safely. The supplied reliability
  reasons are `wrong_doc_type`, `missing_attachment`, `unreadable` and
  `missing_value`.
- In the supplied seed-42 dataset, the reference distribution is 454 `OK`, 46
  `MISMATCH` and 20 `NEEDS_REVIEW`. These counts describe that fixed dataset;
  they are not targets to hard-code for Gmail traffic or regenerated datasets.

The UI keeps one operational Action queue while showing mismatches and review
cases as separate outcomes and filters.

## Current strengths

- React/TypeScript interface and FastAPI/Pydantic API.
- Five-category routing, seven-field evidence-backed comparison and conservative
  OCR handling.
- Real Gmail read/send integration, case references, response matching,
  automatic reprocessing and bulk follow-up.
- Immutable reports and review audit records in Supabase, with attachments in a
  private Storage bucket.
- Deterministic comparison rules and reproducible evaluation on the supplied
  dataset and a separately generated seed.

## Priority 1: make Gmail ingestion restart-safe

Incoming Gmail messages are currently written to `runtime/live-mailbox` before
processing and also synchronized to Supabase. Render's local filesystem is
ephemeral, so a restart can leave database reports present while the source
message and attachment are unavailable to the application.

Add repository methods to load stored email payloads, list attachment metadata
and download private Storage objects. At startup, rebuild the incoming index
from Supabase and hydrate a bounded local cache, or process documents directly
from downloaded bytes. Add a restart integration test that imports one Gmail
message, recreates the application, then opens and reprocesses the same case.

## Priority 2: durable background jobs

Batch and Gmail processing currently run in daemon threads with in-memory
progress. Persist attempts, retry time and the last error in `processing_jobs`.
A worker should claim pending jobs, retry transient failures with backoff, move
exhausted jobs to a visible failed state and resume unfinished jobs after a
restart. A separate managed queue is useful later but is not required for the
first reliable Render deployment.

## Priority 3: targeted AI fallback

The existing scikit-learn classifier is a real ML integration and the
deterministic comparator should remain authoritative. An optional Gemini
fallback can strengthen difficult-input coverage when it is limited to:

1. low-confidence email intent;
2. field proposals when aliases and layout rules fail;
3. scanned-page extraction after OCR is insufficient.

Require structured output, verify every proposed text value against source
evidence, record `decided_by`, model name, confidence and latency, and route
unverified proposals to review. The application must still run without an API
key. Do not use an LLM to decide whether normalized values match.

## Priority 4: visible validation and operations evidence

Add a small analytics page for category distribution, mismatches by field,
review reasons, automation rate, processing failures and latency. Show the
supplied-dataset and holdout metrics from generated artifacts, clearly labelled
as offline validation. This gives judges direct evidence for technology
integration, feasibility and robustness without exposing the answer key to the
runtime system.

## Later hardening

- Structured request and case logs with correlation IDs.
- Supabase Auth or Google OIDC roles instead of a shared access token.
- CSV/PDF report export and aggregate case reporting.
- Sender/template-grouped real-world validation and drift monitoring.

The first four priorities affect architecture, judging evidence or deployment
reliability. Additional visual effects, command palettes and extra navigation
should wait until these are complete.
