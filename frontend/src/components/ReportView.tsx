import type {Category, ExtractedValue, FieldComparison, FieldName, ReportSummary, ReviewReason, Run, RunSummary} from '../types';
import Icon from './Icon';

export const categories: Record<Category,string> = {
  BL_COMPARISON:'BL comparison request', SI_REQUEST:'New SI request',
  INVOICE_QUERY:'Invoice query', GENERAL:'General operational email', SPAM:'Spam',
};
export const categoryActions: Record<Category,string> = {
  BL_COMPARISON:'Verify the Shipping Instruction against the draft Bill of Lading.',
  SI_REQUEST:'Prepare a new Shipping Instruction.', INVOICE_QUERY:'Route to finance or billing.',
  GENERAL:'Route to the responsible operations team.', SPAM:'No operational action.',
};
export const fieldNames: Record<FieldName,string> = {
  shipper:'Shipper', consignee:'Consignee', notify_party:'Notify party',
  port_of_loading:'Port of loading', port_of_discharge:'Port of discharge',
  container_count:'Container count', gross_weight_kg:'Gross weight (kg)',
};
export const statuses: Record<string,string> = {
  PROCESSING:'Processing', REVIEW_REQUIRED:'Review required',
  FOLLOW_UP_REQUIRED:'Follow-up required', WAITING_FOR_RESPONSE:'Waiting for response',
  COMPLETED:'Completed', FAILED:'Failed',
};
export const reviewReasonLabels: Record<ReviewReason,string> = {
  wrong_doc_type:'wrong_doc_type', missing_attachment:'missing_attachment',
  unreadable:'unreadable', missing_value:'missing_value',
};

type RunLike = Run | RunSummary | null | undefined;
const resultOf = (run: RunLike) => run?.result as Run['result'] | ReportSummary | undefined;
export const reviewReasonOf = (run: RunLike) => resultOf(run)?.review_reason || null;
export const categoryOf = (run: RunLike):Category|null => {
  const result=resultOf(run);
  if(!result) return null;
  return result.category || ('predicted_category' in result ? result.predicted_category : result.classification?.predicted_category) || null;
};
export const statusOf = (run: RunLike) => {
  const result = resultOf(run);
  if (!result) return 'PROCESSING';
  if (result.processing_status === 'FAILED') return 'FAILED';
  if (result.routing_status === 'RESPONSE_RECEIVED') return 'REVIEW_REQUIRED';
  if (['FOLLOW_UP_REQUIRED','WAITING_FOR_RESPONSE','COMPLETED'].includes(result.routing_status)) return result.routing_status;
  if (!result.category && ('needs_category_review' in result ? result.needs_category_review : result.classification?.needs_review)) return 'REVIEW_REQUIRED';
  if (['MISMATCH','NEEDS_REVIEW'].includes(result.comparison_status || '')) return 'REVIEW_REQUIRED';
  return 'COMPLETED';
};
export const needsReview = (run: RunLike) => statusOf(run) === 'REVIEW_REQUIRED';
export const needsAttention = (run: RunLike) => needsReview(run) || ['FOLLOW_UP_REQUIRED','FAILED'].includes(statusOf(run));
export const displayStatus = (run: RunLike) => {
  const status=statusOf(run),result=resultOf(run);
  if (status==='REVIEW_REQUIRED' && result?.comparison_status==='MISMATCH') return 'Mismatch detected';
  if (status==='REVIEW_REQUIRED' && result?.comparison_status==='NEEDS_REVIEW') return 'Needs human review';
  return statuses[status] || status;
};
export const tone = (status: string) => status === 'COMPLETED' ? 'ok' : status === 'FAILED' ? 'danger' : status === 'WAITING_FOR_RESPONSE' || status === 'FOLLOW_UP_REQUIRED' ? 'confirmed' : status.includes('REVIEW') ? 'review' : '';
export const date = (value: string) => new Intl.DateTimeFormat('en-GB', {dateStyle:'medium',timeStyle:'short'}).format(new Date(value));

const shownValue = (item: ExtractedValue | null) => item?.raw_value?.trim() || 'Not available';
const shortPath = (path: string) => path.split(/[\\/]/).pop() || path;

