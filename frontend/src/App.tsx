import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router';
import { api, ApiError } from './api';
import type { BatchStatus, Category, EmailDetail, EmailSummary, Health, MailboxStatus } from './types';
import ReportView, { categories, categoryOf, date, displayStatus, needsAttention, needsReview, reviewReasonLabels, reviewReasonOf, statusOf, tone } from './components/ReportView';
import ReviewForm from './components/ReviewForm';
import Icon from './components/Icon';
import AnalyticsView from './components/AnalyticsView';
const extension = (path: string) => path.split('.').pop()?.toUpperCase() || 'FILE';
const filename = (path: string) => path.split(/[\\/]/).pop() || path;
function Documents({
  detail
}: {
  detail: EmailDetail;
}) {
  const [error, setError] = useState('');
  async function download(emailId: string, index: number, path: string) {
    setError('');
    try {
      await api.download(emailId, index, filename(path));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Download failed.');
    }
  }
  function messageGroup(emailId: string, label: string, body: string, documents: EmailDetail['documents'], meta: string) {
    return <div className="message-group" key={emailId}><div className="message-group-label"><strong>{label}</strong><span>{meta}</span></div><details className="source-section"><summary><span className="file-type mail"><Icon name="mail" /></span><span className="source-name">Email message<small>{emailId}</small></span><Icon name="down" className="chevron" /></summary><pre>{body}</pre></details>{documents.map((document, index) => <details className="source-section" key={document.path}><summary><span className="file-type"><Icon name="document" /></span><span className="source-name">{filename(document.path)}<small>{extension(document.path)} / {document.status === 'READ' ? 'Ready to inspect' : document.status}</small></span><Icon name="down" className="chevron" /></summary><div className="document-body"><div className="document-actions"><button type="button" onClick={() => download(emailId, index, document.path)}><Icon name="download" />Download attachment</button><span>{document.path}</span></div><pre>{document.text ?? document.error}</pre></div></details>)}</div>;
  }
  const responses = [...detail.case_messages].reverse();
  return <section className="sources">
    <div className="section-title"><div><h3>Case messages and attachments</h3><p>The newest response and its attachments appear first. Original evidence remains available below.</p></div></div>
    {error && <p className="error-box">{error}</p>}
    {responses.map((message, index) => messageGroup(message.email_id, index === 0 ? 'Latest response' : 'Earlier response', message.body, message.documents, `${message.from} / ${message.received_at ? date(message.received_at) : 'Received via Gmail'}`))}
    {messageGroup(detail.email.email_id, 'Original request', detail.email.body, detail.documents, detail.email.from)}
  </section>;
}
function Detail({
  refresh,
  reviewing
}: {
  refresh: () => Promise<void>;
  reviewing: boolean;
}) {
  const {
    emailId
  } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<EmailDetail | null>(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [sendingFollowUp, setSendingFollowUp] = useState(false),
    [runId, setRunId] = useState('');
  const reload = useCallback(async () => {
    if (!emailId) return;
    const value = await api.detail(emailId);
    setDetail(value);
    setRunId(value.history[0]?.run_id || '');
  }, [emailId]);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError('');
    if (emailId) api.detail(emailId, controller.signal).then(value => {
      setDetail(value);
      setRunId(value.history[0]?.run_id || '');
    }).catch(cause => {
      if (cause.name !== 'AbortError') setError(cause.message);
    });
    return () => controller.abort();
  }, [emailId]);
  async function process() {
    if (!emailId) return;
    setBusy(true);
    setError('');
    try {
      await api.process(emailId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Processing failed.');
    } finally {
      try {
        await reload();
        await refresh();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Could not reload results.');
      }
      setBusy(false);
    }
  }
  async function sendFollowUp() {
    if (!emailId) return false;
    setSendingFollowUp(true);
    setError('');
    try {
      const response=await api.sendFollowUps([emailId]);
      if(response.sent!==1) throw new Error(response.results[0]?.error||'Gmail could not send this follow-up.');
      await reload();
      await refresh();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The follow-up could not be sent.');
      return false;
    } finally {
      setSendingFollowUp(false);
    }
  }
  const run = detail?.history.find(item => item.run_id === runId);
  const status = statusOf(run);
  const responseReceived = run?.result.routing_status === 'RESPONSE_RECEIVED';
  const reviewRequired = needsReview(run);
  return <section className="detail" aria-busy={busy}>{error && <p role="alert" className="error-box">{error}</p>}{!detail ? <div className="empty">{error ? 'Select an email to retry.' : 'Loading email…'}</div> : <>
    <div className="detail-topline"><span className="email-reference">{detail.email.email_id}</span><span className={`badge ${tone(statusOf(run))}`}>{displayStatus(run)}</span></div>
    <h2 className="subject">{detail.email.subject || '(No subject)'}</h2><div className="sender-row"><span className="sender-avatar">{detail.email.from[0]?.toUpperCase()}</span><div><span className="sender-label">FROM</span><p>{detail.email.from}</p></div></div>
    <div className="action-bar"><label className="history-picker">Report version<select disabled={!detail.history.length || busy} value={runId} onChange={event => setRunId(event.target.value)}>{!detail.history.length && <option>Processing</option>}{detail.history.map((item, index) => <option key={item.run_id} value={item.run_id}>{index === 0 ? 'Latest / ' : ''}{date(item.created_at)}</option>)}</select></label><div className="action-buttons">{reviewing && <Link to={`/emails/${emailId}`} className="secondary"><Icon name="left" />Back to report</Link>}{!reviewing && run && reviewRequired && <Link to={`/review/${emailId}`} className="primary"><Icon name="review" />{responseReceived ? 'Review response' : 'Review case'}</Link>}<button disabled={busy} onClick={process} className="secondary"><Icon name="refresh" />{busy ? 'Processing...' : 'Reprocess'}</button></div></div>
    <ReportView run={run} sender={detail.email.from} onSendFollowUp={sendFollowUp} sendingFollowUp={sendingFollowUp} />{reviewing && run && status === 'REVIEW_REQUIRED' && !responseReceived && (run === detail.history[0] ? <ReviewForm key={run.run_id} run={run} onSaved={async () => {
        await reload();
        await refresh();
        navigate(`/emails/${emailId}`);
      }} /> : <p className="review-warning">Select the latest report version before saving a review.</p>)}
    <Documents detail={detail} />
  </>}</section>;
}
function Workspace({
  emails,
  refresh,
  reviewOnly = false,
  archived = false,
  selectedIds,
  toggleSelected
}: {
  emails: EmailSummary[];
  refresh: () => Promise<void>;
  reviewOnly?: boolean;
  archived?: boolean;
  selectedIds: Set<string>;
  toggleSelected: (emailId: string) => void;
}) {
  const [query, setQuery] = useState(''),
    [category, setCategory] = useState('all'),
    [result, setResult] = useState('all'),
    [page, setPage] = useState(0);
  const [confirming, setConfirming] = useState(false),
    [sending, setSending] = useState(false),
    [followUpMessage, setFollowUpMessage] = useState(''),
    [followUpError, setFollowUpError] = useState('');
  const location = useLocation();
  const readyFollowUps = useMemo(() => emails.filter(email => statusOf(email.latest) === 'FOLLOW_UP_REQUIRED'), [emails]);
  const filtered = useMemo(() => emails.filter(email => {
    const status = statusOf(email.latest),
      emailCategory = categoryOf(email.latest);
    const matchesText = `${email.email_id} ${email.subject} ${email.from}`.toLowerCase().includes(query.toLowerCase());
    const matchesCategory = category === 'all' || emailCategory === category;
    const comparisonStatus = email.latest?.result.comparison_status;
    const matchesResult = result === 'all' || result === 'mismatch' && comparisonStatus === 'MISMATCH' || result === 'needs-review' && comparisonStatus === 'NEEDS_REVIEW' || result === 'followup' && status === 'FOLLOW_UP_REQUIRED' || result === 'waiting' && status === 'WAITING_FOR_RESPONSE' || result === 'completed' && status === 'COMPLETED' || result === 'failed' && status === 'FAILED' || result === 'processing' && status === 'PROCESSING';
    return matchesText && matchesCategory && matchesResult && (!reviewOnly || needsAttention(email.latest));
  }), [emails, query, category, result, reviewOnly]);
  const pages = Math.max(1, Math.ceil(filtered.length / 30)),
    current = Math.min(page, pages - 1);
  const reset = (setter: (value: string) => void) => (event: React.ChangeEvent<HTMLSelectElement>) => {
    setter(event.target.value);
    setPage(0);
  };
  async function sendAllFollowUps() {
    setSending(true);
    setFollowUpError('');
    try {
      const response = await api.sendFollowUps(readyFollowUps.map(email => email.email_id));
      setFollowUpMessage(`${response.sent} follow-up${response.sent === 1 ? '' : 's'} sent${response.failed ? `; ${response.failed} failed` : ''}.`);
      setConfirming(false);
      await refresh();
    } catch (cause) {
      setFollowUpError(cause instanceof Error ? cause.message : 'Follow-ups could not be sent.');
    } finally {
      setSending(false);
    }
  }
  return <div className="workbench"><aside className="inbox"><div className="inbox-heading"><div><h2>{reviewOnly ? 'Action queue' : archived ? 'Archived emails' : 'Email inbox'}</h2><p>{reviewOnly ? 'Review decisions and sender follow-ups' : archived ? 'Hidden from the active inbox. Gmail and reports stay intact.' : 'Automatically classified and routed'}</p></div><span className="count-chip">{filtered.length}</span></div>{reviewOnly && <div className="bulk-follow-up"><div><strong>Follow-up required</strong><span>{readyFollowUps.length} confirmed case{readyFollowUps.length === 1 ? '' : 's'}</span></div><button className="primary" disabled={!readyFollowUps.length} onClick={() => {
          setConfirming(true);
          setFollowUpMessage('');
          setFollowUpError('');
        }}><Icon name="mail" />Send all follow-ups ({readyFollowUps.length})</button></div>}{followUpMessage && <p className="bulk-success">{followUpMessage}</p>}<div className="inbox-tools"><div className="search-box"><Icon name="search" /><input type="search" aria-label="Search emails" placeholder="Search sender, subject or ID" value={query} onChange={event => {
            setQuery(event.target.value);
            setPage(0);
          }} /></div><div className="filter-grid"><select aria-label="Filter by category" value={category} onChange={reset(setCategory)}><option value="all">All categories</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Filter by work status" value={result} onChange={reset(setResult)}><option value="all">{reviewOnly ? 'All actions' : 'All work statuses'}</option><option value="mismatch">Mismatch detected</option><option value="needs-review">Needs human review</option><option value="followup">Follow-up required</option>{reviewOnly ? <option value="failed">Processing failed</option> : <><option value="waiting">Waiting for response</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="processing">Processing</option></>}</select></div></div><div className="email-list">{filtered.slice(current * 30, current * 30 + 30).map(email => {
          const status = statusOf(email.latest),
            emailCategory = categoryOf(email.latest),
            hasCase = ['REVIEW_REQUIRED', 'FOLLOW_UP_REQUIRED', 'WAITING_FOR_RESPONSE'].includes(status);
          return <div className="selectable-email-row" key={email.email_id}>{!reviewOnly && <label className="email-select"><input type="checkbox" aria-label={`Select ${email.subject}`} checked={selectedIds.has(email.email_id)} onChange={() => toggleSelected(email.email_id)} /></label>}<Link className={`email-row ${location.pathname.endsWith('/' + email.email_id) ? 'active' : ''}`} to={`/${reviewOnly ? 'review' : archived ? 'archive' : 'emails'}/${email.email_id}`}><span className="email-meta"><span className="email-reference-small">{hasCase ? `Case SC-${email.email_id}` : email.email_id}</span><span className={`email-status ${tone(status)}`}>{displayStatus(email.latest)}</span></span><strong>{email.subject}</strong><span className="category-label">Category: {emailCategory ? categories[emailCategory] : 'Awaiting classification'}</span><span className="email-from">{email.from} / {email.attachment_count} attachment{email.attachment_count === 1 ? '' : 's'}</span></Link></div>;
        })}{!filtered.length && <p className="empty small">No emails match these filters.</p>}</div><div className="paging"><button disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page"><Icon name="left" /></button><span>Page {current + 1} of {pages}</span><button disabled={current === pages - 1} onClick={() => setPage(current + 1)} aria-label="Next page"><Icon name="right" /></button></div></aside><Routes><Route path=":emailId" element={<Detail refresh={refresh} reviewing={reviewOnly} />} /><Route path="*" element={<section className="detail empty"><Icon name="mail" className="empty-symbol" /><h2>{reviewOnly ? 'Choose a case to resolve' : archived ? 'Choose an archived email' : 'Choose an email'}</h2><p>The category, work status and processing result will appear here.</p></section>} /></Routes>{confirming && <div className="modal-backdrop" role="presentation"><section className="follow-up-modal" role="dialog" aria-modal="true" aria-labelledby="follow-up-title"><span className="modal-icon"><Icon name="mail" /></span><h2 id="follow-up-title">Send {readyFollowUps.length} reviewed follow-up{readyFollowUps.length === 1 ? '' : 's'}?</h2><p>Each recipient receives one email with its Case ID and confirmed document issues. Successful cases move to Waiting for response.</p><div className="follow-up-preview">{readyFollowUps.slice(0, 6).map(email => <div key={email.email_id}><strong>SC-{email.email_id}</strong><span>{email.from}</span></div>)}{readyFollowUps.length > 6 && <small>+ {readyFollowUps.length - 6} more cases</small>}</div>{followUpError && <p className="error-box">{followUpError}</p>}<div className="modal-actions"><button className="secondary" disabled={sending} onClick={() => setConfirming(false)}>Cancel</button><button className="primary" disabled={sending} onClick={sendAllFollowUps}><Icon name="mail" />{sending ? 'Sending...' : `Send ${readyFollowUps.length} emails`}</button></div></section></div>}</div>;
}
function BatchBanner({ batch }: { batch: BatchStatus | null }) {
  if (!batch?.running) return null;
  const done = batch.completed + batch.failed + batch.skipped,
    percentage = batch.total ? Math.round(done / batch.total * 100) : 0;
  return <div className="sync-banner" role="status" aria-live="polite"><div><strong>Processing inbox - {done} of {batch.total}</strong><p>{batch.current_email_id ? `Checking ${batch.current_email_id}` : 'Preparing the next email'}</p></div><span>{percentage}%</span><div className="progress"><i style={{
        width: `${percentage}%`
      }} /></div></div>;
}
export default function App() {
  const [emails, setEmails] = useState<EmailSummary[]>([]),
    [archivedEmails, setArchivedEmails] = useState<EmailSummary[]>([]),
    [health, setHealth] = useState<Health | null>(null),
    [batch, setBatch] = useState<BatchStatus | null>(null),
    [mailbox, setMailbox] = useState<MailboxStatus | null>(null),
    [mailSyncing, setMailSyncing] = useState(false),
    [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set()),
    [error, setError] = useState(''),
    [locked, setLocked] = useState(false),
    [token, setToken] = useState(''),
    [navOpen, setNavOpen] = useState(() => localStorage.getItem('shipcheck-nav') !== 'closed');
  const navigate = useNavigate(),
    location = useLocation();
  const refresh = useCallback(async () => {
    const [data, archived] = await Promise.all([api.inbox(), api.archived()]);
    setEmails(data.emails);
    setArchivedEmails(archived.emails);
    setLocked(false);
    const unreadable = data.errors.length + archived.errors.length;
    if (unreadable) setError(`${unreadable} email files could not be read.`);
  }, []);
  const poll = useCallback(async () => {
    try {
      const [state, mailState] = await Promise.all([api.batch(), api.mailbox()]);
      setBatch(state);
      setMailbox(mailState);
      await refresh();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) setLocked(true);
    }
  }, [refresh]);
  useEffect(() => {
    Promise.all([api.health(), api.batch(), api.mailbox()]).then(([healthValue, batchValue, mailValue]) => {
      setHealth(healthValue);
      setBatch(batchValue);
      setMailbox(mailValue);
    }).catch(cause => setError(cause.message));
    refresh().catch(cause => {
      if (cause instanceof ApiError && cause.status === 401) setLocked(true);else setError(cause.message);
    });
    const timer = window.setInterval(poll, 5000);
    return () => window.clearInterval(timer);
  }, [refresh, poll]);
  async function startBatch(force = false, emailIds?: string[]) {
    setError('');
    try {
      setBatch(await api.startBatch(force, emailIds));
      if (emailIds?.length) setSelectedIds(new Set());
      window.setTimeout(poll, 300);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not start processing.');
    }
  }
  async function syncMailbox() {
    setMailSyncing(true);
    setError('');
    try {
      setMailbox(await api.syncMailbox());
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Mailbox synchronization failed.');
    } finally {
      setMailSyncing(false);
    }
  }
  const reviewPage = location.pathname.startsWith('/review');
  const analyticsPage = location.pathname.startsWith('/analytics');
  const archivePage = location.pathname.startsWith('/archive');
  const attentionCount = emails.filter(email => needsAttention(email.latest)).length;
  const okCount = emails.filter(email => {
    const result = email.latest?.result;
    return result?.processing_status === 'COMPLETED' && !!result.category && !['MISMATCH', 'NEEDS_REVIEW'].includes(result.comparison_status || '');
  }).length;
  const mismatchCount = emails.filter(email => email.latest?.result.comparison_status === 'MISMATCH').length;
  const needsReviewCount = emails.filter(email => email.latest?.result.comparison_status === 'NEEDS_REVIEW').length;
  const unprocessedCount = emails.filter(email => !email.latest).length;
  const aiStatus = health?.ai_assistant;
  const aiLabel = aiStatus?.enabled ? `Gemini fallback / ${aiStatus.model}` : aiStatus?.configured ? 'Gemini fallback paused' : 'Gemini fallback off';
  useEffect(() => { setSelectedIds(new Set()); }, [archivePage]);
  async function moveSelected(toArchive: boolean) {
    if (!selectedIds.size) return;
    setError('');
    try {
      await (toArchive ? api.archive : api.restore)([...selectedIds]);
      setSelectedIds(new Set());
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update the archive.');
    }
  }
  function toggleNav() {
    setNavOpen(value => {
      localStorage.setItem('shipcheck-nav', value ? 'closed' : 'open');
      return !value;
    });
  }
  const toggleSelected = (emailId: string) => setSelectedIds(currentSelection => {
    const next = new Set(currentSelection);
    next.has(emailId) ? next.delete(emailId) : next.add(emailId);
    return next;
  });
  const inboxPage = !reviewPage && !analyticsPage && !archivePage;
  return <>
    <aside className={`rail ${navOpen ? 'expanded' : ''}`} aria-label="Workspace navigation">
      <div className="rail-brand"><Link className="brand" to="/inbox" aria-label="ShipCheck home">SC</Link>{navOpen && <div><strong>ShipCheck</strong><small>Shipping document control</small></div>}</div>
      <button className="rail-toggle" onClick={toggleNav} aria-label={navOpen ? 'Collapse sidebar' : 'Expand sidebar'}><Icon name={navOpen ? 'left' : 'right'} /></button>
      <nav className="rail-links">
        <span className="rail-section-label">{navOpen ? 'WORKSPACE' : ''}</span>
        <Link to="/inbox" className={`rail-button ${inboxPage ? 'active' : ''}`}><span className="rail-icon"><Icon name="inbox" /></span>{navOpen && <b>Inbox</b>}{navOpen && <em>{emails.length}</em>}</Link>
        <Link to="/review" className={`rail-button ${reviewPage ? 'active' : ''}`}><span className="rail-icon"><Icon name="review" /></span>{navOpen && <b>Action queue</b>}{navOpen && <em>{attentionCount}</em>}</Link>
        <Link to="/archive" className={`rail-button ${archivePage ? 'active' : ''}`}><span className="rail-icon"><Icon name="archive" /></span>{navOpen && <b>Archive</b>}{navOpen && <em>{archivedEmails.length}</em>}</Link>
        <Link to="/analytics" className={`rail-button ${analyticsPage ? 'active' : ''}`}><span className="rail-icon"><Icon name="document" /></span>{navOpen && <b>Analytics</b>}</Link>
      </nav>
      <div className="rail-bottom"><span className="workspace-avatar">OP</span>{navOpen && <span><strong>Operations</strong><small>Shipping team</small></span>}</div>
    </aside>
    <div className={`shell ${navOpen ? 'nav-open' : ''}`}>
      <header className="topbar">
        <div className="wordmark">{analyticsPage ? 'Analytics' : reviewPage ? 'Action queue' : archivePage ? 'Archive' : 'Shipping inbox'}</div>
        <div className="topbar-actions">
          {inboxPage && <button className="receive-button process-inbox" disabled={Boolean(batch?.running)} title={selectedIds.size ? 'Process the selected emails again' : unprocessedCount ? 'Process emails without a saved report' : 'Run the current pipeline again for the whole inbox'} onClick={() => startBatch(selectedIds.size ? true : unprocessedCount === 0, selectedIds.size ? [...selectedIds] : undefined)}><Icon name="refresh" />{batch?.running ? 'Processing inbox' : selectedIds.size ? `Process selected (${selectedIds.size})` : unprocessedCount ? `Process inbox (${unprocessedCount})` : 'Reprocess inbox'}</button>}
          {!reviewPage && !analyticsPage && selectedIds.size > 0 && <button className="receive-button archive-control" onClick={() => moveSelected(!archivePage)} title={archivePage ? 'Restore selected emails to the active inbox' : 'Hide selected emails from the active inbox'}><Icon name="archive" />{archivePage ? `Restore selected (${selectedIds.size})` : `Archive selected (${selectedIds.size})`}</button>}
          {mailbox?.configured ? <><button className="receive-button" disabled={mailSyncing || mailbox.syncing} onClick={syncMailbox}><Icon name="refresh" />{mailSyncing || mailbox?.syncing ? 'Syncing...' : 'Sync Gmail'}</button><span className={`environment ${mailbox?.connected ? 'mail-connected' : ''}`}><span className="dot" />{mailbox?.connected ? `Gmail / ${mailbox.mailbox}` : 'Gmail connecting'}</span></> : <span className="environment dataset"><span className="dot" />Gmail setup required</span>}
          <span className={`environment ai-state ${aiStatus?.enabled ? 'mail-connected' : ''}`} title={aiStatus?.disabled_reason || undefined}><span className="dot" />{aiLabel}</span>
        </div>
      </header><main>
    <section className="metrics"><div className="metric"><span className="metric-icon"><Icon name="mail" /></span><div><span>Total emails</span><strong>{emails.length}</strong></div></div><div className="metric"><span className="metric-icon completed"><Icon name="check" /></span><div><span>OK</span><strong>{okCount}</strong></div></div><div className="metric mismatch"><span className="metric-icon mismatch"><Icon name="warning" /></span><div><span>Mismatches detected</span><strong>{mismatchCount}</strong></div></div><div className="metric attention"><span className="metric-icon action"><Icon name="review" /></span><div><span>Needs human review</span><strong>{needsReviewCount}</strong></div></div></section>
    <BatchBanner batch={batch} />{error && <p role="alert" className="error-box page-error">{error}</p>}
    {locked ? <form className="access-card" onSubmit={async event => {
      event.preventDefault();
      sessionStorage.setItem('shipcheck-token', token);
      try { await refresh(); await poll(); setError(''); navigate('/inbox'); }
      catch (cause) { setError(cause instanceof Error ? cause.message : 'Access failed.'); }
    }}><label>Workspace access token<input type="password" required value={token} onChange={event => setToken(event.target.value)} /></label><button className="primary">Open workspace</button></form> : <Routes>
      <Route path="/" element={<Navigate to="/inbox" replace />} />
      <Route path="/inbox" element={<Workspace emails={emails} refresh={refresh} selectedIds={selectedIds} toggleSelected={toggleSelected} />} />
      <Route path="/emails/*" element={<Workspace emails={emails} refresh={refresh} selectedIds={selectedIds} toggleSelected={toggleSelected} />} />
      <Route path="/review/*" element={<Workspace emails={emails} refresh={refresh} reviewOnly selectedIds={selectedIds} toggleSelected={toggleSelected} />} />
      <Route path="/archive/*" element={<Workspace emails={archivedEmails} refresh={refresh} archived selectedIds={selectedIds} toggleSelected={toggleSelected} />} />
      <Route path="/analytics" element={<AnalyticsView />} />
      <Route path="*" element={<div className="empty">Page not found. <Link to="/inbox">Return to inbox</Link></div>} />
    </Routes>}
  </main></div></>;
}
