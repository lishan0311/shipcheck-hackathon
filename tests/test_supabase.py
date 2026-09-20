import json
import httpx
import pytest
from backend.repository import SupabaseRepository, StaleReview


def test_private_storage_and_database_requests(tmp_path):
    (tmp_path/'attachments').mkdir();(tmp_path/'attachments/a.txt').write_text('SI example')
    requests=[]
    def respond(request):
        requests.append(request)
        if '/rpc/' in request.url.path:
            return httpx.Response(200,json={'run_id':'id','email_id':'demo','created_at':'time','result':{}})
        return httpx.Response(200,json=[])
    client=httpx.Client(base_url='https://project.supabase.co',transport=httpx.MockTransport(respond),headers={'apikey':'server-key','Authorization':'Bearer server-key'})
    repo=SupabaseRepository('https://project.supabase.co','server-key','shipping-documents',client)
    repo.sync_email({'email_id':'demo','attachments':['attachments/a.txt']},tmp_path)
    repo.save('demo',{'processing_status':'COMPLETED'},expected='base',review={'reason':'confirmed'})
    assert any('/storage/v1/object/shipping-documents/' in r.url.path for r in requests)
    assert all(r.headers['Authorization']=='Bearer server-key' for r in requests)
    payload=json.loads(requests[-1].content)
    assert payload['p_expected_run_id']=='base'
    assert payload['p_review']['reason']=='confirmed'
    assert 'server-key' not in str(payload)


def test_supabase_conflict_is_exposed_as_stale_review():
    client=httpx.Client(base_url='https://project.supabase.co',transport=httpx.MockTransport(lambda r:httpx.Response(409,json={'message':'conflict'})))
    repo=SupabaseRepository('https://project.supabase.co','key','bucket',client)
    with pytest.raises(StaleReview):
        repo.save('demo',{})
