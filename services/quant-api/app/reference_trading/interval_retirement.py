"""Owner-selected retirement of the Nov-16 unprovable observation interval.

No absence claim, historical replay, synthetic fill or notification is produced.
Old originals remain immutable; an independently verified terminal closes their
ordering obligations, while new identities accept only their declared first H1.
"""
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import batched
import json

from sqlalchemy import select, text

from app.reference_trading.formula_transition import (
    INTERVAL_VERSION, RETIREMENTS, _row, require, retired_proof,
)
from app.reference_trading.models import (
    ReferenceActivationReceipt, ReferenceBatch, ReferenceInboxDelivery,
    ReferenceInboxInput, ReferenceRevision, ReferenceStream, ReferenceTradeRow,
)
from app.reference_trading.newow_bootstrap import SCHEMAS, _aware, _hash
from app.reference_trading.newow_h1_boundary import NewowH1Boundary
from app.reference_trading.recording_scope import H1_INTERVAL_POLICY
from app.reference_trading.repository import _identity_from_row, _aware as _db_aware, _wire
from guiyi_quant.newow.fusion_reference import FusionReferenceReplayState
from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json, retirement_reference_from_json,
)

INVENTORY_SHA256 = "f9a665381ade5a0523ab40b171519d87a42ea7a0983d540b791bcfaa659c40ad"
JD_INVENTORY_SHA256 = "c5655b04956064f727a0a652ccecabde98ad294d63ac070abbe4e135cd5b859b"
JD_MISSING_H1 = datetime(2026, 11, 20, 2, tzinfo=UTC)
HEALTH = "INTERVAL_RETIRED"
PREFIX = RETIREMENTS[HEALTH][1]
MAX_DELIVERIES = 120000


def _empty(identity):
    return (FusionReferenceReplayState() if identity.strategy_code == "newow_dual_fusion"
            else seed_replay_state())


def _immutable_row(row):
    return {c.name: _wire(_db_aware(v) if isinstance(v, datetime) else v)
            for c in row.__table__.columns for v in (getattr(row, c.name),)}


def _deliveries(db, stream_ids, *, active=False):
    """One bounded snapshot including frozen routing, never a disabled bypass."""
    from app.reference_trading.inbox import _verified_input, _route_identity, _digest, _validate_active
    rows = db.execute(select(ReferenceInboxDelivery, ReferenceInboxInput).join(
        ReferenceInboxInput, ReferenceInboxInput.input_id == ReferenceInboxDelivery.input_id,
    ).where(ReferenceInboxDelivery.stream_id.in_(stream_ids),
            ReferenceInboxDelivery.status != "COMPLETED")
        .order_by(ReferenceInboxDelivery.delivery_id).limit(MAX_DELIVERIES + 1)).all()
    require(len(rows) <= MAX_DELIVERIES, "INTERVAL_RETIREMENT_BUDGET")
    input_ids = {item.input_id for _, item in rows}
    routes = defaultdict(list)
    for ids in batched(sorted(input_ids), 4096):
        for route in db.scalars(select(ReferenceInboxDelivery).where(
                ReferenceInboxDelivery.input_id.in_(ids)).order_by(ReferenceInboxDelivery.stream_id)):
            routes[route.input_id].append(route)
    verified, result = set(), defaultdict(list)
    for row, item in rows:
        require(row.status != "UNKNOWN" and row.unknown_at is None,
                "INTERVAL_RETIREMENT_UNKNOWN")
        if active:
            _validate_active(db, row, lock=False)
            stream = db.get(ReferenceStream, row.stream_id)
            require(item.product == stream.product and item.frequency == stream.frequency and
                    row.delivery_id == _digest([item.trading_day.isoformat(), item.journal_id, stream.stream_id]) and
                    _db_aware(item.bar_end) <= _db_aware(item.confirmed_at) <= _db_aware(item.ingested_at) and
                    _db_aware(item.bar_end) >= _db_aware(stream.recording_start),
                    'INTERVAL_RETIREMENT_ORIGINAL_IDENTITY')
        if item.input_id not in verified:
            _verified_input(item)
            peers = routes[item.input_id]
            require(len(peers) == item.target_count and
                    _digest([_route_identity(v) for v in peers]) == item.routing_sha256,
                    "INTERVAL_RETIREMENT_ROUTING")
            verified.add(item.input_id)
        result[row.stream_id].append({
            "delivery_id": row.delivery_id, "input_id": item.input_id,
            "original_sha256": _hash({"delivery": _row(row), "input": _row(item)}),
        })
    return dict(result)


