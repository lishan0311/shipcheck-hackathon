export type Category = 'BL_COMPARISON' | 'SI_REQUEST' | 'INVOICE_QUERY' | 'GENERAL' | 'SPAM';
export type FieldName = 'shipper' | 'consignee' | 'notify_party' | 'port_of_loading' | 'port_of_discharge' | 'container_count' | 'gross_weight_kg';
export type ReviewReason = 'wrong_doc_type' | 'missing_attachment' | 'unreadable' | 'missing_value';
export type ReviewDecision = 'CONFIRM_DISCREPANCY' | 'REQUEST_CLARIFICATION' | 'CORRECT_EXTRACTION' | 'ACCEPT_EQUIVALENT' | 'CONFIRM_CLASSIFICATION';
export interface Source { attachment_path: string; quote: string; locator: Record<string, unknown> }
export interface ExtractedValue { raw_value: string | null; normalized_value: string | number | null; source: Source | null; issue: string | null; candidates?: ExtractedValue[] | null; original_source?: Source | null }
export interface FieldComparison { si: ExtractedValue | null; bl: ExtractedValue | null; state: 'MATCH' | 'MISMATCH' | 'UNKNOWN'; resolution?: 'ACCEPTED_EQUIVALENT' | null }
export interface Classification { predicted_category: Category; confidence: number; needs_review: boolean; model_version?: string }
export interface Report {
  email_id: string; processing_status: 'COMPLETED' | 'FAILED'; category: Category | null;
  classification: Classification | null; comparison_status: 'OK' | 'MISMATCH' | 'NEEDS_REVIEW' | null;
  review_reason: ReviewReason | null;
  routing_status: string; routing_source: string; fields: Partial<Record<FieldName, FieldComparison>>;
  defect_fields: FieldName[]; review_details: string[]; review_history: Record<string, unknown>[];
  review_outcome?: ReviewDecision | null; next_action?: string | null;
  case_tracking?: {case_id:string;status:string;contact_to:string;contacted_at?:string|null;responded_at?:string|null;closed_at?:string|null;gmail_thread_id?:string|null;response_email_ids?:string[];history?:Record<string,unknown>[]} | null;
  case_parent_email_id?: string | null;
  error: { message: string } | null;
}
export interface Run { run_id: string; email_id: string; created_at: string; result: Report }
export interface ReportSummary {
  processing_status: 'COMPLETED' | 'FAILED'; category: Category | null; predicted_category: Category | null;
  confidence: number | null; needs_category_review: boolean; routing_status: string;
  comparison_status: 'OK' | 'MISMATCH' | 'NEEDS_REVIEW' | null; defect_fields: FieldName[];
  review_reason: ReviewReason | null;
  review_details: string[]; reviewed: boolean;
  review_outcome?: ReviewDecision | null; next_action?: string | null;
}
export interface RunSummary { run_id: string; email_id: string; created_at: string; result: ReportSummary }
export interface EmailSummary { email_id: string; from: string; subject: string; attachment_count: number; latest: RunSummary | null }
export interface Inbox { emails: EmailSummary[]; errors: {file: string; error: string}[] }
export interface EmailDetail {
  email: {email_id: string; from: string; subject: string; body: string; attachments: string[]; received_at?:string|null};
  documents: {path: string; status: string; text: string | null; error: string | null; warnings?: string[]}[];
  history: Run[];
  case_messages: {email_id:string;from:string;subject:string;body:string;received_at?:string|null;documents:{path:string;status:string;text:string|null;error:string|null;warnings?:string[]}[]}[];
}
export interface Health { status: string; storage_mode: string; persistent: boolean; model_available: boolean; requires_access_token: boolean; ai_assistant?: {configured:boolean;enabled:boolean;model:string|null;requests_used:number;request_limit:number;disabled_reason:string|null} }
export interface BatchStatus {running: boolean; total: number; completed: number; failed: number; skipped: number; current_email_id: string | null; started_at: string | null; finished_at: string | null}
export interface MailboxStatus {provider: string | null; configured: boolean; connected: boolean; mailbox: string | null; syncing: boolean; imported: number; last_sync_at: string | null; last_error: string | null}
export interface FollowUpBatchResult {requested:number;sent:number;failed:number;results:{email_id:string;recipient?:string;status:'SENT'|'FAILED';error?:string}[]}
export interface ValidationMetrics {available:boolean;model_accuracy?:number;pipeline_accuracy?:number;field_f1?:number;end_to_end?:number;review_precision?:number;review_recall?:number;final_score?:number;email_count?:number}
export interface Analytics {total_emails:number;processed_emails:number;outcomes:Record<'OK'|'MISMATCH'|'NEEDS_REVIEW'|'UNPROCESSED',number>;categories:Record<string,number>;mismatch_fields:Record<string,number>;review_reasons:Record<'wrong_doc_type'|'missing_attachment'|'unreadable'|'missing_value',number>;workflows:Record<string,number>;ai_assistant:{configured:boolean;enabled:boolean;model:string|null;requests_used:number;request_limit:number;disabled_reason:string|null};validation:{supplied_dataset:ValidationMetrics;independent_holdout:ValidationMetrics}}
export interface Correction {field: FieldName; side: 'si' | 'bl'; raw_value: string}
export interface ReviewRequest {base_run_id: string; reviewer: string; reason: string; category: Category | null; decision: ReviewDecision; corrections: Correction[]}
