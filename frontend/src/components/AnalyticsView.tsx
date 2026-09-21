import {useEffect, useMemo, useState} from 'react';
import {api} from '../api';
import type {Analytics, ValidationMetrics} from '../types';
import {categories, fieldNames, reviewReasonLabels} from './ReportView';

const outcomeLabels: Record<string,string> = {OK:'OK', MISMATCH:'Mismatches detected', NEEDS_REVIEW:'Needs human review', UNPROCESSED:'Awaiting processing'};
const outcomeColors: Record<string,string> = {OK:'#16815a', MISMATCH:'#c33b47', NEEDS_REVIEW:'#c98212', UNPROCESSED:'#82909d'};
const reasonDescriptions: Record<string,string> = {
  wrong_doc_type:'Attachment is not an SI or draft BL.',
  missing_attachment:'The comparison request does not include both documents.',
  unreadable:'The attachment cannot be read with enough confidence.',
  missing_value:'A required field is blank or cannot be confirmed.',
};
const percent = (value?:number) => typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—';

function Donut({values}: {values:{key:string;value:number}[]}) {
  const total=values.reduce((sum,item)=>sum+item.value,0) || 1;
  let offset=0;
  return <div className="analytics-donut" role="img" aria-label="Email processing outcome distribution"><svg viewBox="0 0 120 120"><circle className="donut-track" cx="60" cy="60" r="46"/>{values.map(item=>{const dash=item.value/total*289;const element=<circle key={item.key} className="donut-segment" cx="60" cy="60" r="46" stroke={outcomeColors[item.key]} strokeDasharray={`${dash} ${289-dash}`} strokeDashoffset={-offset}/>;offset+=dash;return element;})}</svg><div><strong>{total}</strong><span>emails</span></div></div>;
}

function BarList({items,colors}:{items:{label:string;value:number;note?:string}[];colors?:string[]}) {
  const max=Math.max(...items.map(item=>item.value),1);
  return <div className="bar-list">{items.map((item,index)=><div className="bar-row" key={item.label}><div className="bar-label"><span>{item.label}</span><strong>{item.value}</strong></div><div className="bar-track"><i style={{width:`${item.value/max*100}%`,background:colors?.[index]}}/></div>{item.note&&<small>{item.note}</small>}</div>)}</div>;
}

function ValidationCard({title,value}:{title:string;value:ValidationMetrics}) {
  if(!value.available) return <section className="analytics-card validation-card"><div><span className="section-kicker">VALIDATION</span><h3>{title}</h3><p>No frozen organizer-scorer result is available in this deployment.</p></div></section>;
  return <section className="analytics-card validation-card"><div><span className="section-kicker">VALIDATION / ORGANIZER SCORER</span><h3>{title}</h3><p>{value.email_count} emails / {value.source || 'Frozen evaluation artifact'}</p></div><div className="validation-grid"><div><span>Category Macro-F1</span><strong>{percent(value.pipeline_macro_f1)}</strong><small>Rules + model</small></div><div><span>Field F1</span><strong>{percent(value.field_f1)}</strong><small>Seven document fields</small></div><div><span>End-to-end</span><strong>{percent(value.end_to_end)}</strong><small>Fully correct cases</small></div><div><span>Review P / R</span><strong>{percent(value.review_precision)} / {percent(value.review_recall)}</strong><small>Escalation decisions</small></div><div><span>Organizer score</span><strong>{percent(value.final_score)}</strong><small>Weighted score</small></div><div><span>Model-only Macro-F1</span><strong>{percent(value.model_macro_f1)}</strong><small>TF-IDF + logistic regression</small></div></div><p className="validation-note">Produced offline with the organizer-compatible scorer. The runtime pipeline never reads evaluation labels; results are not a claim about unrestricted Gmail traffic.</p></section>;
}

function ReliabilityCard({items}:{items:{label:string;value:number;note?:string}[]}) {
  const total=items.reduce((sum,item)=>sum+item.value,0);
  return <section className="analytics-card"><span className="section-kicker">RELIABILITY</span><h3>Human review reasons</h3>{total ? <BarList items={items} colors={items.map(() => '#c98212')}/> : <div className="reliability-empty"><strong>No reliability exceptions</strong><p>None of the current saved reports required review for wrong document type, missing attachment, unreadable input, or missing value.</p></div>}</section>;
}

export default function AnalyticsView() {
  const [data,setData]=useState<Analytics|null>(null),[error,setError]=useState('');
  useEffect(()=>{const controller=new AbortController();api.analytics().then(setData).catch(cause=>{if(cause.name!=='AbortError')setError(cause.message);});return()=>controller.abort();},[]);
  const outcomeItems=useMemo(()=>data?Object.keys(outcomeLabels).map(key=>({key,value:data.outcomes[key as keyof Analytics['outcomes']]||0})):[],[data]);
  if(error) return <section className="analytics-empty"><h2>Analytics unavailable</h2><p>{error}</p></section>;
  if(!data) return <section className="analytics-empty"><h2>Loading analytics…</h2><p>Reading saved processing reports.</p></section>;
  const categoryItems=Object.entries(categories).map(([key,label])=>({label,value:data.categories[key]||0}));
  const fieldItems=Object.entries(fieldNames).map(([key,label])=>({label,value:data.mismatch_fields[key]||0})).sort((a,b)=>b.value-a.value);
  const reasonItems=Object.keys(reviewReasonLabels).map(key=>({label:reviewReasonLabels[key as keyof typeof reviewReasonLabels],value:data.review_reasons[key as keyof Analytics['review_reasons']]||0,note:reasonDescriptions[key]}));
  return <section className="analytics-page"><div className="analytics-heading"><div><span className="section-kicker">OPERATIONS ANALYTICS</span><h2>Inbox quality and automation</h2><p>Live saved reports, plus clearly labelled offline validation results.</p></div><span className={`analytics-ai ${data.ai_assistant.enabled?'active':''}`}>{data.ai_assistant.enabled?`Gemini active · ${data.ai_assistant.requests_used}/${data.ai_assistant.request_limit} calls`:'Gemini fallback off'}</span></div>
    <div className="analytics-overview"><section className="analytics-card outcome-card"><div className="outcome-visual"><Donut values={outcomeItems}/><span>ALL INBOX EMAILS</span></div><div className="outcome-details"><div><h3>Processing outcomes</h3><p>{data.processed_emails} of {data.total_emails} inbox emails have a saved report.</p></div><div className="outcome-legend">{outcomeItems.map(item=><span key={item.key}><i style={{background:outcomeColors[item.key]}}/>{outcomeLabels[item.key]} <strong>{item.value}</strong></span>)}</div></div></section><section className="analytics-card"><span className="section-kicker">WORKFLOW</span><h3>Case status</h3><BarList items={Object.entries(data.workflows).map(([label,value])=>({label:label.replaceAll('_',' ').toLowerCase(),value})).sort((a,b)=>b.value-a.value)} colors={['#2e6f9f']}/></section></div>
    <div className="analytics-grid"><section className="analytics-card"><span className="section-kicker">CLASSIFICATION</span><h3>Email categories</h3><BarList items={categoryItems} colors={['#0b5cab']}/></section><section className="analytics-card"><span className="section-kicker">DOCUMENT CHECKS</span><h3>Mismatches by field</h3><BarList items={fieldItems} colors={['#c33b47']}/></section><ReliabilityCard items={reasonItems}/></div>
    <div className="analytics-validation"><ValidationCard title="Supplied 520-email dataset" value={data.validation.supplied_dataset}/><ValidationCard title="Independent seed-73 holdout" value={data.validation.independent_holdout}/></div>
  </section>;
}
