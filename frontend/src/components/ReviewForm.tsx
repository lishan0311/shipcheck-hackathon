import {useState} from 'react';
import {api} from '../api';
import type {Category, Correction, FieldComparison, FieldName, ReviewDecision, Run} from '../types';
import {categories, fieldNames} from './ReportView';

const decisions: {value:ReviewDecision;title:string;description:string;outcome:string}[] = [
  {value:'CONFIRM_DISCREPANCY',title:'Confirm discrepancy',description:'Both documents are readable and the draft BL needs to be corrected.',outcome:'Next: add the case to Follow-up required so a correction request can be sent.'},
  {value:'REQUEST_CLARIFICATION',title:'Request clarification',description:'A required value or document cannot be confirmed from the source attachments.',outcome:'Next: add the case to Follow-up required so the sender can provide the missing information.'},
  {value:'CORRECT_EXTRACTION',title:'Correct an extracted value',description:'The source document is clear, but OCR or extraction recorded the wrong value.',outcome:'Next: save the source correction and compare the documents again.'},
  {value:'ACCEPT_EQUIVALENT',title:'Accept equivalent wording',description:'Only use for equivalent party-name or address presentation differences.',outcome:'Next: no email is sent; the case completes automatically if all seven fields align.'},
];

function comparisonDecision(run:Run):ReviewDecision {
  return run.result.comparison_status==='MISMATCH' ? 'CONFIRM_DISCREPANCY' : 'REQUEST_CLARIFICATION';
}
function initialDecision(run:Run):ReviewDecision {
  return run.result.category==='BL_COMPARISON' ? comparisonDecision(run) : 'CONFIRM_CLASSIFICATION';
}

export default function ReviewForm({run,onSaved}:{run:Run;onSaved:()=>Promise<void>}) {
  const [category,setCategory]=useState<Category|''>(run.result.category||run.result.classification?.predicted_category||'');
  const [decision,setDecision]=useState<ReviewDecision>(initialDecision(run));
  const [reviewer,setReviewer]=useState('');
  const [reason,setReason]=useState('');
  const [field,setField]=useState<FieldName>('container_count');
  const [side,setSide]=useState<'si'|'bl'>('bl');
  const [value,setValue]=useState('');
  const [corrections,setCorrections]=useState<Correction[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const comparison=category==='BL_COMPARISON';
  const isMismatch=run.result.comparison_status==='MISMATCH';
  const comparedFields=Object.entries(run.result.fields).filter((entry):entry is [FieldName,FieldComparison]=>!!entry[1]);
  const unknownFields=comparedFields.filter(([,item])=>item.state==='UNKNOWN');
  const mismatchedFields=comparedFields.filter(([,item])=>item.state==='MISMATCH');
  const equivalentAllowed=!unknownFields.length&&mismatchedFields.length>0&&mismatchedFields.every(([name])=>['shipper','consignee','notify_party'].includes(name));
  const applicableDecisions=comparison ? decisions.filter(option => isMismatch
    ? ['CONFIRM_DISCREPANCY','CORRECT_EXTRACTION','ACCEPT_EQUIVALENT'].includes(option.value)
    : ['REQUEST_CLARIFICATION','CORRECT_EXTRACTION'].includes(option.value)) : [];
  const selectedOption=applicableDecisions.find(option=>option.value===decision);
  function disabledDecision(value:ReviewDecision) {
    if(value==='CONFIRM_DISCREPANCY') return !mismatchedFields.length;
    if(value==='ACCEPT_EQUIVALENT') return !equivalentAllowed;
    return false;
  }
  async function submit(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError('');
    try {await api.review(run.email_id,{base_run_id:run.run_id,reviewer,reason,category:category||null,decision:comparison?decision:'CONFIRM_CLASSIFICATION',corrections:decision==='CORRECT_EXTRACTION'?corrections:[]});await onSaved();}
    catch(cause){setError(cause instanceof Error?cause.message:'The decision could not be saved.');}
    finally{setBusy(false);}
  }
  function addCorrection(){if(!value.trim())return;setCorrections([...corrections.filter(item=>item.field!==field||item.side!==side),{field,side,raw_value:value.trim()}]);setValue('');}
  const heading=comparison ? isMismatch ? 'Confirm the detected discrepancy' : 'Resolve the unreadable or incomplete evidence' : 'Confirm the email category';
  const guidance=comparison ? isMismatch ? 'ShipCheck found a difference in readable SI and draft BL values. Confirm it, correct an extraction error, or accept an equivalent party presentation.' : 'ShipCheck cannot safely decide from the attachments. Request missing information or correct a verified extraction.' : 'Choose the correct workflow. Only BL comparison requests proceed to document checking.';
  return <form onSubmit={submit} className="review-form">
    <div className="review-form-heading"><span className="section-kicker">HUMAN REVIEW</span><h3>{heading}</h3><p>{guidance}</p></div>
    <fieldset disabled={busy}>
      <div className="review-grid"><label>Reviewed by<input required maxLength={100} value={reviewer} onChange={event=>setReviewer(event.target.value)} placeholder="Enter your name"/></label><label>Email category<select required value={category} onChange={event=>{const next=event.target.value as Category;setCategory(next);setCorrections([]);setDecision(next==='BL_COMPARISON'?comparisonDecision(run):'CONFIRM_CLASSIFICATION');}}><option value="">Choose a category</option>{Object.entries(categories).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></div>
      {comparison&&<div className="decision-options"><span className="form-label">Decision</span>{applicableDecisions.map(option=>{const disabled=disabledDecision(option.value);return <label className={`decision-option ${decision===option.value?'selected':''} ${disabled?'disabled':''}`} key={option.value}><input disabled={disabled} type="radio" name="decision" value={option.value} checked={decision===option.value} onChange={()=>{setDecision(option.value);setCorrections([]);}}/><span><strong>{option.title}</strong><small>{option.description}</small><small className="decision-outcome">{disabled&&option.value==='ACCEPT_EQUIVALENT'?'Unavailable for this case':option.outcome}</small></span></label>;})}</div>}
      {comparison&&decision==='CORRECT_EXTRACTION'&&<div className="correction-box"><div><strong>Correct the extracted value</strong><p>Use the exact value visible in the source. This does not create a revised SI or BL.</p></div><div className="correction-grid"><select aria-label="Field to correct" value={field} onChange={event=>setField(event.target.value as FieldName)}>{Object.entries(fieldNames).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select><select aria-label="Document to correct" value={side} onChange={event=>setSide(event.target.value as 'si'|'bl')}><option value="si">SI reference</option><option value="bl">Draft BL</option></select><input aria-label="Corrected extraction" placeholder="Value exactly as shown" value={value} onChange={event=>setValue(event.target.value)}/><button type="button" className="secondary" onClick={addCorrection}>Add correction</button></div>{corrections.map(correction=><div className="correction-item" key={`${correction.side}-${correction.field}`}><span>{correction.side.toUpperCase()} / {fieldNames[correction.field]}: {correction.raw_value}</span><button type="button" onClick={()=>setCorrections(corrections.filter(item=>item!==correction))}>Remove</button></div>)}</div>}
      <label className="review-reason">Review note<textarea required minLength={3} maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)} placeholder="Summarise what you checked."/></label>
      {error&&<p role="alert" className="error-box">{error}</p>}
      <div className="review-footer"><p>{comparison ? selectedOption?.outcome : 'Next: save the confirmed category and route the email to its normal workflow.'}</p><button className="primary" type="submit">{busy?'Saving...':'Save decision'}</button></div>
    </fieldset>
  </form>;
}
