"""Single-account, offline-only forward host for P2 completed decisions."""

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from threading import RLock
from uuid import uuid4

from app.market_data.newow.v2_completed import (
    Admission, CompletedStream, MarketWindow, consume_completed, from_observation,
    read_next_published_input,
)
from app.market_data.newow.v2_scope import (
    Deployment, Scope, physical_subscription_count, validate_formal_scope, validate_scope,
)
from app.market_data.product_retirement import normalize_symbol
from guiyi_quant.newow.decision_adapter import ExecutionContext, MarketSource, V2Strategy, seed_decision_state
from guiyi_quant.newow.decision_checkpoint import decode_decision_checkpoint, encode_decision_checkpoint
from guiyi_quant.newow.product_contracts import ActionKind

from gateway import (
    FixtureGateway, NativeFill, NativeOrder, OrderStatus, Quote, Snapshot, VeighNaOfflineGateway,
    aware, contract_product, identity, lots,
)
from recovery import active, invalidate, native_key, open_obligations, reconcile_snapshot, record_fill, record_order
from risk import ContractPolicy, HostConfig, ManagementPermit, account_fresh, budget, fresh, timestamp
from store import TradingStore, digest, wire


def initial_state():
    return dict(revision=None, config_ref=None, market=[], requested_market=[], market_rank={},
                owners={}, policies={}, streams={}, staged={}, intents={}, clears={}, orders={},
                order_generations={}, fills={}, quotes={}, native=None, generation=None, readback_id=None,
                last_callback_at=None, readback_started_at=None, last_invalidation_at=None,
                trading_day=None, watermark=0, verified_until=None, status='RECONCILING',
                reason='P5_STARTUP_READBACK_REQUIRED', native_conflict=False)