def _jd_originals(db, deliveries):
    # Approval binds immutable inputs and targets. The frozen, parked plan
    # separately binds the full delivery state, including mutable diagnostics.
    return [
        {"delivery_id": row["delivery_id"], "input_id": row["input_id"],
         "envelope_sha256": db.get(ReferenceInboxInput, row["input_id"]).envelope_sha256}
        for row in deliveries
    ]


class NewowIntervalRetirement(NewowH1Boundary):
    retired_health = HEALTH
    version, batch_prefix, reason, codes = RETIREMENTS[HEALTH]
    seed_manifest_key = INTERVAL_VERSION
    policy_version = H1_INTERVAL_POLICY

    def __init__(self, factory, *, inventory, first_endpoint, assert_fenced,
                 clock=lambda: datetime.now(UTC), jd=False):
        super().__init__(factory, assert_fenced=assert_fenced)
        require(inventory.get("kind") == "READ_ONLY_INVENTORY_NOT_EXECUTION_PLAN",
                "INTERVAL_RETIREMENT_INVENTORY")
        self.inventory_sha256 = JD_INVENTORY_SHA256 if jd else INVENTORY_SHA256
        self.stream_count = 4 if jd else 236
        require(sha256(json.dumps(inventory, ensure_ascii=False, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest() == self.inventory_sha256,
                "INTERVAL_RETIREMENT_INVENTORY_HASH")
        self.inventory = {v["stream_id"]: v for v in inventory["affected_scope"]}
        products = {v["product"] for v in self.inventory.values()}
        require(len(self.inventory) == len(inventory["affected_scope"]) == self.stream_count
                and all(v["frequency"] == "60m" for v in self.inventory.values())
                and (products == {"jd"} if jd else len(products) == 59 and "jd" not in products),
                "INTERVAL_RETIREMENT_SCOPE")
        self.jd = jd
        self.first_endpoint, self.clock = first_endpoint, clock

    def _old(self, db, stream_id, *, lock=False):
        frozen, data = super()._old(db, stream_id, lock=lock)
        row, _, batch, _, identity, reference = data
        expected = self.inventory.get(stream_id)
        require(expected is not None and identity.recording_mode is RecordingMode.FORWARD_OBSERVATION and
                row.frequency == "60m" and
                (row.active_revision_id, row.activation_generation, row.row_version,
                 batch.batch_id, sha256(batch.checkpoint_text.encode()).hexdigest()) ==
                (expected["revision"], expected["generation"], expected["row_version"],
                 expected["checkpoint_id"], expected["checkpoint_sha256"]),
                "INTERVAL_RETIREMENT_INVENTORY_DRIFT")
        cp = adapter_checkpoint_from_json(batch.checkpoint_text, expected_stream=identity,
                                         expected_strategy_schema=batch.strategy_schema)
        if cp.computed_through is None:
            require(batch.kind == "seed_seal" and batch.seq == 1 and
                    cp.strategy_state == _empty(identity) and
                    reference == ReferenceState.flat(identity, recording_start=_db_aware(row.recording_start)),
                    "INTERVAL_RETIREMENT_EMPTY_SEED")
        frozen["all_trades_sha256"] = _hash([_row(t) for t in db.scalars(
            select(ReferenceTradeRow).where(ReferenceTradeRow.stream_id == stream_id)
            .order_by(ReferenceTradeRow.revision_id, ReferenceTradeRow.trade_id,
                      ReferenceTradeRow.valid_from_seq))])
        frozen["deliveries"] = _deliveries(db, (stream_id,), active=True).get(stream_id, [])
        if self.jd:
            require(_jd_originals(db, frozen["deliveries"]) == expected["deliveries"]
                    and len(frozen["deliveries"]) == 4
                    and int(reference.open_trade is not None) == expected["open_count"],
                    "INTERVAL_RETIREMENT_INVENTORY_DRIFT")
        return frozen, data

    def _freeze(self, db, stream_ids, *, start, expiry, at):
        require(set(stream_ids) == set(self.inventory) and len(stream_ids) == self.stream_count and
                at < expiry <= start, "INTERVAL_RETIREMENT_SCOPE")
        if self.jd:
            require(not db.scalar(select(ReferenceInboxInput.input_id).where(
                ReferenceInboxInput.product == "jd", ReferenceInboxInput.frequency == "60m",
                ReferenceInboxInput.bar_end == JD_MISSING_H1,
            ).limit(1)), "INTERVAL_RETIREMENT_ORIGINAL_FOUND")
        products = {v['product'] for v in self.inventory.values()}
        enabled = set(db.scalars(select(ReferenceStream.stream_id).where(
            ReferenceStream.enabled.is_(True), ReferenceStream.product.in_(products),
            ReferenceStream.frequency == '60m', ReferenceStream.strategy_code.in_(self.codes),
            ReferenceStream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value)))
        require(enabled == set(stream_ids), 'INTERVAL_RETIREMENT_DUPLICATE_ROUTE')
        originals = _deliveries(db, stream_ids, active=True)
        items, endpoints = [], {}
        for sid in sorted(stream_ids):
            frozen, (row, _, _, receipt, identity, _) = self._old(db, sid)
            require(originals.get(sid), "INTERVAL_RETIREMENT_NO_HEAD")
            # Every unfinished route must belong to the frozen active interval.
            require(not db.scalar(select(ReferenceInboxDelivery.delivery_id).where(
                ReferenceInboxDelivery.stream_id == sid,
                ReferenceInboxDelivery.status != "COMPLETED",
                (ReferenceInboxDelivery.revision_id != row.active_revision_id) |
                (ReferenceInboxDelivery.generation != row.activation_generation) |
                (ReferenceInboxDelivery.activation_receipt_id != receipt.receipt_id),
            ).limit(1)), "INTERVAL_RETIREMENT_ROUTE_DRIFT")
            require(frozen["deliveries"] == originals[sid], "INTERVAL_RETIREMENT_ORIGINAL_DRIFT")
            target = replace(identity, observation_policy_version=self.policy_version)
            require(db.get(ReferenceStream, target.stream_id) is None,
                    "INTERVAL_RETIREMENT_TARGET_EXISTS")
            if row.product not in endpoints:
                endpoints[row.product] = self.first_endpoint(db, row.product, start)
            endpoint = endpoints[row.product]
            first = _aware(datetime.fromisoformat(endpoint["bar_end"]))
            require(first >= start and endpoint["product"] == row.product,
                    "INTERVAL_RETIREMENT_FIRST_ENDPOINT")
            budget = {k: receipt.budget.get(k) for k in ("max_pending_keys", "max_units_per_round")}
            require(all(type(v) is int and 0 < v <= cap
                        for v, cap in zip(budget.values(), (512, 32), strict=True)),
                    "INTERVAL_RETIREMENT_BUDGET")
            bootstrap = dict(old_stream_id=sid, target_stream_id=target.stream_id,
                expected_first_bar_end=first.isoformat(), expires_at=expiry.isoformat(),
                host=receipt.host, environment=receipt.environment, budget=budget,
                session_proof=endpoint, inventory_sha256=self.inventory_sha256)
            items.append(dict(old=frozen, bootstrap={**bootstrap, "plan_hash": _hash(bootstrap)}))
        groups = defaultdict(set)
        for i in items:
            groups[i["old"]["stream"]["product"]].add(i["old"]["stream"]["strategy_code"])
        require(all(v == self.codes for v in groups.values()), "INTERVAL_RETIREMENT_SCOPE")
        body = dict(version=self.version, items=items, recording_start=start.isoformat(),
                    expires_at=expiry.isoformat(), inventory_sha256=self.inventory_sha256)
        return {**body, "plan_hash": _hash(body)}

    def _boundary_owner(self, batch, at):
        if batch.computed_through is None:
            # _old has independently proved an exact pristine, flat empty seed.
            return (None, None, None)
        return super()._boundary_owner(batch, at)

    def _terminal_checkpoint(self, batch, transition, owner, identity, at, key):
        market_end = _db_aware(batch.computed_through) if batch.computed_through else None
        return AdapterCheckpoint(transition.state, market_end, key if market_end else None,
                                 *owner, identity, transition.state)

    def _terminal_fields(self, at):
        return dict(computed_through=None, observed_at=None)

    def _proof_extras(self, db, item, result):
        target = db.get(ReferenceStream, result["target_stream_id"])
        receipt = db.scalar(select(ReferenceActivationReceipt).where(
            ReferenceActivationReceipt.stream_id == target.stream_id,
            ReferenceActivationReceipt.generation == 1))
        seed_id = db.get(ReferenceRevision,
            (target.stream_id, target.active_revision_id)).checkpoint_batch_id
        seed = db.get(ReferenceBatch, seed_id)
        chunks = db.scalars(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == target.stream_id,
            ReferenceBatch.revision_id == target.active_revision_id,
            ReferenceBatch.kind == 'seed_chunk').order_by(ReferenceBatch.seed_chunk_index)).all()
        return dict(interval_inventory=item["old"], inventory_sha256=self.inventory_sha256,
                    target_seed_id=seed_id, target_seed_sha256=_hash(_immutable_row(seed)),
                    target_receipt_id=receipt.receipt_id,
                    target_receipt=_immutable_row(receipt),
                    target_chunks_sha256=_hash([_immutable_row(c) for c in chunks]),
                    bootstrap_sha256=item["bootstrap"]["plan_hash"])

    def _before_commit(self, db, plan):
        self.assert_fenced()
        current = (db.scalar(text("SELECT clock_timestamp()"))
                   if db.get_bind().dialect.name == "postgresql" else self.clock())
        require(_aware(current) < datetime.fromisoformat(plan["expires_at"]) <=
                datetime.fromisoformat(plan["recording_start"]),
                "INTERVAL_RETIREMENT_EXPIRED_DURING_COMMIT")

    def _status(self, db, plan):
        terminals = db.scalars(select(ReferenceBatch).where(
            ReferenceBatch.batch_key == PREFIX + plan['plan_hash'])).all()
        if not terminals:
            return None
        expected = {i['old']['stream']['stream_id'] for i in plan['items']}
        require({b.stream_id for b in terminals} == expected and len(terminals) == self.stream_count,
                'INTERVAL_RETIREMENT_PARTIAL_COMMIT')
        from app.reference_trading.inbox_recovery import verified_resolution_ids
        resolved = verified_resolution_ids(db, stream_ids=tuple(expected))
        frozen = {v['delivery_id'] for i in plan['items'] for v in i['old']['deliveries']}
        require(set(resolved) == frozen, 'INTERVAL_RETIREMENT_RESOLUTION_DRIFT')
        return dict(status='COMMITTED', plan_hash=plan['plan_hash'], retired=sorted(expected),
                    retired_originals=len(resolved))


def first_session_endpoint(db, product, cut, *, data_root):
    """Freeze time and authority only; no future prices or observed Bar claim."""
    from zoneinfo import ZoneInfo
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.market_data.aggregation import expected_intraday_ends
    catalog = MarketCatalog(db, data_root)
    market = MarketDataService(catalog, CanonicalMonthlyStore(data_root))
    day = cut.astimezone(ZoneInfo("Asia/Shanghai")).date()
    calendar = dict(catalog.calendar_days(product, day, day + timedelta(days=7)))
    for offset in range(8):
        candidate = day + timedelta(days=offset)
        require(candidate in calendar, 'INTERVAL_RETIREMENT_CALENDAR_INCOMPLETE')
        opened = calendar[candidate]
        if not opened:
            continue
        windows = market.session_windows(symbol=product, trading_day=candidate)
        future = [end for end in expected_intraday_ends(windows, '60m') if end >= cut]
        if future:
            return dict(product=product, trading_day=str(candidate), bar_end=min(future).isoformat(),
                        metadata_sha256=_hash(market.historical_metadata_evidence(
                            symbol=product, since=day, through=candidate)))
    require(False, "INTERVAL_RETIREMENT_SESSION_MISSING")


def retired_interval_delivery_ids(db, *, stream_ids=None, check_cancelled=lambda: None):
    """Verified terminal obligations, never recovered or COMPLETED observations."""
    query = select(ReferenceBatch).where(ReferenceBatch.batch_key.like(PREFIX + '%'))
    if stream_ids is not None:
        query = query.where(ReferenceBatch.stream_id.in_(stream_ids))
    terminals = db.scalars(query.order_by(ReferenceBatch.stream_id)).all()
    if not terminals:
        return ()
    originals = _deliveries(db, [b.stream_id for b in terminals])
    result = []
    for batch in terminals:
        check_cancelled()
        row = db.get(ReferenceStream, batch.stream_id)
        proof = retired_proof(db, row)
        expected_inventory = JD_INVENTORY_SHA256 if row is not None and row.product == "jd" else INVENTORY_SHA256
        require(proof is not None and proof['inventory_sha256'] == expected_inventory and
                batch.computed_through is None and batch.observed_at is None and
                not batch.projected_action_pks and
                db.get(ReferenceRevision, (row.stream_id, row.active_revision_id)).checkpoint_batch_id == batch.batch_id and
                batch.source_evidence[INTERVAL_VERSION] == {k:v for k,v in proof.items() if k != 'retired_seq'},
                "INTERVAL_RETIREMENT_INVALID")
        old = proof['interval_inventory']
        if row.product == "jd":
            require(row.frequency == "60m" and len(old['deliveries']) == 4,
                    "INTERVAL_RETIREMENT_INVALID")
        receipt_old = db.get(ReferenceActivationReceipt, old['receipt']['receipt_id'])
        require(receipt_old is not None and receipt_old.disabled_at is not None and
                {**_row(receipt_old), 'disabled_at':old['receipt']['disabled_at']} == old['receipt'] and
                _db_aware(receipt_old.disabled_at).isoformat() == proof['boundary_at'],
                'INTERVAL_RETIREMENT_RECEIPT_DRIFT')
        require(originals.get(row.stream_id) == old['deliveries'], "INTERVAL_RETIREMENT_ORIGINAL_DRIFT")
        prior = db.get(ReferenceBatch, old['revision']['checkpoint_batch_id'])
        require(prior is not None and prior.post_state_hash == old['checkpoint_sha256'] and
                sha256(prior.checkpoint_text.encode()).hexdigest() == prior.post_state_hash and
                batch.pre_state_hash == prior.post_state_hash and batch.expected_seq == prior.seq and
                batch.seq == prior.seq + 1, "INTERVAL_RETIREMENT_CHECKPOINT_DRIFT")
        before = db.execute(select(ReferenceBatch.batch_id, ReferenceBatch.payload_hash,
            ReferenceBatch.post_state_hash, ReferenceBatch.consumed_by_batch_id).where(
                ReferenceBatch.stream_id == row.stream_id, ReferenceBatch.batch_id != batch.batch_id)
            .order_by(ReferenceBatch.batch_id)).all()
        require(_hash([list(v) for v in before]) == old['batches_sha256'], "INTERVAL_RETIREMENT_BATCH_DRIFT")
        trades = db.scalars(select(ReferenceTradeRow).where(ReferenceTradeRow.stream_id == row.stream_id)
            .order_by(ReferenceTradeRow.revision_id, ReferenceTradeRow.trade_id,
                      ReferenceTradeRow.valid_from_seq)).all()
        original_trades, appended, closed = [], [], []
        for trade in trades:
            wire = _row(trade)
            if trade.revision_id == batch.revision_id and trade.valid_from_seq == batch.seq:
                appended.append(wire)
                continue
            if trade.revision_id == batch.revision_id and trade.valid_to_seq == batch.seq:
                require(trade.status == 'OPEN', "INTERVAL_RETIREMENT_TRADE_DRIFT")
                wire['valid_to_seq'] = 'None'
                closed.append(wire)
            original_trades.append(wire)
        require(_hash(original_trades) == old['all_trades_sha256'] and len(appended) == len(closed),
                "INTERVAL_RETIREMENT_TRADE_DRIFT")
        original_ref = retirement_reference_from_json(prior.checkpoint_text,
            expected_stream=_identity_from_row(row), expected_strategy_schema=prior.strategy_schema)
        require(len(appended) == int(original_ref.open_trade is not None),
                'INTERVAL_RETIREMENT_TRADE_DRIFT')
        for before, after in zip(closed, appended, strict=True):
            require(after == {**before, 'valid_from_seq': str(batch.seq), 'valid_to_seq': 'None',
                    'status': 'OBSERVATION_INTERRUPTED', 'effective_bar_end': str(batch.processed_at),
                    'holding_bars':str(original_ref.open_trade.holding_bars),
                    'observed_at': str(batch.processed_at)}, "INTERVAL_RETIREMENT_TRADE_DRIFT")
        target = db.get(ReferenceStream, proof['new_stream_id'])
        seed = db.get(ReferenceBatch, proof['target_seed_id'])
        receipt = db.get(ReferenceActivationReceipt, proof['target_receipt_id'])
        require(target is not None and _identity_from_row(target) == replace(
                    _identity_from_row(row), observation_policy_version=H1_INTERVAL_POLICY) and
                target.product == row.product and target.strategy_code == row.strategy_code and
                seed is not None and seed.stream_id == target.stream_id and seed.kind == 'seed_seal' and
                seed.computed_through is None and seed.observed_at is None and
                receipt is not None and receipt.stream_id == target.stream_id and
                receipt.revision_id == seed.revision_id and receipt.generation == 1 and
                _db_aware(receipt.recording_start).isoformat() == proof['recording_start'] and
                seed.dependency_manifest[INTERVAL_VERSION]['plan_hash'] == proof['bootstrap_sha256'],
                "INTERVAL_RETIREMENT_SEED_DRIFT")
        bootstrap = seed.dependency_manifest[INTERVAL_VERSION]
        require(_hash({k:v for k,v in bootstrap.items() if k != 'plan_hash'}) ==
                bootstrap['plan_hash'] == proof['bootstrap_sha256']
                and bootstrap['inventory_sha256'] == expected_inventory, 'INTERVAL_RETIREMENT_BOOTSTRAP_DRIFT')
        current_receipt = _immutable_row(receipt)
        require({**current_receipt, 'disabled_at':proof['target_receipt']['disabled_at']} ==
                proof['target_receipt'] and
                (receipt.disabled_at is None or _db_aware(receipt.disabled_at) >= _db_aware(receipt.activated_at)) and
                _hash(_immutable_row(seed)) == proof['target_seed_sha256'],
                'INTERVAL_RETIREMENT_SEED_DRIFT')
        chunks = db.scalars(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == target.stream_id,
            ReferenceBatch.revision_id == seed.revision_id,
            ReferenceBatch.kind == 'seed_chunk').order_by(ReferenceBatch.seed_chunk_index)).all()
        require(_hash([_immutable_row(c) for c in chunks]) == proof['target_chunks_sha256'] and
                len(chunks) == 1 and chunks[0].seed_root_hash == seed.post_state_hash and
                chunks[0].seed_chunk_text == seed.checkpoint_text and
                seed.source_evidence.get('seed_root_hash') == seed.post_state_hash,
                'INTERVAL_RETIREMENT_SEED_DRIFT')
        identity = _identity_from_row(target)
        cp = adapter_checkpoint_from_json(seed.checkpoint_text, expected_stream=identity,
                                         expected_strategy_schema=SCHEMAS[row.strategy_code.removeprefix('newow_')])
        require(sha256(seed.checkpoint_text.encode()).hexdigest() == seed.post_state_hash and
                cp.computed_through is None and cp.strategy_state == _empty(identity) and
                cp.reference_state == ReferenceState.flat(identity, recording_start=_db_aware(receipt.recording_start)),
                "INTERVAL_RETIREMENT_SEED_DRIFT")
        result.extend(v['delivery_id'] for v in old['deliveries'])
    require(len(result) == len(set(result)) <= MAX_DELIVERIES, "INTERVAL_RETIREMENT_BUDGET")
    return tuple(result)
