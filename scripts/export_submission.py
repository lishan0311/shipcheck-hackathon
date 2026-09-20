"""Export completed reports for the optional organizer scoring endpoint."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from backend.repository import SupabaseRepository
from backend.settings import Settings


def build_submission(email_ids,latest):
    submission={};blocked=[]
    for eid in email_ids:
        result=latest.get(eid,{}).get('result',{})
        if result.get('processing_status')!='COMPLETED' or not result.get('category'):
            blocked.append(eid);continue
        comparison=result['category']=='BL_COMPARISON'
        # A request to prepare/send a draft BL has no document pair yet. It is
        # correctly classified work, not a failed comparison or escalation.
        status='OK' if result.get('routing_status')=='DRAFT_BL_REQUEST' else (result.get('comparison_status') if comparison else 'OK')
        if status not in {'OK','MISMATCH','NEEDS_REVIEW'}:
            blocked.append(eid);continue
        submission[eid]={'category':result['category'],'status':status,
                         'has_defect':status=='MISMATCH','defect_fields':result.get('defect_fields',[]) if status=='MISMATCH' else [],
                         'review_reason':result.get('review_reason') if status=='NEEDS_REVIEW' else None}
    if blocked:
        raise ValueError(f'{len(blocked)} emails need processing or category confirmation: '+', '.join(blocked[:20]))
    return submission


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('runtime/submission.json'))
    parser.add_argument('--score-url',help='Optional organizer server base URL, for example http://localhost:8080')
    args=parser.parse_args();settings=Settings.from_env()
    if not settings.supabase_url or not settings.supabase_key:
        parser.error('Configure Supabase to export persisted reports.')
    repo=SupabaseRepository(settings.supabase_url,settings.supabase_key,settings.bucket)
    try:
        submission=build_submission([p.stem for p in sorted((settings.dataset/'inbox').glob('*.json'))],repo.latest_all())
    finally:
        repo.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(submission,indent=2),encoding='utf-8')
    print(f'Exported {len(submission)} results to {args.output}')
    if args.score_url:
        response=httpx.post(args.score_url.rstrip('/')+'/submit',json=submission,timeout=60)
        response.raise_for_status();print(json.dumps(response.json(),indent=2))

if __name__=='__main__':
    main()
