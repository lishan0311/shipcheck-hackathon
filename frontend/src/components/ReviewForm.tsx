import {useState} from 'react';
import {api} from '../api';
import type {Category, Correction, FieldComparison, FieldName, ReviewDecision, Run} from '../types';
import {categories, fieldNames} from './ReportView';

const decisions: {value:ReviewDecision;title:string;description:string;outcome:string}[] = [
  {value:'CONFIRM_DISCREPANCY',title:'The documents really differ',description:'Use this when ShipCheck read both files correctly and the draft BL must be changed.',outcome:'Next: create a case and send a correction request.'},
  {value:'REQUEST_CLARIFICATION',title:'Information is missing or unclear',description:'Use this when a required value is blank, unreadable or cannot be confirmed from the attachments.',outcome:'Next: create a case and ask the sender for the missing information.'},
  {value:'CORRECT_EXTRACTION',title:'ShipCheck read a value incorrectly',description:'Use this when the source file is clear but OCR or extraction captured the wrong value.',outcome:'Next: enter the source value and run the comparison again.'},
  {value:'ACCEPT_EQUIVALENT',title:'Different wording, same meaning',description:'Use this only for equivalent party names or address formatting. Counts, weights and ports cannot be waived.',outcome:'Next: approve the equivalent values and complete automatically if all seven fields align.'},
];

function comparisonDecision(run:Run):ReviewDecision {
  if (run.result.comparison_status==='MISMATCH') return 'CONFIRM_DISCREPANCY';
  if (run.result.comparison_status==='NEEDS_REVIEW') return 'REQUEST_CLARIFICATION';
  return 'CORRECT_EXTRACTION';
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
  const comparedFields=Object.entries(run.result.fields).filter((entry):entry is [FieldName,FieldComparison]=>!!entry[1]);
  const unknownFields=comparedFields.filter(([,item])=>item.state==='UNKNOWN');
  const mismatchedFields=comparedFields.filter(([,item])=>item.state==='MISMATCH');
  const equivalentAllowed=!unknownFields.length&&mismatchedFields.length>0&&mismatchedFields.every(([name])=>['shipper','consignee','notify_party'].includes(name));
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
  return <form onSubmit={submit} className="review-form">
    <div className="review-form-heading"><span className="section-kicker">HUMAN REVIEW</span><h3>Review this case</h3><p>Choose the outcome that matches the source evidence. Your decision is recorded in the case history.</p></div>
    <fieldset disabled={busy}>
      <div className="review-grid"><label>Reviewed by<input required maxLength={100} value={reviewer} onChange={event=>setReviewer(event.target.value)} placeholder="Enter your name"/></label><label>Email category<select required value={category} onChange={event=>{const next=event.target.value as Category;setCategory(next);setCorrections([]);setDecision(next==='BL_COMPARISON'?comparisonDecision(run):'CONFIRM_CLASSIFICATION');}}><option value="">Choose a category</option>{Object.entries(categories).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></div>
      {comparison&&<div className="decision-options"><span className="form-label">Decision</span>{decisions.map(option=>{const disabled=disabledDecision(option.value);return <label className={`decision-option ${decision===option.value?'selected':''} ${disabled?'disabled':''}`} key={option.value}><input disabled={disabled} type="radio" name="decision" value={option.value} checked={decision===option.value} onChange={()=>{setDecision(option.value);setCorrections([]);}}/><span><strong>{option.title}</strong><small>{option.description}</small><small className="decision-outcome">{disabled&&option.value==='ACCEPT_EQUIVALENT'?'Unavailable for this case':option.outcome}</small></span></label>;})}</div>}
      {comparison&&decision==='CORRECT_EXTRACTION'&&<div className="correction-box"><div><strong>Correct the extracted value</strong><p>Use the exact value visible in the source. This does not create a revised SI or BL.</p></div><div className="correction-grid"><select aria-label="Field to correct" value={field} onChange={event=>setField(event.target.value as FieldName)}>{Object.entries(fieldNames).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select><select aria-label="Document to correct" value={side} onChange={event=>setSide(event.target.value as 'si'|'bl')}><option value="si">SI reference</option><option value="bl">Draft BL</option></select><input aria-label="Corrected extraction" placeholder="Value exactly as shown" value={value} onChange={event=>setValue(event.target.value)}/><button type="button" className="secondary" onClick={addCorrection}>Add correction</button></div>{corrections.map(correction=><div className="correction-item" key={`${correction.side}-${correction.field}`}><span>{correction.side.toUpperCase()} / {fieldNames[correction.field]}: {correction.raw_value}</span><button type="button" onClick={()=>setCorrections(corrections.filter(item=>item!==correction))}>Remove</button></div>)}</div>}
      <label className="review-reason">Review note<textarea required minLength={3} maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)} placeholder="Summarise what you checked."/></label>
      {error&&<p role="alert" className="error-box">{error}</p>}
      <div className="review-footer"><p>Cases that need sender input will move to Follow-up required.</p><button className="primary" type="submit">{busy?'Saving...':'Save decision'}</button></div>
    </fieldset>
  </form>;
}
