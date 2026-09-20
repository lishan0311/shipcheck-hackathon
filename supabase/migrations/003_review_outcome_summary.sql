-- Include the business outcome of a human decision in the lightweight inbox view.
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

revoke all on public.latest_report_summaries from anon, authenticated;
grant select on public.latest_report_summaries to service_role;
