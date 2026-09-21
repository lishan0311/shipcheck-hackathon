import type { Analytics, BatchStatus, EmailDetail, FollowUpBatchResult, Health, Inbox, MailboxStatus, Run, ReviewRequest } from './types';

const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = sessionStorage.getItem('shipcheck-token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${base}/api${path}`, {...options, headers});
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail)
      ? data.detail.map((item: {msg: string}) => item.msg).join('; ') : 'Request failed. Please retry.';
    throw new ApiError(response.status, message);
  }
  return data as T;
}
export const api = {
  health: () => request<Health>('/health'),
  batch: () => request<BatchStatus>('/batch'),
  startBatch: (force=false, emailIds?: string[]) => request<BatchStatus>('/batch/start', {method: 'POST', body: JSON.stringify({force, email_ids: emailIds})}),
  mailbox: () => request<MailboxStatus>('/mailbox/status'),
  syncMailbox: () => request<MailboxStatus>('/mailbox/sync', {method: 'POST', body: '{}'}),
  sendFollowUps: (emailIds:string[]) => request<FollowUpBatchResult>('/cases/follow-ups', {method:'POST',body:JSON.stringify({email_ids:emailIds})}),
  inbox: () => request<Inbox>('/emails'),
  analytics: () => request<Analytics>('/analytics'),
  detail: (id: string, signal?: AbortSignal) => request<EmailDetail>(`/emails/${encodeURIComponent(id)}`, {signal}),
  process: (id: string) => request<Run>(`/emails/${encodeURIComponent(id)}/process`, {method: 'POST', body: '{}'}),
  review: (id: string, body: ReviewRequest) => request<Run>(`/emails/${encodeURIComponent(id)}/review`, {method: 'POST', body: JSON.stringify(body)}),
  completeCase: (id: string) => request<Run>(`/emails/${encodeURIComponent(id)}/case/complete`, {method: 'POST', body: '{}'}),
  download: async (id: string, index: number, filename: string) => {
    const headers = new Headers();
    const token = sessionStorage.getItem('shipcheck-token');
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(`${base}/api/emails/${encodeURIComponent(id)}/attachments/${index}`, {headers});
    if (!response.ok) throw new ApiError(response.status, 'Attachment download failed.');
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click();
    URL.revokeObjectURL(url);
  },
};
