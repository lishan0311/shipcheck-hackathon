import pytest
from scripts.export_submission import build_submission


def test_export_does_not_invent_missing_predictions():
    with pytest.raises(ValueError):
        build_submission(['email_001'],{})


def test_export_matches_official_shape_and_omits_internal_evidence():
    result={'processing_status':'COMPLETED','category':'BL_COMPARISON','comparison_status':'MISMATCH','defect_fields':['container_count'],'fields':{'private':'evidence'}}
    output=build_submission(['email_001'],{'email_001':{'result':result}})
    assert output['email_001']=={'category':'BL_COMPARISON','status':'MISMATCH','has_defect':True,'defect_fields':['container_count'],'review_reason':None}
