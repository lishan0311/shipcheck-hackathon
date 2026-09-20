-- Run in your own Supabase SQL editor. No anonymous access to shipment data.
create table if not exists public.emails (
  email_id text primary key,
  payload jsonb not null,
  created_at timestamptz not null default now()
);
create table if not exists public.attachments (
  email_id text not null references public.emails(email_id),
  path text not null,
  object_path text not null,
  sha256 text not null,
  size_bytes bigint not null,
  primary key(email_id, path)
);
create table if not exists public.processing_jobs (
  job_id uuid primary key default gen_random_uuid(),
  email_id text not null references public.emails(email_id),
  status text not null check (status in ('RUNNING','COMPLETED','FAILED')),
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
create table if not exists public.reports (
  run_id uuid primary key default gen_random_uuid(),
  sequence bigint generated always as identity unique,
  email_id text not null references public.emails(email_id),
  created_at timestamptz not null default now(),
  result jsonb not null
);
create index if not exists reports_email_sequence on public.reports(email_id, sequence desc);
create table if not exists public.reviews (
  review_id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.reports(run_id),
  base_run_id uuid not null references public.reports(run_id),
  email_id text not null references public.emails(email_id),
  audit jsonb not null,
  created_at timestamptz not null default now()
);
alter table public.emails enable row level security;
alter table public.attachments enable row level security;
alter table public.processing_jobs enable row level security;
alter table public.reports enable row level security;
alter table public.reviews enable row level security;

create or replace view public.latest_reports with (security_invoker=true) as
select distinct on (email_id) run_id, email_id, created_at, result
from public.reports order by email_id, sequence desc;

create or replace view public.latest_report_summaries with (security_invoker=true) as
select distinct on (email_id)
  run_id, email_id, created_at,
  jsonb_build_object(
    'processing_status', result->'processing_status',
    'category', result->'category',
    'predicted_category', result#>'{classification,predicted_category}',
    'confidence', result#>'{classification,confidence}',
    'needs_category_review', coalesce((result#>>'{classification,needs_review}')::boolean, false),
    'routing_status', result->'routing_status',
    'comparison_status', result->'comparison_status',
    'defect_fields', coalesce(result->'defect_fields', '[]'::jsonb),
    'review_details', coalesce(result->'review_details', '[]'::jsonb),
    'reviewed', coalesce(result->>'routing_source','') = 'human_review',
    'review_outcome', result->'review_outcome',
    'next_action', result->'next_action'
  ) as result
from public.reports order by email_id, sequence desc;

create or replace function public.persist_report(
  p_email_id text, p_result jsonb, p_job_id uuid default null,
  p_expected_run_id uuid default null, p_review jsonb default null
) returns jsonb language plpgsql security invoker set search_path=public as $$
declare saved public.reports; latest uuid;
begin
  perform 1 from public.emails where email_id=p_email_id for update;
  if not found then raise exception 'Email does not exist'; end if;
  select run_id into latest from public.reports where email_id=p_email_id order by sequence desc limit 1;
  if p_expected_run_id is not null and latest is distinct from p_expected_run_id then
    raise sqlstate 'PT409' using message='A newer report exists';
  end if;
  insert into public.reports(email_id,result) values(p_email_id,p_result) returning * into saved;
  if p_review is not null then
    insert into public.reviews(run_id,base_run_id,email_id,audit)
    values(saved.run_id,p_expected_run_id,p_email_id,p_review);
  end if;
  if p_job_id is not null then
    update public.processing_jobs set status=p_result->>'processing_status',finished_at=now()
    where job_id=p_job_id and email_id=p_email_id;
  end if;
  return jsonb_build_object('run_id',saved.run_id,'email_id',saved.email_id,'created_at',saved.created_at,'result',saved.result);
end $$;
revoke all on function public.persist_report(text,jsonb,uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.persist_report(text,jsonb,uuid,uuid,jsonb) to service_role;
revoke all on public.emails,public.attachments,public.processing_jobs,public.reports,public.reviews,public.latest_reports,public.latest_report_summaries from anon,authenticated;
grant all on public.emails,public.attachments,public.processing_jobs,public.reports,public.reviews to service_role;
grant select on public.latest_reports to service_role;
grant select on public.latest_report_summaries to service_role;
grant usage,select on all sequences in schema public to service_role;

insert into storage.buckets(id,name,public,file_size_limit)
values('shipping-documents','shipping-documents',false,20971520)
on conflict(id) do nothing;
