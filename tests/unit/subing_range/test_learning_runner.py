"""Failure injection at the full stage-1 composition boundary, no database/files of record."""
from contextlib import nullcontext
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
import gzip
import json

import pytest

from scripts.research import regime_learning as runner


@pytest.fixture
def harness(monkeypatch,tmp_path):
    import sqlalchemy
    import sqlalchemy.orm
    from app.db import readonly, url
    from app import private_settings
    from app.market_data import catalog,market_data_service,storage,actual_dominant_research
    products=[s for s in (runner.ROOT/'data/universe/operational_products.txt').read_text().splitlines() if s]
    calls=[]
    class Session:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,*a):return [(s,date(2023,1,3),date(2023,6,29)) for s in products]
    class Catalog:
        def __init__(self,*a):pass
        def trading_days(self,symbol,start,end):
            return tuple(date(2023,1,3)+timedelta(days=i) for i in range(100))
        def product_partitions(self,symbol):return ()
    class Market:
        def __init__(self,*a):pass
        def release_decoded_read_caches(self):pass
        def contract_source_evidence(self,**kw):return {}
    def owners(self,**kw):
        calls.append(kw)
        return (SimpleNamespace(contract='X',start_trading_day=date(2023,1,3),end_trading_day=date(2023,6,30)),)
    monkeypatch.setattr(sqlalchemy,'create_engine',lambda *a,**kw:SimpleNamespace(dispose=lambda:None))
    monkeypatch.setattr(sqlalchemy.orm,'Session',Session)
    monkeypatch.setattr(readonly,'readonly_transaction',lambda *a,**kw:nullcontext())
    monkeypatch.setattr(url,'normalize_database_url',lambda s:s)
    monkeypatch.setattr(private_settings,'load_private_readonly_settings',lambda *a:({'DATABASE_URL':'test','GUIYI_CANONICAL_DATA_ROOT':str(tmp_path)},None))
    monkeypatch.setattr(catalog,'MarketCatalog',Catalog)
    monkeypatch.setattr(market_data_service,'MarketDataService',Market)
    monkeypatch.setattr(storage,'CanonicalMonthlyStore',lambda *a:None)
    monkeypatch.setattr(actual_dominant_research.ActualDominantResearchSegmentLoader,'owner_segments',owners)
    monkeypatch.setattr(runner,'physical_rows',lambda *a:([1],dict(contract='X',frequency=a[3],owner_start=date(2023,1,3),owner_end=date(2023,6,30),source={},cutoff=None,bars_hash='fixed')))
    return calls


def test_failed_segment_cannot_leak_partial_rows_or_blind_candidates(harness,monkeypatch,tmp_path):
    from tests.unit.subing_range.test_learning import sample_bars
    def broken(bars,symbol,frequency,source,sector,pool,splits):
        pool.offer(symbol=symbol,frequency=frequency,contract='X',sector=sector,label='RANGE',bars=sample_bars())
        yield dict(owned=True,reference={'label':'RANGE'},partition='DEVELOPMENT')
        raise ValueError('INJECTED_AFTER_FIRST_ROW')
    monkeypatch.setattr(runner,'observe',broken)
    out=tmp_path/'atomic'
    runner.run(out,date(2023,6,30))
    assert json.loads((out/'run.json').read_text())['samples']==0
    assert all(r['owned_bars']==0 and r['status']=='UNAVAILABLE' for r in json.loads((out/'coverage.json').read_text()))
    assert all(gzip.open(p,'rt').read()=='' for p in out.glob('*.jsonl.gz'))


def test_mapping_tail_is_requested_not_silently_clipped(harness,monkeypatch,tmp_path):
    from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
    calls=[]
    def missing_tail(self,**kw):
        calls.append(kw)
        assert kw['through']==date(2023,6,30)  # fake catalog's last mapping is June 29
        raise ValueError('MAPPING_TAIL_MISSING')
    monkeypatch.setattr(ActualDominantResearchSegmentLoader,'owner_segments',missing_tail)
    out=tmp_path/'mapping'
    runner.run(out,date(2023,6,30))
    assert len(calls)==60
    assert all(r['status']=='UNAVAILABLE' and r['diagnostic']['stage']=='mapping' for r in json.loads((out/'coverage.json').read_text()))


def test_code_drift_prevents_final_snapshot_and_review_page(harness,monkeypatch,tmp_path):
    monkeypatch.setattr(runner,'observe',lambda *a:iter(()))
    original=Path.read_bytes
    count=0
    def changed(path):
        nonlocal count
        data=original(path)
        if path.resolve()==Path(runner.__file__).resolve():
            count+=1
            if count>1:
                return data+b'changed'
        return data
    monkeypatch.setattr(Path,'read_bytes',changed)
    out=tmp_path/'code-drift'
    with pytest.raises(ValueError,match='RESEARCH_CODE_CHANGED'):
        runner.run(out,date(2023,6,30))
    assert not (out/'index.html').exists() and not (out/'snapshot.json').exists()


def test_saved_snapshot_roundtrip_preserves_original_identity(tmp_path):
    from datetime import datetime,timezone
    from decimal import Decimal
    from app.market_data.new_subing_research import payload_hash
    snapshot={'date':date(2026,10,30),'timestamp':datetime(2026,10,30,7,tzinfo=timezone.utc),'value':Decimal('1.25')}
    path=tmp_path/'snapshot.json'
    runner.dump(path,snapshot)
    assert payload_hash(json.loads(path.read_text()))==payload_hash(snapshot)