function locationLabel(item: ExtractedValue) {
  const locator = item.source?.locator || {};
  if (typeof locator.line_start === 'number') {
    const end = locator.line_end === locator.line_start ? '' : `-${locator.line_end}`;
    return `Lines ${locator.line_start}${end}`;
  }
  if (typeof locator.page === 'number') return `Page ${locator.page}`;
  if (typeof locator.sheet === 'string') return `${locator.sheet}${locator.cell ? ` / ${locator.cell}` : ''}`;
  return 'Source location recorded';
}

function Evidence({item}: {item: ExtractedValue | null}) {
  if (!item) return null;
  return <>
    {item.source && <details className="evidence"><summary>View source <Icon name="down"/></summary><div className="evidence-panel"><div className="evidence-meta"><strong>{shortPath(item.source.attachment_path)}</strong><span>{locationLabel(item)}</span></div><blockquote>{item.source.quote}</blockquote></div></details>}
    {item.original_source && <details className="evidence"><summary>Original extraction <Icon name="down"/></summary><div className="evidence-panel"><blockquote>{item.original_source.quote}</blockquote></div></details>}
    {item.issue && <p className="field-issue">{item.issue}</p>}
    {item.candidates?.map((candidate,index) => <Evidence key={index} item={candidate}/>)}</>;
}

function decisionText(field: FieldComparison) {
  if (field.resolution === 'ACCEPTED_EQUIVALENT') return 'Accepted as equivalent';
  if (field.state === 'MATCH') return 'Aligned';
  if (field.state === 'UNKNOWN') return 'Cannot verify';
  return 'Different';
}

function fallbackAction(run: Run) {
  const result=run.result, category=categoryOf(run);
  if (category !== 'BL_COMPARISON') return category ? categoryActions[category] : 'Confirm the correct workflow for this email.';
  if (result.comparison_status === 'OK') return 'No document correction is required. Continue with the approved draft.';
  if (result.comparison_status === 'MISMATCH') return result.routing_source === 'human_review'
    ? 'Send the confirmed discrepancy to the sender and request a revised draft Bill of Lading.'
    : 'An operator must confirm the discrepancy before contacting the sender.';
  if (result.review_details.some(detail=>detail.startsWith('OCR produced different values'))) return 'OCR read different values in the two documents. Check the highlighted fields against the source pages.';
  return result.routing_source === 'human_review'
    ? 'The request is ready to send. Keep this case out of the review queue while waiting for a response.'
    : 'An operator must confirm what information is missing or unclear.';
}

function replyBody(run:Run) {
  const issues=(Object.entries(run.result.fields) as [FieldName, FieldComparison][]).filter(([,field])=>field.state !== 'MATCH');
  return [
    'Hello,', '', 'We reviewed the draft Bill of Lading against the Shipping Instruction.',
    ...(issues.length ? ['', 'Please review the following items:', ...issues.map(([name,field]) =>
      `- ${fieldNames[name]}: SI - ${shownValue(field.si)} | Draft BL - ${shownValue(field.bl)}`)] : []),
    '', 'Please confirm the missing information or provide a revised draft before finalisation.', '', 'Regards,', 'Shipping Operations',
  ].join('\n');
}

