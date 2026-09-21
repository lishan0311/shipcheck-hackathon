"""HTTP contracts: shared concepts are mirrored in frontend/src/types.ts."""
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal['BL_COMPARISON', 'SI_REQUEST', 'INVOICE_QUERY', 'GENERAL', 'SPAM']
FieldName = Literal['shipper', 'consignee', 'notify_party', 'port_of_loading', 'port_of_discharge', 'container_count', 'gross_weight_kg']
ReviewDecision = Literal['CONFIRM_DISCREPANCY', 'REQUEST_CLARIFICATION', 'CORRECT_EXTRACTION', 'ACCEPT_EQUIVALENT', 'CONFIRM_CLASSIFICATION']
CaseStatus = Literal['FOLLOW_UP_REQUIRED', 'WAITING_FOR_RESPONSE', 'RESPONSE_RECEIVED', 'COMPLETED']


class Email(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    email_id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    sender: str = Field(alias='from')
    subject: str
    body: str
    attachments: list[str]
    received_at: str | None = None


class Source(BaseModel):
    attachment_path: str
    quote: str
    locator: dict[str, Any]


class ExtractedValue(BaseModel):
    raw_value: str | None = None
    normalized_value: str | int | None = None
    source: Source | None = None
    issue: str | None = None
    candidates: list['ExtractedValue'] | None = None
    original_source: Source | None = None


class FieldComparison(BaseModel):
    si: ExtractedValue | None
    bl: ExtractedValue | None
    state: Literal['MATCH', 'MISMATCH', 'UNKNOWN']
    resolution: Literal['ACCEPTED_EQUIVALENT'] | None = None


class Classification(BaseModel):
    model_config = ConfigDict(extra='allow')
    predicted_category: Category
    confidence: float = Field(ge=0, le=1)
    needs_review: bool
    review_details: list[str]


class Report(BaseModel):
    email_id: str
    processing_status: Literal['COMPLETED', 'FAILED']
    category: Category | None = None
    classification: Classification | None = None
    routing_source: str = 'ai_classifier'
    routing_status: str = 'COMPARED'
    comparison_status: Literal['OK', 'MISMATCH', 'NEEDS_REVIEW'] | None = None
    fields: dict[FieldName, FieldComparison] = Field(default_factory=dict)
    defect_fields: list[FieldName] = Field(default_factory=list)
    has_defect: bool | None = None
    review_reason: Literal['wrong_doc_type', 'missing_attachment', 'unreadable', 'missing_value'] | None = None
    review_details: list[str] = Field(default_factory=list)
    error: dict[str, str] | None = None
    review_history: list[dict[str, Any]] = Field(default_factory=list)
    review_outcome: ReviewDecision | None = None
    next_action: str | None = None
    case_tracking: dict[str, Any] | None = None
    case_parent_email_id: str | None = None

    @model_validator(mode='after')
    def check_ok(self):
        if self.comparison_status == 'OK':
            if len(self.fields) != 7 or any(v.state != 'MATCH' for v in self.fields.values()):
                raise ValueError('OK requires all seven fields to match.')
        return self


class Run(BaseModel):
    run_id: str
    email_id: str
    created_at: str
    result: Report


class Document(BaseModel):
    model_config = ConfigDict(extra='allow')
    path: str
    status: str
    text: str | None
    error: str | None


class EmailDetail(BaseModel):
    email: Email
    ingestion_status: str
    documents: list[Document]
    history: list[Run]
    case_messages: list[dict[str, Any]] = Field(default_factory=list)


class EmailSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    email_id: str
    sender: str = Field(alias='from')
    subject: str
    attachment_count: int
    latest: 'RunSummary | None'


class ReportSummary(BaseModel):
    processing_status: Literal['COMPLETED', 'FAILED']
    category: Category | None = None
    predicted_category: Category | None = None
    confidence: float | None = None
    needs_category_review: bool = False
    routing_status: str
    comparison_status: Literal['OK', 'MISMATCH', 'NEEDS_REVIEW'] | None = None
    review_reason: Literal['wrong_doc_type', 'missing_attachment', 'unreadable', 'missing_value'] | None = None
    defect_fields: list[FieldName] = Field(default_factory=list)
    review_details: list[str] = Field(default_factory=list)
    reviewed: bool = False
    review_outcome: ReviewDecision | None = None
    next_action: str | None = None


class RunSummary(BaseModel):
    run_id: str
    email_id: str
    created_at: str
    result: ReportSummary


class InboxResponse(BaseModel):
    emails: list[EmailSummary]
    errors: list[dict[str, str]]


class BatchStatus(BaseModel):
    running: bool
    total: int
    completed: int
    failed: int
    skipped: int
    current_email_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class BatchRequest(BaseModel):
    """Optional explicit set of inbox emails to process again."""
    model_config = ConfigDict(extra='forbid')
    force: bool | None = None
    email_ids: list[str] | None = Field(default=None, max_length=520)


class ArchiveRequest(BaseModel):
    """Emails to hide from or restore to the operational inbox."""
    model_config = ConfigDict(extra='forbid')
    email_ids: list[str] = Field(min_length=1, max_length=520)

    @model_validator(mode='after')
    def unique_ids(self):
        if len(self.email_ids) != len(set(self.email_ids)):
            raise ValueError('Each email can appear only once.')
        return self


class IncomingAttachment(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    filename: str = Field(min_length=1, max_length=180)
    content_base64: str = Field(min_length=1, max_length=30_000_000)


class IncomingEmail(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True, str_strip_whitespace=True)
    sender: str = Field(alias='from', min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=1000)
    body: str = Field(min_length=1, max_length=100_000)
    attachments: list[IncomingAttachment] = Field(default_factory=list, max_length=6)


class FollowUpBatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email_ids: list[str] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique_ids(self):
        if len(self.email_ids) != len(set(self.email_ids)):
            raise ValueError('Each case can appear only once.')
        return self


class Correction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: FieldName
    side: Literal['si', 'bl']
    raw_value: str = Field(min_length=1, max_length=3000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    base_run_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)
    category: Category | None = None
    decision: ReviewDecision = 'CORRECT_EXTRACTION'
    corrections: list[Correction] = Field(default_factory=list, max_length=14)

    @model_validator(mode='after')
    def validate_changes(self):
        keys = [(c.field, c.side) for c in self.corrections]
        if len(keys) != len(set(keys)):
            raise ValueError('Each side of a field can be corrected only once.')
        if self.category is None and not self.corrections and self.decision == 'CORRECT_EXTRACTION':
            raise ValueError('Confirm a category or provide a field correction.')
        return self
