"""Explicit, independent PostgreSQL development journal and rebuildable projection."""
import json
from hashlib import sha256
from sqlalchemy import MetaData,Table,Column,String,Integer,JSON,ForeignKey,create_engine,select,insert,update,text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

metadata=MetaData()
runs=Table('subing_development_runs',metadata,Column('run_id',String(100),primary_key=True),Column('identity',JSON,nullable=False),Column('sequence',Integer,nullable=False),Column('tail_hash',String(64),nullable=False),Column('state',JSON,nullable=False))
events=Table('subing_development_events',metadata,Column('run_id',String(100),ForeignKey(runs.c.run_id),primary_key=True),Column('sequence',Integer,primary_key=True),Column('event_id',String(250),nullable=False),Column('input_hash',String(64),nullable=False),Column('event_hash',String(64),nullable=False),Column('previous_hash',String(64),nullable=False),Column('payload',JSON,nullable=False))
ZERO='0'*64

def digest(x):return sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

class ModelStore:
    def __init__(self,url,*,test_only=False):
        parsed=make_url(url)
        if parsed.get_backend_name()!='postgresql' or parsed.host not in ('127.0.0.1','localhost','::1') or parsed.database!=('guiyi_subing_development_test' if test_only else 'guiyi_subing_development') or parsed.query:
            raise ValueError('SUBING_DEVELOPMENT_DATABASE_REQUIRED')
        self.engine=create_engine(url,connect_args={'connect_timeout':5})

    def initialize(self):
        """Explicit developer setup only; never called on HTTP requests."""
        with self.engine.begin() as c:
            metadata.create_all(c)
            c.execute(text("CREATE OR REPLACE FUNCTION subing_development_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'SUBING_EVENT_IMMUTABLE'; END $$"))
            c.execute(text("CREATE OR REPLACE FUNCTION subing_development_identity_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.identity::jsonb IS DISTINCT FROM OLD.identity::jsonb OR NEW.run_id IS DISTINCT FROM OLD.run_id THEN RAISE EXCEPTION 'SUBING_RUN_IDENTITY_IMMUTABLE'; END IF; RETURN NEW; END $$"))
            if not c.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='subing_development_identity_no_change')")):
                c.execute(text('CREATE TRIGGER subing_development_identity_no_change BEFORE UPDATE ON subing_development_runs FOR EACH ROW EXECUTE FUNCTION subing_development_identity_immutable()'))
            if not c.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='subing_development_no_event_change')")):
                c.execute(text('CREATE TRIGGER subing_development_no_event_change BEFORE UPDATE OR DELETE OR TRUNCATE ON subing_development_events FOR EACH STATEMENT EXECUTE FUNCTION subing_development_immutable()'))

    def create(self,run_id,identity,state):
        with self.engine.begin() as c:
            existing=c.execute(select(runs).where(runs.c.run_id==run_id)).mappings().first()
            if existing:
                if existing['identity']!=identity:raise ValueError('MODEL_IDENTITY_CONFLICT')
                return
            c.execute(insert(runs).values(run_id=run_id,identity=identity,sequence=0,tail_hash=ZERO,state=state))

    def load(self,run_id):
        with self.engine.connect() as c:
            r=c.execute(select(runs).where(runs.c.run_id==run_id)).mappings().one()
            rows=c.execute(select(events).where(events.c.run_id==run_id).order_by(events.c.sequence)).mappings().all()
        previous=ZERO;ids=set()
        for i,e in enumerate(rows,1):
            if e['sequence']!=i or e['previous_hash']!=previous or e['event_id'] in ids or e['input_hash']!=digest(e['payload']):raise ValueError('MODEL_JOURNAL_INVALID')
            h=digest(dict(run_id=run_id,sequence=i,event_id=e['event_id'],input_hash=e['input_hash'],previous_hash=previous))
            if h!=e['event_hash']:raise ValueError('MODEL_JOURNAL_INVALID')
            previous=h;ids.add(e['event_id'])
        if len(rows)!=r['sequence'] or previous!=r['tail_hash']:raise ValueError('MODEL_TAIL_INVALID')
        return dict(r),[e['payload'] for e in rows]

    def append(self,run_id,payload,state,expected_sequence):
        try:
            with self.engine.begin() as c:
                r=c.execute(select(runs).where(runs.c.run_id==run_id).with_for_update()).mappings().one()
                old=c.execute(select(events).where(events.c.run_id==run_id,events.c.event_id==payload['event_id'])).mappings().first()
                if old:
                    if old['input_hash']!=digest(payload):raise ValueError('MODEL_EVENT_CONFLICT')
                    return False
                if r['sequence']!=expected_sequence:raise ValueError('MODEL_CONCURRENT_WRITER')
                seq=expected_sequence+1;h=digest(dict(run_id=run_id,sequence=seq,event_id=payload['event_id'],input_hash=digest(payload),previous_hash=r['tail_hash']))
                c.execute(insert(events).values(run_id=run_id,sequence=seq,event_id=payload['event_id'],input_hash=digest(payload),event_hash=h,previous_hash=r['tail_hash'],payload=payload))
                c.execute(update(runs).where(runs.c.run_id==run_id).values(sequence=seq,tail_hash=h,state=state))
            return True
        except DBAPIError:raise ValueError('MODEL_COMMIT_OUTCOME_UNKNOWN') from None
