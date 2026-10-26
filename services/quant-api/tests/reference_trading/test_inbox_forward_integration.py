"""Actual capture/reducer/calculation commit through a frozen inbox delivery."""
from datetime import timedelta
from decimal import Decimal

from app.market_data.live_market import _bar_from_payload
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import PreparedBatch
from app.reference_trading.forward_inputs import _bar_wire
from app.reference_trading.forward_service import ForwardReferenceService
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.live_wake import InboxForwardLiveWake
from app.reference_trading.models import ReferenceBatch, ReferenceInboxDelivery
from app.reference_trading.presentation import envelope
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.runtime import ForwardReferenceWorker
from guiyi_quant.reference_trading import CompletedReferenceBar, reduce_reference
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from test_forward_capture import _active
from test_activation import NOW
from test_inbox import event
import json
import os
import pytest


@pytest.mark.parametrize("transport", ["direct", "redis"])
def test_real_capture_calculation_and_delivery_commit_atomically_with_delayed_timing(transport):
    factory, identity, revision, _ = _active()
    repository = ReferenceRepository(factory)
    repository.inbox_enabled = True
    inbox = ReferenceInboxRepository(factory)
    original = event()
    journal = None
    client = None
    if transport == "redis":
        from dataclasses import replace
        from uuid import uuid4
        from urllib.parse import urlparse
        from redis import Redis
        from app.market_data.observation_stream import ObservationStream
        url = os.environ.get("GUIYI_ISOLATED_REDIS_URL")
        if not url:
            pytest.skip("GUIYI_ISOLATED_REDIS_URL required")
        parsed = urlparse(url)
        assert parsed.scheme == 'redis' and parsed.hostname == '127.0.0.1' and parsed.port == 16389
        assert parsed.path == '/11' and not parsed.username and not parsed.password
        namespace = 'test:inbox-integration:' + uuid4().hex + ':'
        day = original.trading_day
        class Journal(ObservationStream):
            def key(self, day):return namespace + super().key(day)
            def cursor_key(self, consumer, day):return namespace + super().cursor_key(consumer, day)
            def registration_key(self, consumer):return namespace + super().registration_key(consumer)
            def days(self):return (day,)
        client = Redis.from_url(url)
        journal = Journal(client, kind='completed')
        journal.initialize('reference', day, cursor='0-0')
        original = replace(original, stream_id=journal.append(original))
    receipt = inbox.ingest(original, ingested_at=NOW + timedelta(seconds=10))
    raw = _bar_from_payload(json.dumps(original.data))
    captures = []
    def read(stream, kind, end):
        capture = ForwardCapture(stream, revision, 1, 'RB2610:'+end.isoformat(), end,
           original.confirmed_at, 'completed_live', {'bar':_bar_wire(raw),'contract':'RB2610'},
           {'owner_segment_id':'owner','calculation_segment_id':'calc'}, 'first_seen')
        captures.append(capture)
        return capture
    def evaluate(token, checkpoint, evidence):
        capture = evidence['forward_capture_v1']
        transition = reduce_reference(checkpoint.reference_state,
           completed_bar=CompletedReferenceBar('RB2610','owner','calc',raw.bar_end,raw.trading_day,Decimal('3500')))
        updated = AdapterCheckpoint(checkpoint.strategy_state,raw.bar_end,capture['hash'],
          'RB2610','owner','calc',identity,transition.state)
        return PreparedBatch(identity.stream_id,revision,'forward:inbox',token,{'source':'fixture'},(),
          (transition,),updated,'newow_product_replay_v1',{'forward_capture_v1':{
             'capture_id':evidence['capture_id'],'hash':capture['hash'],'generation':1},
             'presentation_v1':envelope([])},original.confirmed_at)
    service = ForwardReferenceService(repository,evaluate)
    worker = ForwardReferenceWorker(repository,lambda _:service,read,enabled=True)
    wake = object.__new__(InboxForwardLiveWake)
    wake._inbox,wake._worker = inbox,worker
    wake._after_stream_id=None
    wake._retry_after_by_stream={}
    wake.stop_requested=lambda:False
    wake.request_history=lambda *_:None
    if journal is None:
        wake._calculate_heads()
    else:
        wake._stream = journal
        wake.subscribe()
        wake.poll()
        assert journal.cursor('reference', original.trading_day) == journal.tail(original.trading_day)
    with factory() as db:
        delivery=db.get(ReferenceInboxDelivery,receipt.delivery_ids[0])
        assert delivery.status=='COMPLETED'
        calculation=db.get(ReferenceBatch,delivery.calculation_batch_id)
        assert calculation.kind=='calculation' and calculation.outcome=='committed'
        timing=calculation.source_evidence['delivery_timing_v2']
        assert timing['confirmed_at']==original.confirmed_at.isoformat()
        assert timing['ingested_at']==(NOW+timedelta(seconds=10)).isoformat()
        assert timing['processing_mode']=='delayed_original'
    assert inbox.next_heads()==()
    assert inbox.ingest(original).duplicate
    assert len(captures)==1

    if client is not None:
        keys = list(client.scan_iter(match=namespace + '*'))
        if keys:
            client.delete(*keys)
        client.close()
