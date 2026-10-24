"""Exact one-shot native RB4 append only. Default offline admission; no rebuild.

Accepts a SHA-frozen local bundle. Any failed or unknown native result stops.
Old sealed batch/checkpoint headers and full action/mark/economic trade rows
are independently fingerprinted; valid_to_seq may only close after old cutoff.
"""
import argparse
from dataclasses import asdict
from datetime import date
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


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def exact_old_state(state,frozen):
    if (state.revision_status!='active' or state.revision_id!=frozen['revision_id']
            or state.stream.active_revision_id!=frozen['revision_id']
            or state.checkpoint.seq!=frozen['seq']
            or state.source_evidence.get('end_input_index')!=frozen['processed']
            or state.dependency_manifest.get('query_since')!=frozen['query_since']):
        raise ValueError('RB_OLD_CHECKPOINT_CHANGED')


def valid_closures(before,after,old_seq,new_seq):
    if set(before)!=set(after):raise ValueError('OLD_TRADE_ROWS_CHANGED')
    for key,prior in before.items():
        current=after[key]
        if prior!=current and not (prior is None and type(current) is int and old_seq<current<=new_seq):
            raise ValueError('OLD_TRADE_VALIDITY_REWRITTEN')


def old_facts(factory,identity,revision,cutoff):
    from sqlalchemy import select,or_
    from app.db.readonly import readonly_transaction
    from app.reference_trading.models import ReferenceBatch,ReferenceActionRow,ReferenceTradeRow,ReferenceMarkRow
    result={}
    with factory() as db,readonly_transaction(db,timeout_seconds=120):
        configs=[('batch_headers',ReferenceBatch,
            [ReferenceBatch.__table__.c[key] for key in ('batch_id','seq','batch_key','payload_hash','kind','expected_seq','pre_state_hash','post_state_hash','checkpoint_text','strategy_schema','computed_through')],
            (ReferenceBatch.stream_id==identity.stream_id,ReferenceBatch.revision_id==revision,or_(ReferenceBatch.seq<=cutoff,ReferenceBatch.seq.is_(None)))),
            ('actions',ReferenceActionRow,list(ReferenceActionRow.__table__.columns),
             (ReferenceActionRow.stream_id==identity.stream_id,ReferenceActionRow.batch_revision_id==revision,ReferenceActionRow.batch_seq<=cutoff)),
            ('trade_economic_rows',ReferenceTradeRow,[c for c in ReferenceTradeRow.__table__.columns if c.name!='valid_to_seq'],
             (ReferenceTradeRow.stream_id==identity.stream_id,ReferenceTradeRow.revision_id==revision,ReferenceTradeRow.valid_from_seq<=cutoff)),
            ('marks',ReferenceMarkRow,list(ReferenceMarkRow.__table__.columns),
             (ReferenceMarkRow.stream_id==identity.stream_id,ReferenceMarkRow.revision_id==revision,ReferenceMarkRow.batch_seq<=cutoff))]
        for name,model,columns,where in configs:
            rows=[list(row) for row in db.execute(select(*columns).where(*where).order_by(*model.__table__.primary_key.columns))]
            result[name]=dict(count=len(rows),sha256=sha(rows))
        validity=db.execute(select(ReferenceTradeRow.trade_id,ReferenceTradeRow.valid_from_seq,ReferenceTradeRow.valid_to_seq).where(
            ReferenceTradeRow.stream_id==identity.stream_id,ReferenceTradeRow.revision_id==revision,ReferenceTradeRow.valid_from_seq<=cutoff))
        result['trade_validity']={json.dumps([trade_id,seq]):end for trade_id,seq,end in validity}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--bundle-sha256',required=True)
    parser.add_argument('--previous-writer-exited',required=True,action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--check-only',action='store_true',help='Fresh production reads only; never calculate or publish')
    args=parser.parse_args()
    if args.apply and args.check_only: parser.error('Choose apply or check-only')
    if args.apply or args.check_only:
        spec=importlib.util.spec_from_file_location('private_boot',ROOT/'output/runtime-intraday-repair-20261013/dual-park-day13-preparation.py')
        private=importlib.util.module_from_spec(spec);spec.loader.exec_module(private);private.bootstrap_private()
        os.environ['GUIYI_PROJECT_ROOT']=str(RUNTIME)
    spec=importlib.util.spec_from_file_location('resume',BASE/'v18-subing-native-resume-once.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    from app.guiyi_cli.reference_commands import strict_json_loads,_jsonable
    from app.reference_trading.planning import plan_from_dict,_wire
    from guiyi_quant.subing_reference import _stream_identity
    bundle=helper.frozen_file(args.bundle,args.bundle_sha256,strict_json_loads)
    frozen=helper.frozen_file(Path(bundle['result_path']),bundle['result_sha256'],strict_json_loads)
    if frozen.get('mode')!='rb-plan' or frozen.get('runtime')!=str(RUNTIME):raise ValueError('RB_BUNDLE_IDENTITY_INVALID')
    checks=frozen['checks']
    if len(checks)!=4 or {x['frequency'] for x in checks}!={'15m','30m','60m','1d'}:raise ValueError('EXACT_RB4_REQUIRED')
    plans={}
    for row in checks:
        spec=bundle['plans'][row['frequency']]
        plan=plan_from_dict(helper.frozen_file(Path(spec['path']),spec['sha256'],strict_json_loads,max_bytes=134217728))
        if plan.operation!='advance' or len(plan.streams)!=1:raise ValueError('ADVANCE_ONLY_REQUIRED')
        stream=plan.streams[0];identity=stream.request.identity
        if (row['operation']!='advance' or row['reason']!='EXACT_APPEND_PROVEN'
                or plan.plan_hash!=row['plan_hash'] or stream.source_token!=row['source_token']
                or identity.stream_id!=row['stream_id'] or identity.product!='RB'
                or _wire(identity)!=_wire(_stream_identity('RB',row['frequency'],row['frequency']=='1d'))
                or str(stream.request.since)!='2023-01-01' or str(stream.request.through)!='2026-10-23'
                or stream.request.as_of.isoformat()!='2026-10-23T16:00:00+00:00'):
            raise ValueError('RB_PLAN_IDENTITY_CHANGED')
        plans[row['frequency']]=plan
    commit=subprocess.check_output(['/usr/bin/git','-C',str(RUNTIME),'rev-parse','HEAD'],text=True).strip()
    tag=subprocess.check_output(['/usr/bin/git','-C',str(RUNTIME),'rev-parse','v1.15.18^{commit}'],text=True).strip()
    if commit!=tag or commit!=bundle['runtime_commit']:raise ValueError('EXACT_RUNTIME_REQUIRED')
    if not (args.apply or args.check_only):
        print(json.dumps(dict(status='PLAN_ONLY_NO_PRODUCTION_ACCESS',plan_hashes={f:p.plan_hash for f,p in plans.items()})))
        return 0
    spec=importlib.util.spec_from_file_location('dispatch',BASE/'v18-subing-route-dispatch.py')
    dispatch=importlib.util.module_from_spec(spec);spec.loader.exec_module(dispatch)
    previous=BASE/('subing-rb-advance-'+args.bundle_sha256)
    if (not (previous/'result.json').is_file() or json.loads((previous/'result.json').read_text()).get('status')!='PREFLIGHT'
            or any(previous.glob('*intent.json')) or any(previous.glob('*report.json'))):
        raise ValueError('PREVIOUS_ATTEMPT_NOT_PROVEN_PREFLIGHT_ONLY')
    suffix='-check' if args.check_only else '-apply'
    out=dispatch.output_directory(BASE/('subing-rb-advance-v2-'+args.bundle_sha256+suffix))
    result=dict(status='PREFLIGHT',routes=[],bundle_sha256=args.bundle_sha256)
    try:

        from app.db.session import SessionLocal
        from app.reference_trading.composition import open_historical_reference_components
        from app.reference_trading.contracts import prove_dependency_append
        for frozen_row in checks:
            frequency=frozen_row['frequency'];plan=plans[frequency];stream=plan.streams[0];identity=stream.request.identity
            with open_historical_reference_components(reuse_market_inputs=True) as (planner,service):
                repo=service._repository
                before=repo.read_state(identity.stream_id);exact_old_state(before,frozen_row)
                snapshot=planner._reader.load_stream(stream.request,expected_source_token=stream.source_token)
                if snapshot.dependency_manifest!=stream.input_manifest or len(snapshot.bars)!=stream.input_count:raise ValueError('FRESH_SOURCE_CHANGED')
                index=frozen_row['processed'];tail=snapshot.bars[index:]
                if not tail or before.source_evidence.get('last_fingerprint')!=snapshot.bars[index-1].fingerprint:raise ValueError('EXACT_APPEND_REQUIRED')
                prove_dependency_append(before.dependency_manifest,stream.input_manifest,appended_ranges=tuple(x.fingerprint for x in tail))
                facts=old_facts(SessionLocal,identity,before.revision_id,before.checkpoint.seq)
                after_proof=repo.read_state(identity.stream_id);exact_old_state(after_proof,frozen_row)
                if (after_proof.checkpoint,after_proof.dependency_digest)!=(before.checkpoint,before.dependency_digest):raise ValueError('RB_CHECKPOINT_DRIFT')
                dispatch.durable_write(out/(frequency+'-old-facts.json'),facts)
                if args.check_only:
                    result['routes'].append(dict(frequency=frequency,status='PREFLIGHT_PASSED',processed=index,input_count=stream.input_count,old_facts_sha256=sha(facts)))
                    continue
                dispatch.durable_write(out/(frequency+'-intent.json'),dict(bundle_sha256=args.bundle_sha256,
                    plan_hash=plan.plan_hash,identity=_wire(identity),old_revision_id=before.revision_id,
                    checkpoint=asdict(before.checkpoint),dependency_digest=before.dependency_digest,
                    source_token=stream.source_token,old_facts_sha256=sha(facts),runtime_commit=commit))
                result['status']='OUTCOME_UNKNOWN'
                native=service.advance(plan,plan.plan_hash)
                dispatch.durable_write(out/(frequency+'-report.json'),_jsonable(native))
                row=dict(frequency=frequency,status=native.status);result['routes'].append(row)
                if native.status!='completed':raise ValueError('NATIVE_RESULT_REQUIRES_READBACK')
                after=repo.read_state(identity.stream_id)
                if (after.revision_id!=before.revision_id or after.revision_status!='active'
                        or after.source_evidence.get('end_input_index')!=stream.input_count):raise ValueError('RB_POSTCHECKPOINT_INVALID')
                current=old_facts(SessionLocal,identity,before.revision_id,before.checkpoint.seq)
                valid_closures(facts.pop('trade_validity'),current.pop('trade_validity'),before.checkpoint.seq,after.checkpoint.seq)
                if facts!=current:raise ValueError('OLD_FACTS_CHANGED')
                dispatch.durable_write(out/(frequency+'-readback.json'),dict(old_facts_preserved=True,
                    old_facts=current,revision_id=after.revision_id,checkpoint=asdict(after.checkpoint)))
        result['status']='PREFLIGHT_PASSED' if args.check_only else 'completed'
        if args.check_only:result['production_writes']=0
    except BaseException as error:
        import re
        code=getattr(error,'code',None) or str(error)
        result['error_type']=type(error).__name__
        import traceback
        result['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(error.__traceback__) if str(ROOT) in f.filename]
        result['stopped']=code if re.fullmatch('[A-Z][A-Z0-9_]{1,120}',str(code)) else 'DETAIL_REDACTED'
    dispatch.durable_write(out/'result.json',result);print(json.dumps(dict(output=str(out),**result)))
    return 0 if result['status'] in ('completed','PREFLIGHT_PASSED') else 1


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        print('{"status":"STOPPED_DETAIL_REDACTED"}');sys.exit(1)
