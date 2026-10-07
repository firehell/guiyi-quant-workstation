from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import pandas as pd
import pyarrow.parquet as pq
import pytest
from app.market_data import rqdata_adapter as adapter
from app.market_data.domain import DatasetKey, ContractError
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
END=datetime(2023,6,8,13,3,tzinfo=UTC)
DAY=date(2023,6,9)
def row():
 return dict(order_book_id='PP2405',datetime='2023-06-08 21:03:00',trading_date='2023-06-09',open=6910.,high=6890.,low=6890.,close=6890.,volume=1.,total_turnover=34525.,open_interest=1684.)
def fetch(source,end=END,day=DAY,contract='PP2405'):
 class Client:
  def price(self,*args):return pd.DataFrame([source])
 service=adapter.RQDataMarketAdapter(session=None,client=Client())
 return service._minute_bars(DatasetKey('contract','pp',contract,'1m'),(end,),(day,))[0]
def test_exact_source_only_high_is_corrected_and_input_preserved():
 source=row();before=dict(source);bar=fetch(source)
 assert bar.high==bar.open==Decimal('6910')
 assert bar.low==bar.close==Decimal('6890')
 assert (bar.volume,bar.turnover,bar.open_interest)==(Decimal('1'),Decimal('34525'),Decimal('1684'))
 assert source==before
@pytest.mark.parametrize('field,value',[('order_book_id','PP2505'),('datetime','2023-06-08 21:04:00')])
def test_no_general_envelope_repair(field,value):
 source=row();source[field]=value
 end=END+timedelta(minutes=1) if field=='datetime' else END
 contract=source['order_book_id']
 with pytest.raises(ContractError):fetch(source,end=end,contract=contract)
@pytest.mark.parametrize('field,value',[('open',6911),('high',6889),('low',6889),('close',6889),('volume',2),('total_turnover',34526),('open_interest',1685),('trading_date','2023-06-08')])
def test_target_source_drift_rejected(field,value):
 source=row();source[field]=value
 with pytest.raises(Exception):fetch(source,day=date(2023,6,8) if field=='trading_date' else DAY)
def test_supplier_already_matching_approved_shape_is_unchanged():
 source=row();source['high']=6910;bar=fetch(source);assert bar.high==Decimal('6910')
def test_unscoped_converter_stays_strict():
 with pytest.raises(ContractError):adapter._canonical_bar(row(),END,DAY)
def test_correction_policy_is_preserved_in_immutable_parquet(tmp_path):
 bar=fetch(row());key=DatasetKey('contract','pp','PP2405','1m')
 request=PublishRequest(key,2023,6,(bar,),(END,))
 store=CanonicalMonthlyStore(tmp_path);published=store.publish(request)
 metadata=pq.ParquetFile(published.parquet_path).schema_arrow.metadata
 policy=json.loads(metadata[b'guiyi.approved_local_ohlc_policy'])
 assert policy['rule_id']=='pp2405-20230608T210300-high-equals-open-v1'
 assert policy['authority']=='owner_approved_local_correction'
 assert policy['original']['high']=='6890' and policy['corrected']['high']=='6910'
 assert store.publish(request).parquet_path==published.parquet_path

@pytest.mark.parametrize('field,value',[('datetime','2023-06-08 21:03:00.000000001'),('open_oi',999),('close_oi',999),('open_oi','Infinity'),('close_oi','NaN')])
def test_exact_raw_timestamp_and_all_oi_aliases_required(field,value):
 source=row();source[field]=value
 with pytest.raises(ContractError) as error:fetch(source)
 assert error.value.facts['field']=='approved_local_correction'
 assert error.value.facts['reason']=='source_preimage_mismatch'
