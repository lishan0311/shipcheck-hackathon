import copy
import pytest
from pydantic import ValidationError
from backend.comparison import compare_email
from backend.review import apply_review
from backend.schemas import Report, ReviewRequest
from backend.repository import MemoryRepository, StaleReview


def fixture_report():
    text='SHIPPING INSTRUCTION\nShipper: A\nConsignee: B\nNotify: C\nPOL: D\nPOD: E\nContainer Count: 3\nGross Weight (KG): 22000'
    bl=text.replace('SHIPPING INSTRUCTION','BILL OF LADING (DRAFT)').replace('Container Count: 3','Container Count: 4')
    result=compare_email({'email':{'email_id':'demo'},'documents':[{'path':'si.txt','status':'READ','text':text},{'path':'bl.txt','status':'READ','text':bl}]})
    result.update(category='BL_COMPARISON',routing_status='COMPARED')
    return {'run_id':'base','email_id':'demo','result':result}


def test_field_correction_recomputes_without_mutating_original(tmp_path):
    base=fixture_report(); original=copy.deepcopy(base)
    request=ReviewRequest(base_run_id='base',reviewer='Alex',reason='Verified original BL',corrections=[{'field':'container_count','side':'bl','raw_value':'3'}])
    result,audit=apply_review(base,request,tmp_path)
    assert result['comparison_status']=='OK'
    assert base==original
    assert result['fields']['container_count']['bl']['original_source']['attachment_path']=='bl.txt'
    assert audit['changes'][0]['before']['normalized_value']==4
    Report.model_validate(result)


def test_no_false_ok_and_invalid_corrections(tmp_path):
    base=fixture_report()
    base['result'].update(comparison_status='NEEDS_REVIEW',review_reason='unreadable',review_details=['OCR needs review'])
    req=ReviewRequest(base_run_id='base',reviewer='Alex',reason='Checked count',corrections=[{'field':'container_count','side':'bl','raw_value':'3'}])
    assert apply_review(base,req,tmp_path)[0]['comparison_status']=='NEEDS_REVIEW'
    with pytest.raises(ValidationError):
        ReviewRequest(base_run_id='base',reviewer='',reason='ok')
    with pytest.raises(ValidationError):
        Report(email_id='demo',processing_status='COMPLETED',comparison_status='OK')


def test_repository_stale_review_guard():
    repo=MemoryRepository();first=repo.save('demo',fixture_report()['result'])
    repo.save('demo',fixture_report()['result'])
    with pytest.raises(StaleReview):
        repo.save('demo',fixture_report()['result'],expected=first['run_id'])


def test_confirmed_discrepancy_keeps_source_difference_and_sets_next_action(tmp_path):
    base=fixture_report()
    request=ReviewRequest(base_run_id='base',reviewer='Alex',reason='Count checked against both documents',
                          decision='CONFIRM_DISCREPANCY',corrections=[])
    result,audit=apply_review(base,request,tmp_path)
    assert result['comparison_status']=='MISMATCH'
    assert result['defect_fields']==['container_count']
    assert result['fields']['container_count']['bl']['raw_value']=='4'
    assert result['review_outcome']=='CONFIRM_DISCREPANCY'
    assert 'revised draft Bill of Lading' in result['next_action']
    assert audit['decision']=='CONFIRM_DISCREPANCY'


def test_reviewer_can_accept_presentation_difference_without_rewriting_source(tmp_path):
    base=fixture_report()
    count=base['result']['fields']['container_count']
    count['bl']=copy.deepcopy(count['si']);count['state']='MATCH'
    shipper=base['result']['fields']['shipper']
    shipper['bl']['raw_value']='A with address';shipper['bl']['normalized_value']='a with address';shipper['state']='MISMATCH'
    base['result']['defect_fields']=['shipper']
    request=ReviewRequest(base_run_id='base',reviewer='Alex',reason='Equivalent value confirmed',
                          decision='ACCEPT_EQUIVALENT',corrections=[])
    result,_=apply_review(base,request,tmp_path)
    assert result['comparison_status']=='OK'
    assert result['defect_fields']==[]
    field=result['fields']['shipper']
    assert field['resolution']=='ACCEPTED_EQUIVALENT'
    assert field['si']['raw_value']=='A'
    assert field['bl']['raw_value']=='A with address'


def test_equivalent_decision_cannot_hide_an_unresolved_field(tmp_path):
    base=fixture_report()
    count=base['result']['fields']['container_count']
    count['bl']=copy.deepcopy(count['si']);count['state']='MATCH'
    shipper=base['result']['fields']['shipper']
    shipper['bl']['raw_value']='A with address';shipper['bl']['normalized_value']='a with address';shipper['state']='MISMATCH'
    base['result']['fields']['gross_weight_kg']['si']['issue']='Required value is missing.'
    base['result']['fields']['gross_weight_kg']['state']='UNKNOWN'
    base['result']['defect_fields']=['shipper']
    request=ReviewRequest(base_run_id='base',reviewer='Alex',reason='Checked the party name',
                          decision='ACCEPT_EQUIVALENT',corrections=[])
    with pytest.raises(ValueError,match='cannot be accepted as equivalent'):
        apply_review(base,request,tmp_path)


def test_extraction_correction_requires_a_corrected_value(tmp_path):
    request=ReviewRequest(base_run_id='base',reviewer='Alex',reason='Extraction was wrong',category='BL_COMPARISON',
                          decision='CORRECT_EXTRACTION',corrections=[])
    with pytest.raises(ValueError,match='corrected extraction'):
        apply_review(fixture_report(),request,tmp_path)