function CaseSummary({run,subject,sender}: {run:Run;subject:string;sender:string}) {
  const result=run.result, status=statusOf(run), category=categoryOf(run), action=result.next_action || fallbackAction(run);
  const reviewReason=reviewReasonOf(run);
  const caseId=result.case_tracking?.case_id || (['REVIEW_REQUIRED','FOLLOW_UP_REQUIRED','WAITING_FOR_RESPONSE'].includes(status) ? `SC-${run.email_id}` : '');
  const entries=Object.entries(result.fields) as [FieldName, FieldComparison][];
  const issues=entries.filter(([,field])=>field.state !== 'MATCH');
  const followUpReady=category==='BL_COMPARISON' && result.routing_status==='FOLLOW_UP_REQUIRED' && !!result.case_tracking;
  const to=(sender.match(/<([^>]+)>/)?.[1] || sender).trim();
  const mailboxName=to.split('@')[0].split(/[._-]+/).filter(Boolean).map(part=>part[0]?.toUpperCase()+part.slice(1)).join(' ');
  const displayName=(sender.match(/^([^<]+)</)?.[1] || mailboxName || to).trim();
  const marker=`[SC-${run.email_id}]`;
  const replySubject=`${marker} ${/^re:/i.test(subject) ? subject : `Re: ${subject}`}`;
  const gmailUrl=`https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(replySubject)}&body=${encodeURIComponent(replyBody(run))}`;
  function downloadReport() {
    const lines = ['ShipCheck discrepancy report', `Email: ${run.email_id}`, `Generated: ${date(run.created_at)}`, '', `Next action: ${action}`, '',
      ...issues.flatMap(([name,field])=>[fieldNames[name],`  SI: ${shownValue(field.si)}`,`  Draft BL: ${shownValue(field.bl)}`,`  Decision: ${decisionText(field)}`,''])];
    const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/plain;charset=utf-8'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download=`${run.email_id}-discrepancy-report.txt`;anchor.click();URL.revokeObjectURL(url);
  }
  const icon:'check'|'mail'|'warning'=status==='COMPLETED'?'check':['FOLLOW_UP_REQUIRED','WAITING_FOR_RESPONSE'].includes(status)?'mail':'warning';
  return <section className={`case-summary ${tone(status)}`}>
    <span className="case-summary-icon"><Icon name={icon}/></span>
    <div className="case-summary-copy"><span className="case-workflow">Category: {category ? categories[category] : 'Workflow confirmation required'}</span><h3>{displayStatus(run)}</h3><p>{action}</p>{reviewReason&&<span className="review-reason-tag">{reviewReasonLabels[reviewReason]}</span>}<small>{caseId ? `Case ${caseId} / ` : ''}{result.routing_source==='human_review'?'Human decision recorded':'Automated result'} / {date(run.created_at)}</small>{!!result.review_details.length&&<p className="case-note">Required: {result.review_details.join(' ')}</p>}</div>
    {followUpReady&&<div className="case-summary-actions"><a className="primary" href={gmailUrl} target="_blank" rel="noreferrer" title={`Contact ${displayName} in Gmail`}><Icon name="external"/>Contact sender</a><button type="button" className="secondary" onClick={downloadReport}><Icon name="download"/>Download report</button></div>}
  </section>;
}

export default function ReportView({run,subject,sender}: {run: Run | undefined;subject:string;sender:string}) {
  if (!run) return <div className="case-summary"><span className="case-summary-icon"><Icon name="warning"/></span><div className="case-summary-copy"><h3>Queued for processing</h3><p>The workflow and required action will appear when processing finishes.</p></div></div>;
  const result = run.result;
  const entries = Object.entries(result.fields) as [FieldName, FieldComparison][];
  return <>
    <CaseSummary run={run} subject={subject} sender={sender}/>
    {result.error&&<p role="alert" className="error-box">{result.error.message}</p>}
    {!!entries.length&&<section className="comparison-section"><div className="table-heading"><div><h3>SI and draft BL comparison</h3><p>The SI is the reference document.</p></div><span>{entries.filter(([,value])=>value.state==='MATCH').length} / 7 aligned</span></div><div className="table-wrap"><table><thead><tr><th>Field</th><th>SI reference</th><th>Draft BL</th><th>Result</th></tr></thead><tbody>{entries.map(([key,field])=><tr key={key} className={field.state.toLowerCase()}><td>{fieldNames[key]}</td>{(['si','bl'] as const).map(side=><td key={side}><span className="value">{shownValue(field[side])}</span><Evidence item={field[side]}/></td>)}<td><span className="field-state">{decisionText(field)}</span>{field.state==='MISMATCH'&&<small className="decision-note">Names, legal qualifiers and addresses are business content. Case, punctuation and line breaks are ignored.</small>}{field.resolution==='ACCEPTED_EQUIVALENT'&&<small className="decision-note">Accepted by a reviewer with an audit reason.</small>}</td></tr>)}</tbody></table></div></section>}
    {!!result.review_history.length&&<details className="audit"><summary>Decision history ({result.review_history.length}) <Icon name="down"/></summary><div className="audit-list">{result.review_history.map((entry,index)=><div key={index}><strong>{String(entry.decision||'Review recorded').replaceAll('_',' ')}</strong><p>{String(entry.reason||'No reason recorded')}</p><small>{String(entry.reviewer||'Operator')} / {entry.created_at?date(String(entry.created_at)):''}</small></div>)}</div></details>}
  </>;
}