class TradingHost:
    def __init__(self, dsn: str, config: HostConfig, gateway: FixtureGateway):
        if type(gateway) not in (FixtureGateway, VeighNaOfflineGateway):
            raise ValueError('P5_OFFLINE_GATEWAY_REQUIRED')
        self.store = TradingStore(dsn, config.alias)
        self.config = config
        self.gateway = gateway
        self._dispatch_lock = RLock()

    def __enter__(self):
        self.store.__enter__()
        try:
            with self.store.transaction() as (state, journal):
                if not state:
                    state.update(initial_state())
                config_ref = digest({
                    'market_generation': self.config.market_generation,
                    'market_age_us': self.config.market_age // timedelta(microseconds=1),
                    'isolated_capacity': self.config.isolated_capacity,
                    'limits': None if self.config.limits is None else {
                        key: int(value / timedelta(microseconds=1)) if isinstance(value, timedelta) else value
                        for key, value in asdict(self.config.limits).items()
                    },
                })
                if state['config_ref'] and state['config_ref'] != config_ref:
                    raise ValueError('P5_HOST_CONFIGURATION_CONFLICT')
                state['config_ref'] = config_ref
                state['readback_id'] = None
                invalidate(state, 'P5_STARTUP_READBACK_REQUIRED')
                for policy in state['policies'].values():
                    self.gateway.register_contract(policy)
                for intent in state['intents'].values():
                    if intent['state'] == 'PLANNED':
                        self._expire(journal, intent, 'P5_RESTART_EXPIRED')
                    if intent['state'] in {'CLAIMED', 'CANCEL_CLAIMED'}:
                        intent['state'] = 'UNKNOWN' if intent['state'] == 'CLAIMED' else 'CANCEL_UNKNOWN'
                        journal.record('orders', f"{intent['id']}:{intent['state']}", self._intent_row(intent))
                for key in sorted(state['staged']):
                    self._finish_build(state, journal, state['staged'][key], None, 'P5_RESTART_EXPIRED')
                state['staged'].clear()
                state['quotes'].clear()
                state['order_generations'].clear()
        except BaseException:
            self.store.__exit__()
            raise
        return self

    def __exit__(self, *_):
        with self._dispatch_lock:
            try:
                with self.store.transaction() as (state, _journal):
                    invalidate(state, 'P5_HOST_STOPPED')
                    state['status'] = 'STOPPED'
            except RuntimeError:
                pass  # A dead database connection already fenced the writer.
            finally:
                self.store.__exit__()

    def status(self):
        with self.store.transaction() as (state, _journal):
            return {key: state[key] for key in ('status', 'reason', 'revision', 'owners', 'watermark')} | {
                'subscriptions': self._subscriptions(state),
            }

    @staticmethod
    def _subscriptions(state):
        contracts = {product: set() for product in state['market']}
        for product, rank in state['market_rank'].items():
            if product in contracts:
                contracts[product].add(rank['contract'])
        for product, entry in state['owners'].items():
            if entry['contract']:
                contracts[product].add(entry['contract'])
        native = state.get('native') or {}
        for row in (*native.get('positions', ()), *state['intents'].values()):
            if row['product'] in contracts and row['quantity'] and ('state' not in row or active(row)):
                contracts[row['product']].add(row['contract'])
        for order in state['orders'].values():
            product = contract_product(order['contract'])
            if product in contracts and not OrderStatus(order['status']).terminal:
                contracts[product].add(order['contract'])
        subscriptions = {product: sorted(values) for product, values in contracts.items()}
        return {'physical_count': physical_subscription_count(
            Scope(state['revision'] or 'offline-empty', tuple(contracts), ()), subscriptions,
        ), 'contracts': subscriptions}

    def activate(self, scope: Scope, *, expected_revision: str | None, supported=(), retired=(), now: datetime | None = None) -> None:
        now = aware(now or datetime.now().astimezone())
        with self.store.transaction() as (state, journal):
            if (state['revision'] != expected_revision or not scope.revision
                    or journal.get('scope', scope.revision)):
                raise ValueError('P5_SCOPE_REVISION_CONFLICT')
            deployments = {entry.product: entry for entry in scope.deployments}
            if len(deployments) != len(scope.deployments) or any(entry.draining for entry in scope.deployments):
                raise ValueError('V2_SCOPE_OWNER_CONFLICT')
            owners = {}
            effective = list(scope.deployments)
            market = list(scope.market_products)
            for product, prior in state['owners'].items():
                candidate = deployments.get(product)
                if candidate is None:
                    effective.append(Deployment(product, prior['strategy'], prior['frequency'], draining=True))
                    if product not in market:
                        market.append(product)
                    owners[product] = dict(prior, phase='DRAINING')
                elif (prior['strategy'], prior['frequency']) == (candidate.strategy, candidate.frequency):
                    if prior['phase'] == 'DRAINING':
                        raise ValueError('P5_OWNER_DRAINING')
                    owners[product] = prior
                else:
                    if (prior['phase'] == 'DRAINING' or open_obligations(state, product)
                            or not account_fresh(state, now)):
                        raise ValueError('P5_OWNER_UNSETTLED')
            validated = Scope(scope.revision, tuple(market), tuple(effective))
            if self.config.isolated_capacity:
                validate_scope(validated, supported=map(normalize_symbol, supported),
                               retired=map(normalize_symbol, retired), isolated=True)
            else:
                validate_formal_scope(validated)
            for product, candidate in deployments.items():
                if product not in owners:
                    owners[product] = dict(strategy=candidate.strategy, frequency=candidate.frequency,
                                           deployment=scope.revision, phase='ACTIVE',
                                           contract=(state['market_rank'].get(product) or {}).get('contract'),
                                           drain_after=None)
            for product, owner in owners.items():
                if (owner['phase'] == 'DRAINING' and owner['drain_after'] is None):
                    owner['drain_after'] = (state.get('native') or {}).get('as_of')
            state.update(revision=scope.revision, market=sorted(market), owners=owners,
                         requested_market=list(scope.market_products))
            state['market_rank'] = {product: rank for product, rank in state['market_rank'].items() if product in market}
            journal.record('scope', scope.revision, {'owners': owners, 'market': state['market']})

    def retire(self, product: str, *, expected_revision: str, new_revision: str, now: datetime):
        aware(now)
        product = normalize_symbol(product)
        with self.store.transaction() as (state, journal):
            owner = state['owners'].get(product)
            native = state.get('native') or {}
            if (state['revision'] != expected_revision or not new_revision or journal.get('scope', new_revision)
                    or not owner or owner['phase'] != 'DRAINING' or not account_fresh(state, now)
                    or not native.get('as_of') or owner['drain_after']
                    and timestamp(native['as_of']) <= timestamp(owner['drain_after'])
                    or open_obligations(state, product)):
                raise ValueError('P5_DRAIN_UNSETTLED')
            del state['owners'][product]
            if product not in state['requested_market']:
                state['market'].remove(product)
                state['market_rank'].pop(product, None)
            state['revision'] = new_revision
            journal.record('scope', new_revision, {'owners': state['owners'], 'market': state['market']})

    def register_policy(self, policy: ContractPolicy) -> None:
        with self.store.transaction() as (state, _journal):
            key = identity(policy.exchange, policy.contract)
            if policy.product not in state['market']:
                raise ValueError('P5_PRODUCT_NOT_CONFIGURED')
            row = wire(policy)
            if state['policies'].get(key, row) != row:
                raise ValueError('P5_CONTRACT_POLICY_CONFLICT')
            self.gateway.register_contract(row)
            state['policies'][key] = row

    def manage_existing(self, permit: ManagementPermit, *, now: datetime) -> None:
        """Record an explicit, bounded fixture reduction for an old or draining contract."""
        aware(now)
        with self.store.transaction() as (state, journal):
            previous = journal.get('management', permit.reference)
            if previous:
                if previous != wire(permit):
                    raise ValueError('P5_MANAGEMENT_PERMIT_CONFLICT')
                return
            owner = state['owners'].get(permit.product)
            if (not self.config.fixture_send_enabled or not self.config.limits or not owner
                    or state['revision'] != permit.revision or state['trading_day'] != permit.trading_day.isoformat()
                    or not permit.approved_at < now <= permit.expires_at
                    or permit.expires_at - permit.approved_at > self.config.limits.signal_age
                    or (owner['phase'] != 'DRAINING' and owner['contract'] in {None, permit.contract})
                    or not self._has_contract_obligation(state, permit.product, permit.contract)
                    or identity(permit.exchange, permit.contract) not in state['policies']):
                raise ValueError('P5_MANAGEMENT_PERMIT_INVALID')
            decision_id = digest([self.store.account, 'management', permit.reference])
            journal.record('management', permit.reference, wire(permit), at=now)
            state['clears'][decision_id] = wire({
                'decision': {
                    'decision_id': decision_id, 'product': permit.product, 'physical_contract': permit.contract,
                    'trading_day': permit.trading_day, 'config_revision': owner['deployment'],
                    'frequency': owner['frequency'], 'strategy': owner['strategy'], 'decision_at': permit.approved_at,
                    'management_ref': permit.reference,
                },
                'product': permit.product, 'session': permit.session, 'expires': permit.expires_at,
                'maximum_close_lots': permit.maximum_close_lots,
            })
        self.advance(now)

    def begin_readback(self, *, generation: str, trading_day, started_at: datetime) -> str:
        aware(started_at)
        readback_id = uuid4().hex
        with self.store.transaction() as (state, journal):
            day = trading_day.isoformat()
            if (not generation or state['trading_day'] and day < state['trading_day']
                    or state['native'] and started_at < timestamp(state['native']['as_of'])):
                raise ValueError('P5_NATIVE_BINDING_INVALID')
            if generation != state['generation']:
                state.update(generation=generation, watermark=0, quotes={}, native_conflict=False, order_generations={})
                state['last_callback_at'] = None
            elif state['trading_day'] and day != state['trading_day']:
                raise ValueError('P5_NATIVE_BINDING_INVALID')
            if state['trading_day'] and day > state['trading_day']:
                state['intents'] = {key: row for key, row in state['intents'].items() if active(row)}
                state['orders'].clear()
                state['fills'].clear()
            state['trading_day'] = day
            state['readback_id'] = readback_id
            state['readback_started_at'] = started_at.isoformat()
            state['order_generations'].clear()
            self._invalidate_prefix(state, journal, 'P5_READBACK_REQUIRED', started_at)
        return readback_id

    def reconcile(self, snapshot: Snapshot) -> bool:
        try:
            with self.store.transaction() as (state, journal):
                if (snapshot.alias != self.config.alias or snapshot.generation != state['generation']
                        or snapshot.trading_day.isoformat() != state['trading_day']
                        or not state['readback_id'] or snapshot.readback_id != state['readback_id']
                        or state['native_conflict']
                        or snapshot.as_of < timestamp(state['readback_started_at'])
                        or state['last_invalidation_at']
                        and snapshot.as_of < timestamp(state['last_invalidation_at'])
                        or state['last_callback_at'] and snapshot.as_of < timestamp(state['last_callback_at'])
                        or state['native'] and snapshot.as_of < timestamp(state['native']['as_of'])
                        or state['native'] and snapshot.as_of == timestamp(state['native']['as_of'])
                        and state['status'] != 'READY'):
                    raise ValueError('P5_READBACK_IDENTITY_CONFLICT')
                previous = state.get('native')
                reason = reconcile_snapshot(state, journal, snapshot)
                if previous and snapshot.as_of == timestamp(previous['as_of']) and previous != state['native']:
                    raise ValueError('P5_READBACK_IDENTITY_CONFLICT')
                record = {'native': state['native'], 'verified': not reason}
                journal.record('readbacks', digest(record), record, at=snapshot.as_of)
                for intent in state['intents'].values():
                    if intent.get('restart_expiry_pending'):
                        del intent['restart_expiry_pending']
                        journal.record('orders', f"{intent['id']}:restart_no_send",
                                       self._intent_row(intent), at=snapshot.as_of)
                for order in snapshot.orders:
                    state['order_generations'][order.key] = snapshot.generation
                limits = self.config.limits
                if reason is None and limits:
                    state.update(status='READY', reason=None,
                                 verified_until=(snapshot.as_of + limits.account_age).isoformat())
                    return True
                self._invalidate_prefix(state, journal, reason or 'P5_RISK_LIMIT_MISSING', snapshot.as_of)
                return False
        except ValueError as error:
            with self.store.transaction() as (state, journal):
                at = max((snapshot.as_of, *(timestamp(state[key]) for key in (
                    'readback_started_at', 'last_callback_at', 'last_invalidation_at',
                ) if state[key])))
                self._invalidate_prefix(state, journal, str(error), at)
            return False

    @staticmethod
    def _invalidate_prefix(state, journal, reason, known_at, *, key=None):
        invalidate(state, reason)
        previous = state['last_invalidation_at']
        if previous is None or known_at > timestamp(previous):
            state['last_invalidation_at'] = known_at.isoformat()
        journal.record('native_updates', key or uuid4().hex, {'verified': False, 'reason': reason}, at=known_at)

    def block(self, reason: str, *, known_at: datetime) -> None:
        aware(known_at)
        with self.store.transaction() as (state, journal):
            self._invalidate_prefix(state, journal, reason, known_at)

    def callback(self, event: NativeOrder | NativeFill, *, generation: str, sequence: int,
                 known_at: datetime) -> None:
        lots(sequence, minimum=1)
        aware(known_at)
        try:
            with self.store.transaction() as (state, journal):
                if generation != state['generation'] or event.trading_day.isoformat() != state['trading_day']:
                    raise ValueError('P5_CALLBACK_IDENTITY_CONFLICT')
                key = f'{generation}:{sequence}'
                if sequence > state['watermark'] + 1:
                    raise ValueError('P5_CALLBACK_GAP')
                journal.record('callbacks', key, {'type': type(event).__name__, 'event': wire(event)},
                               at=known_at)
                if sequence <= state['watermark']:
                    return
                if (state['last_callback_at'] and known_at < timestamp(state['last_callback_at'])
                        or isinstance(event, NativeFill) and event.occurred_at > known_at):
                    raise ValueError('P5_CALLBACK_TIME_INVALID')
                state['watermark'] = sequence
                state['last_callback_at'] = known_at.isoformat()
                changed = (record_fill(state, journal, event) if isinstance(event, NativeFill)
                           else record_order(state, journal, event))
                if isinstance(event, NativeOrder):
                    state['order_generations'][event.key] = generation
                if changed:
                    self._invalidate_prefix(state, journal, 'P5_NATIVE_UPDATE_READBACK_REQUIRED', known_at, key=key)
        except ValueError as error:
            with self.store.transaction() as (state, journal):
                state['native_conflict'] = True
                self._invalidate_prefix(state, journal, str(error), known_at)

    def quote(self, quote: Quote) -> None:
        with self.store.transaction() as (state, _journal):
            if (quote.generation != state['generation'] or quote.trading_day.isoformat() != state['trading_day']):
                raise ValueError('P5_QUOTE_SCOPE_CONFLICT')
            key = identity(quote.exchange, quote.contract)
            prior = state['quotes'].get(key)
            if prior and quote.as_of <= timestamp(prior['as_of']):
                if prior == wire(quote):
                    return
                raise ValueError('P5_QUOTE_CONFLICT')
            state['quotes'][key] = wire(quote)

    def receive_observation(self, envelope, window: MarketWindow, *, generation: str,
                            expected: datetime, now: datetime,
                            verified_lifecycle: bool = False):
        if generation != self.config.market_generation:
            raise ValueError('P5_MARKET_GENERATION_CONFLICT')
        item = from_observation(envelope, window, generation=generation, as_of=now,
                                verified_lifecycle=verified_lifecycle)
        return self.receive_completed(item, window, expected=expected, now=now)

    def receive_publication(self, reader, window: MarketWindow, *, generation: str,
                            expected: datetime, now: datetime,
                            publication, after, prior_owner_segment_id, prior_calculation_segment_id,
                            verified_lifecycle=False):
        if generation != self.config.market_generation:
            raise ValueError('P5_MARKET_GENERATION_CONFLICT')
        item = read_next_published_input(
            reader, window, after=after, as_of=now, generation=generation,
            publication=publication, prior_owner_segment_id=prior_owner_segment_id,
            prior_calculation_segment_id=prior_calculation_segment_id, verified_lifecycle=verified_lifecycle,
        )
        if item is not None:
            return self.receive_completed(item, window, expected=expected, now=now)
        return None

    def receive_completed(self, item, window: MarketWindow, *, expected: datetime, now: datetime):
        """Consume a proved P2 input. `expected` is the next endpoint proved by Market."""
        aware(now)
        aware(expected)
        payload = item.payload
        product, frequency, contract = window.product, window.frequency.value, item.physical_contract
        raw = payload.bar.bar
        session = window.session_for(item.bar_end)
        if (window.contract != contract or window.owner_segment_id != item.owner_segment_id
                or window.owner_ref != payload.owner_ref or window.trading_day != item.trading_day
                or raw.product != product or payload.bar.frequency != frequency
                or payload.session != (session.start, session.end) or expected not in window.endpoints
                or payload.available_at > now or payload.source is MarketSource.CANONICAL and raw.observation_eligible
                or payload.source is MarketSource.OBSERVATION and payload.revision != self.config.market_generation):
            raise ValueError('P5_MARKET_PROOF_CONFLICT')
        with self.store.transaction() as (state, journal):
            if product not in state['market']:
                raise ValueError('P5_PRODUCT_NOT_CONFIGURED')
            owner = state['owners'].get(product)
            selected = owner and owner['frequency'] == frequency
            revision = owner['deployment'] if selected else 'observation-only'
            stream_key = digest([product, frequency, revision, item.owner_segment_id])
            input_key = digest([stream_key, payload.market_key()])
            prior = journal.input_result(input_key)
            entry = state['streams'].get(stream_key)
            stream, core = self._restore_stream(entry)
            if prior and prior['fingerprint'] == item.fingerprint:
                return Admission.DUPLICATE
            staged_key = next((key for key, row in state['staged'].items() if row['stream_key'] == stream_key), None)
            if staged_key:
                stage = state['staged'][staged_key]
                if stage['input_key'] == input_key:
                    if stage['fingerprint'] != item.fingerprint:
                        del state['staged'][staged_key]
                        self._finish_build(state, journal, stage, None, 'P5_MARKET_INPUT_CONFLICT')
                        state['streams'][stream_key]['market']['blocked'] = True
                        return Admission.CONFLICT
                    return Admission.DUPLICATE
                if now <= timestamp(stage['deadline']):
                    raise ValueError('P5_PENDING_MARKET_ENDPOINT')
                self._seal_due(state, journal, now)
                stream, core = self._restore_stream(state['streams'].get(stream_key))
            if stream.through and stream.through in window.endpoints:
                successor = window.next_after(stream.through)
                if item.bar_end > stream.through and expected != successor:
                    raise ValueError('P5_MARKET_EXPECTED_ENDPOINT_CONFLICT')
            if (payload.source is MarketSource.OBSERVATION and stream.scope
                    and stream.scope[0] == MarketSource.CANONICAL and not stream.blocked):
                stream = CompletedStream()
            rank = state['market_rank'].get(product)
            if payload.source is MarketSource.OBSERVATION and rank and rank['contract'] != contract:
                if contract in rank['previous_contracts'] or item.bar_end <= timestamp(rank['bar_end']):
                    raise ValueError('P5_RANK1_REGRESSION')
            limits = self.config.limits
            is_fresh = fresh(now, payload.available_at, self.config.market_age)
            context = self._context(journal, item, owner if selected else None, revision)
            market, decision_state, admission, decisions = consume_completed(
                stream, core, item, context, expected=expected,
                fresh=is_fresh if payload.source is MarketSource.OBSERVATION else None,
                previous_fingerprint=prior['fingerprint'] if prior else None,
            )
            checkpoint = {'market': wire(market), 'core': encode_decision_checkpoint(decision_state)}
            if admission is not Admission.ACCEPTED:
                if market != stream:
                    state['streams'][stream_key] = checkpoint
                journal.record('input_diagnostics', digest([input_key, item.fingerprint, admission]),
                               {'market_key': payload.market_key(), 'status': admission, 'fingerprint': item.fingerprint})
                return admission
            if payload.source is MarketSource.OBSERVATION:
                previous = rank['previous_contracts'] if rank else []
                if rank and rank['contract'] != contract:
                    previous = [*previous, rank['contract']]
                if not rank or item.bar_end >= timestamp(rank['bar_end']):
                    state['market_rank'][product] = {
                        'contract': contract, 'bar_end': item.bar_end.isoformat(), 'previous_contracts': previous,
                    }
                if owner:
                    owner['contract'] = contract
            stage = {'input_key': input_key, 'fingerprint': item.fingerprint, 'stream_key': stream_key,
                     'checkpoint': checkpoint, 'decisions': wire(decisions), 'session': wire(payload.session),
                     'received_at': now.isoformat()}
            decision = next((d for d in decisions if selected and d.strategy == owner['strategy']), None)
            if decision is not None:
                stage['decision'] = wire(decision)
            if decision and decision.main_action is ActionKind.BUILD and decision.execution_candidate:
                deadline = item.bar_end + limits.batch_delay if limits else now
                within_epoch = self._opening_after_readback_boundary(state, payload.available_at)
                # A delayed publication can only be acted on with a common, eligible
                # market cutoff. P5 has no authorization to carry it into a new session.
                if (owner['phase'] == 'ACTIVE' and now < deadline < session.end
                        and within_epoch and account_fresh(state, now)
                        and payload.source is MarketSource.OBSERVATION):
                    stage['deadline'] = deadline.isoformat()
                    stage['exchange'] = self._exchange_for_contract(state, product, contract)
                    state['staged'][input_key] = stage
                    return admission
                reason = 'P5_RISK_INPUT_UNAVAILABLE'
                if not within_epoch:
                    reason = 'P5_SIGNAL_BEFORE_READBACK'
                elif account_fresh(state, now):
                    reason = 'P5_OPENING_WINDOW_CLOSED'
                self._finish_build(state, journal, stage, None, reason)
            else:
                if (decision and decision.main_action is ActionKind.CLEAR and limits
                        and fresh(now, payload.available_at, limits.signal_age)
                        and payload.source is MarketSource.OBSERVATION
                        and (decision.execution_candidate or decision.reason in {
                            'ACCOUNT_PREFIX_UNVERIFIED', 'NO_CONFIRMED_POSITION',
                        } and self._has_contract_obligation(state, product, contract))):
                    clear = {
                        'decision': wire(decision), 'product': product, 'session': stage['session'],
                        'expires': (payload.available_at + limits.signal_age).isoformat(),
                    }
                    if not self._plan_clear(state, journal, clear, now):
                        state['clears'][decision.decision_id] = clear
                self._finish_build(state, journal, stage, None, None)
        self.advance(now)
        return admission

    @staticmethod
    def _restore_stream(entry):
        if not entry:
            return CompletedStream(), seed_decision_state()
        raw = dict(entry['market'])
        for key in ('through', 'available_through'):
            if raw[key]:
                raw[key] = timestamp(raw[key])
        if raw['scope']:
            first, *rest = raw['scope']
            raw['scope'] = (MarketSource(first), *rest)
        return CompletedStream(**raw), decode_decision_checkpoint(entry['core'])

    def _context(self, journal, item, owner, revision):
        at = item.payload.available_at
        prefix = journal.account_prefix(at) if owner else None
        native = prefix['native'] if prefix and prefix['verified'] else None
        product = item.payload.bar.bar.product
        unsettled = {i['contract'] for i in journal.intent_prefix(product, at) if active(i)} if owner else set()
        values = {}
        limits = self.config.limits
        if (native and limits
                and native['trading_day'] == item.trading_day.isoformat()
                and fresh(at, timestamp(native['as_of']), limits.account_age)):
            positions = [p for p in native['positions'] if p['product'] == product and p['quantity']]
            unsettled.update(p['contract'] for p in positions if p['contract'] != item.physical_contract)
            position = sum(p['quantity'] for p in positions if p['contract'] == item.physical_contract)
            values = dict(account_as_of=timestamp(native['as_of']), account_ref=digest(native),
                          fill_prefix_ref=digest(native['fill_keys']), position=Decimal(position),
                          position_contract=item.physical_contract)
        return ExecutionContext(
            self.store.account, revision, tuple(V2Strategy), owner['strategy'] if owner else None,
            unsettled_contracts=tuple(unsettled), **values,
        )

    @staticmethod
    def _has_contract_obligation(state, product, contract):
        native = state.get('native') or {}
        return (any(p['product'] == product and p['contract'] == contract and p['long'] and p['quantity']
                    for p in native.get('positions', ()))
                or any(i['product'] == product and i['contract'] == contract and i['offset'] == 'OPEN'
                       and active(i) for i in state['intents'].values()))

    @staticmethod
    def _finish_build(state, journal, stage, execution, reason):
        journal.record('inputs', stage['input_key'], {'fingerprint': stage['fingerprint']})
        state['streams'][stage['stream_key']] = stage['checkpoint']
        for decision in stage['decisions']:
            is_target = decision['decision_id'] == stage.get('decision', {}).get('decision_id')
            journal.record('decisions', decision['decision_id'], {
                **decision, 'received_at': stage['received_at'],
                'input_fingerprint': stage['fingerprint'],
                'execution': execution if is_target else None,
                'execution_reason': reason if is_target else None,
            })

    def _execution_facts(self, state, decision, session, now, *, opening):
        limits = self.config.limits
        owner = state['owners'].get(decision['product'])
        if not (limits and owner and (owner['deployment'], owner['frequency'], owner['strategy']) == (
            decision['config_revision'], decision['frequency'], decision['strategy'],
        ) and timestamp(session[0]) < now < timestamp(session[1])
            and now > timestamp(decision['decision_at']) and account_fresh(state, now)
            and decision['trading_day'] == state['trading_day']):
            return None
        if opening and (
            owner['phase'] != 'ACTIVE' or owner['contract'] != decision['physical_contract']
            or not self._opening_after_readback_boundary(state, timestamp(decision['decision_at']))
        ):
            return None
        if opening and any(p['quantity'] and identity(p['exchange'], p['contract']) not in state['policies']
                           for p in state['native']['positions']):
            return None
        policies = [p for p in state['policies'].values() if p['contract'] == decision['physical_contract']
                    and p['product'] == decision['product']]
        if len(policies) != 1:
            return None
        policy = policies[0]
        binding = policy['native_binding']
        if binding and not timestamp(binding['at']) <= now <= timestamp(binding['valid_until']):
            return None
        quote = state['quotes'].get(identity(policy['exchange'], policy['contract']))
        if not quote or not fresh(now, timestamp(quote['as_of']), limits.quote_age):
            return None
        price = Decimal(quote['ask'] if opening else quote['bid'])
        if price % Decimal(policy['tick']) != 0:
            return None
        return policy, price

    @staticmethod
    def _opening_after_readback_boundary(state, at):
        previous = state['last_invalidation_at']
        return previous is not None and at >= timestamp(previous)

    @staticmethod
    def _exchange_for_contract(state, product, contract):
        return min((p['exchange'] for p in state['policies'].values()
                    if (p['product'], p['contract']) == (product, contract)), default='')

    @staticmethod
    def _intent_row(intent):
        return {'kind': 'order_intent', **intent}

    def _make_intent(self, state, journal, decision, policy, *, offset, quantity, price, unit, session, now, expires):
        key = digest([self.store.account, decision['decision_id'], offset])
        if key in state['intents']:
            return key
        intent = wire({
            'id': key, 'decision_id': decision['decision_id'], 'offset': offset,
            'quantity': quantity, 'price': price, 'reserved': quantity * unit, 'unit_reserve': unit,
            'product': decision['product'], 'contract': policy['contract'], 'exchange': policy['exchange'],
            'tick': policy['tick'], 'multiplier': policy['multiplier'],
            'native_symbol': policy['native_symbol'], 'state': 'PLANNED', 'native_id': None,
            'trading_day': decision['trading_day'], 'decision': decision, 'session': session,
            'expires': expires, 'created_at': now,
        })
        state['intents'][key] = intent
        journal.record('orders', f'{key}:planned', self._intent_row(intent), at=now)
        return key

    @staticmethod
    def _expire(journal, intent, reason, *, at=None):
        intent.update(state='EXPIRED', reserved='0', reason=reason)
        if at is None:
            intent['restart_expiry_pending'] = True
        journal.record('orders', f"{intent['id']}:expired", {'kind': 'order_intent', **intent}, at=at)

    def _adjudicate(self, state, journal, stage, now):
        decision = stage['decision']
        limits = self.config.limits
        facts = self._execution_facts(state, decision, stage['session'], now, opening=True)
        funds = budget(state, limits) if state.get('native') and limits else None
        outcome = {'risk_version': limits.revision if limits else None, 'budget': wire(funds), 'intent': None}
        reason = 'P5_RISK_INPUT_UNAVAILABLE'
        if facts and fresh(now, timestamp(decision['decision_at']), limits.signal_age):
            policy, price = facts
            positions = state['native']['positions']
            if (any(p['product'] == decision['product'] and p['quantity'] for p in positions)
                    or open_obligations(state, decision['product'])):
                reason = 'P5_EXECUTION_OBLIGATION'
            elif funds['daily_loss'] >= limits.daily_loss_cap:
                reason = 'P5_DAILY_LOSS_LIMIT'
            else:
                unit = price * Decimal(policy['multiplier']) * Decimal(policy['margin_rate']) + Decimal(policy['fee_ceiling'])
                quantity = policy['maximum_lots']
                if quantity * unit > funds['buying_power']:
                    reason = 'P5_SHARED_BUDGET'
                elif not self.config.fixture_send_enabled:
                    reason = 'P5_OBSERVATION_ONLY'
                else:
                    key = self._make_intent(
                        state, journal, decision, policy, offset='OPEN', quantity=quantity, price=price, unit=unit,
                        session=stage['session'], now=now, expires=timestamp(decision['decision_at']) + limits.signal_age,
                    )
                    outcome['intent'], reason = key, 'P5_APPROVED'
        self._finish_build(state, journal, stage, outcome, reason)

    def _plan_clear(self, state, journal, clear, now):
        decision = clear['decision']
        if now > timestamp(clear['expires']):
            journal.record('clear_outcomes', decision['decision_id'], {'reason': 'P5_CLEAR_EXPIRED'})
            return True
        product = decision['product']
        if any(i['product'] == product and active(i) for i in state['intents'].values()):
            return False
        facts = self._execution_facts(state, decision, clear['session'], now, opening=False)
        if not facts or not self.config.fixture_send_enabled:
            return False
        policy, price = facts
        position = self._long_position(state, policy)
        if not position:
            journal.record('clear_outcomes', decision['decision_id'], {'reason': 'P5_ALREADY_FLAT'})
            return True
        legs = self.gateway.close_legs(position | policy)
        if not legs:
            return False
        remaining = clear.get('maximum_close_lots', position['quantity'])
        keys = []
        for offset, quantity in legs:
            quantity = min(remaining, quantity)
            if not quantity:
                break
            keys.append(self._make_intent(
                state, journal, decision, policy, offset=offset, quantity=quantity, price=price, unit=Decimal(0),
                session=clear['session'], now=now, expires=timestamp(clear['expires']),
            ))
            remaining -= quantity
        journal.record('clear_outcomes', decision['decision_id'], {'intents': keys})
        return True

    @staticmethod
    def _long_position(state, policy):
        return next((p for p in state['native']['positions'] if p['long'] and p['quantity']
                     and all(p[key] == policy[key] for key in ('product', 'contract', 'exchange'))), None)

    def _seal_due(self, state, journal, now):
        due = [entry for entry in state['staged'].values() if now > timestamp(entry['deadline'])]
        due.sort(key=lambda entry: (
            timestamp(entry['deadline']), entry['exchange'], entry['decision']['product'],
            entry['decision']['config_revision'],
        ))
        for entry in due:
            self._adjudicate(state, journal, entry, now)
            del state['staged'][entry['input_key']]

    def advance(self, now: datetime) -> None:
        """Seal due opening batches, act on earlier CLEARs, then drain committed intents."""
        aware(now)
        with self._dispatch_lock:
            with self.store.transaction() as (state, journal):
                for key, clear in list(state['clears'].items()):
                    if self._plan_clear(state, journal, clear, now):
                        del state['clears'][key]
                self._seal_due(state, journal, now)
                keys = [i['id'] for i in state['intents'].values() if i['state'] == 'PLANNED']
                cancellations = self._cancel_targets(state, now)
            for key in cancellations:
                with self.store.dispatch_fence():
                    self._cancel(key, now)
            for key in keys:
                with self.store.dispatch_fence():
                    self._dispatch(key, now)

    def _dispatch(self, key, now):
        with self.store.transaction() as (state, journal):
            intent = state['intents'][key]
            if intent['state'] != 'PLANNED':
                return
            opening = intent['offset'] == 'OPEN'
            facts = self._execution_facts(state, intent['decision'], intent['session'], now, opening=opening)
            if (not facts or now > timestamp(intent['expires']) or not self.config.fixture_send_enabled
                    or facts[1] != Decimal(intent['price'])):
                self._expire(journal, intent, 'P5_DISPATCH_PRECONDITION_CHANGED', at=now)
                return
            if opening:
                funds = budget(state, self.config.limits)
                if (funds['buying_power'] < 0 or funds['daily_loss'] >= self.config.limits.daily_loss_cap
                        or any(p['product'] == intent['product'] and p['quantity']
                               for p in state['native']['positions'])):
                    self._expire(journal, intent, 'P5_DISPATCH_BUDGET_CHANGED', at=now)
                    return
            else:
                position = self._long_position(state, facts[0])
                possible = dict(self.gateway.close_legs(position | facts[0])) if position else {}
                if possible.get(intent['offset'], 0) < intent['quantity']:
                    self._expire(journal, intent, 'P5_CLOSE_QUANTITY_CHANGED', at=now)
                    return
            try:
                self.gateway.validate_request(intent)
            except (ValueError, RuntimeError):
                self._expire(journal, intent, 'P5_NATIVE_REQUEST_INVALID', at=now)
                return
            intent.update(state='CLAIMED', claimed_at=now.isoformat())
            journal.record('orders', f'{key}:claimed', self._intent_row(intent), at=now)
            request = intent.copy()
        try:
            native_id = self.gateway.send(request)
            if not isinstance(native_id, str) or not native_id:
                native_id = None
        except Exception:
            native_id = None
        with self.store.transaction() as (state, journal):
            intent = state['intents'][key]
            if native_id and any(i.get('native_id') == native_id and native_key(i, native_id) == native_key(intent, native_id)
                                 for i in state['intents'].values() if i['id'] != key):
                native_id = None
            intent.update(state='SUBMITTED' if native_id else 'UNKNOWN', native_id=native_id,
                          submit_observed_at=now.isoformat())
            journal.record('orders', f'{key}:submit_outcome', self._intent_row(intent), at=now)
            if not native_id:
                self._invalidate_prefix(state, journal, 'P5_SUBMIT_UNKNOWN', now)

    def _cancel_targets(self, state, now):
        if not self.config.fixture_send_enabled or state['native_conflict']:
            return []
        targets = {(c['product'], c['decision']['physical_contract'], c['decision']['config_revision'])
                   for c in state['clears'].values()
                   if timestamp(c['session'][0]) < now < timestamp(c['session'][1])
                   and now <= timestamp(c['expires'])}
        return [i['id'] for i in state['intents'].values()
                if (i['product'], i['contract'], i['decision']['config_revision']) in targets
                and i['offset'] == 'OPEN' and i['state'] in {'NATIVE_ACTIVE', 'SUBMITTED'}
                and self._cancel_order_is_active(state, i)]

    @staticmethod
    def _cancel_order_is_active(state, intent):
        key = native_key(intent, intent.get('native_id'))
        order = state['orders'].get(key)
        return bool(order and intent['trading_day'] == state['trading_day']
                    and state['order_generations'].get(key) == state['generation']
                    and OrderStatus(order['status']) in {OrderStatus.ACTIVE, OrderStatus.PARTIAL})

    def _cancel(self, key, now):
        with self.store.transaction() as (state, journal):
            intent = state['intents'][key]
            if key not in self._cancel_targets(state, now):
                return
            intent.update(state='CANCEL_CLAIMED', cancel_claimed_at=now.isoformat())
            journal.record('orders', f'{key}:cancel_claimed', self._intent_row(intent), at=now)
            request = intent.copy()
        try:
            self.gateway.cancel(request)
        except Exception:
            pass  # The gateway's return cannot prove the native cancellation outcome.
        with self.store.transaction() as (state, journal):
            intent = state['intents'][key]
            intent['state'] = 'CANCEL_UNKNOWN'
            journal.record('orders', f'{key}:cancel_outcome', self._intent_row(intent), at=now)
            self._invalidate_prefix(state, journal, 'P5_CANCEL_READBACK_REQUIRED', now)
