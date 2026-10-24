"""One exact native resume of a fully reported known INTERRUPTED build.

Default admission/plan-only. No replanning, budget changes, retry or loop.
No production access until explicitly run after original writer exits.
"""
import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path('/Volumes/扩展盘/guiyi-quant-workstation')
BASE=ROOT/'output/data-three-repair-20261023'
RUNTIME=ROOT/'.worktrees/release-v1.15.18'
sys.path[:0]=[str(RUNTIME/'services/quant-api'),str(RUNTIME/'packages/quant-core')]


def frozen_file(path,expected,loads,*,max_bytes=16777216):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>max_bytes:
        raise ValueError('FROZEN_INPUT_PATH_INVALID')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('FROZEN_INPUT_HASH_CHANGED')
    return loads(raw.decode(),max_bytes=max_bytes)


def known_partial(report):
    if not isinstance(report,dict) or set(report)!={'status','streams'} or report['status']!='partial' or not isinstance(report['streams'],list) or len(report['streams'])!=1:
        raise ValueError('COMPLETE_KNOWN_PARTIAL_REPORT_REQUIRED')
    row=report['streams'][0]
    if not isinstance(row,dict) or set(row)!={'stream_id','status','reason','completed_bars',
            'candidate_revision_id','active_revision_id','last_batch_key','resume_token','snapshot'}:
        raise ValueError('COMPLETE_KNOWN_PARTIAL_REPORT_REQUIRED')
    if (row.get('status')!='partial' or row.get('reason')!='INTERRUPTED'
            or row.get('active_revision_id') is not None or row.get('snapshot') is not None):
        raise ValueError('UNKNOWN_OR_NONINTERRUPTED_RESULT_FORBIDDEN')
    token=row.get('resume_token')
    if not isinstance(token,dict) or set(token)!={'plan_hash','stream_id','revision_id','next_input_index','source_token','last_batch_key'}:
        raise ValueError('COMPLETE_RESUME_TOKEN_REQUIRED')
    if (type(token['next_input_index']) is not int or token['next_input_index']<=0
            or row.get('completed_bars')!=token['next_input_index']
            or row.get('stream_id')!=token['stream_id']
            or row.get('candidate_revision_id')!=token['revision_id']
            or row.get('last_batch_key')!=token['last_batch_key']):
        raise ValueError('PARTIAL_REPORT_TOKEN_CONFLICT')
    return token


def exact_candidate(state,receipt,evidence,token,stream_plan,snapshot):
    if (state.revision_status!='candidate' or state.revision_id!=token.revision_id
            or state.stream.active_revision_id is not None
            or state.checkpoint_batch_key!=token.last_batch_key
            or state.source_evidence.get('end_input_index')!=token.next_input_index
            or state.dependency_digest!=stream_plan.dependency_digest
            or state.dependency_manifest!=stream_plan.input_manifest):
        raise ValueError('CANDIDATE_CHECKPOINT_CHANGED')
    if (receipt is None or evidence is None or receipt.seq!=state.checkpoint.seq
            or receipt.revision_id!=token.revision_id
            or receipt.checkpoint_hash!=state.checkpoint.state_hash
            or evidence.get('end_input_index')!=token.next_input_index
            or evidence!=state.source_evidence):
        raise ValueError('EXACT_LAST_RECEIPT_REQUIRED')
    if (snapshot.source_token!=token.source_token
            or snapshot.dependency_manifest!=stream_plan.input_manifest
            or len(snapshot.bars)!=stream_plan.input_count
            or token.next_input_index>len(snapshot.bars)
            or evidence.get('last_fingerprint')!=snapshot.bars[token.next_input_index-1].fingerprint):
        raise ValueError('FRESH_SOURCE_CHANGED')


def resume_effect(service,plan,token,dispatch,out,intent,jsonable):
    dispatch.durable_write(out/'resume-intent.json',intent)
    native=service.resume(plan,token,plan.plan_hash)
    dispatch.durable_write(out/'resume-report.json',jsonable(native))
    return native


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('inventory','plan','report','intent'):
        parser.add_argument('--'+key,type=Path,required=True)
        parser.add_argument('--'+key+'-sha256',required=True)
    parser.add_argument('--original-writer-exited',action='store_true',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--check-only',action='store_true',help='Fresh production reads only; never calculate or publish')
    args=parser.parse_args()
    if args.apply and args.check_only: parser.error('Choose apply or check-only')
    if args.apply or args.check_only:
        spec=importlib.util.spec_from_file_location('private_boot',ROOT/'output/runtime-intraday-repair-20261013/dual-park-day13-preparation.py')
        private=importlib.util.module_from_spec(spec);spec.loader.exec_module(private);private.bootstrap_private()
        os.environ['GUIYI_PROJECT_ROOT']=str(RUNTIME)
    from app.guiyi_cli.reference_commands import strict_json_loads,_jsonable
    from app.reference_trading.planning import plan_from_dict,_wire
    from app.reference_trading.service import ResumeToken
    from guiyi_quant.subing_reference import _stream_identity
    # The already-produced AL plan is 51.4 MB due to its full immutable
    # prefix. Parse that exact frozen artifact with an explicit 128 MiB cap;
    # never truncate, reserialize, or alter its original native budget/hash.
    values={key:frozen_file(getattr(args,key),getattr(args,key+'_sha256'),strict_json_loads,
                           max_bytes=134217728 if key=='plan' else 16777216)
            for key in ('inventory','plan','report','intent')}
    token=ResumeToken(**known_partial(values['report']))
    plan=plan_from_dict(values['plan'])
    if plan.operation!='build' or len(plan.streams)!=1 or token.plan_hash!=plan.plan_hash:
        raise ValueError('ORIGINAL_BUILD_PLAN_REQUIRED')
    stream_plan=plan.streams[0];identity=stream_plan.request.identity;original_intent=values['intent']
    if (identity.strategy_code!='subing_reference' or identity.frequency not in ('15m','30m','60m','1d')
            or _wire(identity)!=_wire(_stream_identity(identity.product,identity.frequency,identity.frequency=='1d'))
            or token.stream_id!=identity.stream_id or token.source_token!=stream_plan.source_token
            or original_intent.get('plan_hash')!=plan.plan_hash
            or original_intent.get('stream_id')!=identity.stream_id
            or original_intent.get('identity')!=_wire(identity)
            or original_intent.get('source_token')!=token.source_token
            or original_intent.get('since')!=str(stream_plan.request.since)
            or original_intent.get('through')!=str(stream_plan.request.through)
            or original_intent.get('as_of')!=stream_plan.request.as_of.isoformat()
            or values['inventory'].get('as_of')!=stream_plan.request.as_of.isoformat()
            or original_intent.get('inventory_sha256')!=args.inventory_sha256):
        raise ValueError('ORIGINAL_INTENT_IDENTITY_CONFLICT')
    matching=[x for x in values['inventory']['streams'] if x['stream_id']==identity.stream_id]
    if (len(matching)!=1 or matching[0]['status']!='ABSENT'
            or matching[0]['identity']!=_wire(identity)
            or str(stream_plan.request.since)!=matching[0]['product_start']
            or str(stream_plan.request.through)!='2026-10-23'
            or values['inventory']['runtime']!=str(RUNTIME)):
        raise ValueError('ORIGINAL_INVENTORY_CONFLICT')
    runtime_commit=subprocess.check_output(['/usr/bin/git','-C',str(RUNTIME),'rev-parse','HEAD'],text=True).strip()
    release_commit=subprocess.check_output(['/usr/bin/git','-C',str(RUNTIME),'rev-parse','v1.15.18^{commit}'],text=True).strip()
    if runtime_commit!=release_commit: raise ValueError('EXACT_RUNTIME_COMMIT_REQUIRED')
    spec=importlib.util.spec_from_file_location('dispatch',BASE/'v18-subing-route-dispatch.py')
    dispatch=importlib.util.module_from_spec(spec);spec.loader.exec_module(dispatch)
    if not (args.apply or args.check_only):
        print(json.dumps(dict(status='PLAN_ONLY_NO_PRODUCTION_ACCESS',plan_hash=plan.plan_hash,resume_token=asdict(token),runtime_commit=runtime_commit)))
        return 0
    # Deterministic per-token directory forbids a second use of the same report,
    # even if the caller attempts to choose a different output directory.
    token_sha=hashlib.sha256(json.dumps(asdict(token),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    previous=BASE/('subing-native-resume-'+token_sha)
    if (not (previous/'result.json').is_file() or json.loads((previous/'result.json').read_text()).get('status')!='PREFLIGHT'
            or any(previous.glob('*intent.json')) or any(previous.glob('*report.json'))):
        raise ValueError('PREVIOUS_ATTEMPT_NOT_PROVEN_PREFLIGHT_ONLY')
    suffix='-check' if args.check_only else '-apply'
    out=dispatch.output_directory(BASE/('subing-native-resume-v2-'+token_sha+suffix))
    result=dict(status='PREFLIGHT',plan_hash=plan.plan_hash,resume_token=asdict(token),runtime_commit=runtime_commit)
    try:

        from app.reference_trading.composition import open_historical_reference_components
        with open_historical_reference_components(reuse_market_inputs=True) as (planner,service):
            repo=service._repository
            snapshot=planner._reader.load_stream(stream_plan.request,expected_source_token=token.source_token)
            state=repo.read_state(token.stream_id,token.revision_id)
            receipt=repo.read_batch(token.stream_id,token.revision_id,token.last_batch_key)
            evidence=repo.read_batch_evidence(token.stream_id,token.revision_id,token.last_batch_key)
            exact_candidate(state,receipt,evidence,token,stream_plan,snapshot)
            index,key,published=service._validate_resume_position(plan,stream_plan,snapshot,token)
            if (index,key,published)!=(token.next_input_index,token.last_batch_key,None):
                raise ValueError('EXACT_REPORTED_POSITION_REQUIRED')
            hashes={key:getattr(args,key+'_sha256') for key in ('inventory','plan','report','intent')}
            intent=dict(schema_version='exact_subing_native_resume_once_v1',frozen_sha256=hashes,
                runtime_commit=runtime_commit,plan_hash=plan.plan_hash,identity=_wire(identity),
                resume_token=asdict(token),checkpoint=asdict(state.checkpoint),
                source_token=snapshot.source_token,dependency_digest=state.dependency_digest)
            if args.check_only:
                result.update(status='PREFLIGHT_PASSED',production_writes=0,next_input_index=index,input_count=len(snapshot.bars))
                dispatch.durable_write(out/'result.json',result)
                print(json.dumps(dict(output=str(out),**result)))
                return 0
            result['status']='OUTCOME_UNKNOWN'
            native=resume_effect(service,plan,token,dispatch,out,intent,_jsonable)
            result['status']=native.status
            result['report_path']=str(out/'resume-report.json')
    except BaseException as error:
        import re
        code=getattr(error,'code',None) or str(error)
        result['error_type']=type(error).__name__
        import traceback
        result['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(error.__traceback__) if str(ROOT) in f.filename]
        result['stopped']=code if re.fullmatch('[A-Z][A-Z0-9_]{1,120}',str(code)) else 'DETAIL_REDACTED'
    dispatch.durable_write(out/'result.json',result)
    print(json.dumps(dict(output=str(out),**result)))
    return 0 if result['status'] in ('completed','PREFLIGHT_PASSED') else 1


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as error:
        import re
        code=getattr(error,'code',None) or str(error)
        print(json.dumps(dict(status='STOPPED',error=code if re.fullmatch('[A-Z][A-Z0-9_]{1,120}',str(code)) else 'DETAIL_REDACTED')))
        sys.exit(1)
