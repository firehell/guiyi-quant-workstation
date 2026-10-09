"""One-shot Newow completed-observation deliveries; never replay history."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, JSON, String, UniqueConstraint, and_, select, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.alerts.notification import NotificationDelivery
from app.alerts.notification_composition import _load_from_env, build_notification_transport_from_env
from app.reference_trading.models import ReferenceActionRow, ReferenceBatch, ReferenceStream, ReferenceRevision
from app.reference_trading.presentation import require_envelope

STRATEGIES = ('newow_trend', 'newow_oscillation', 'newow_main_rise', 'newow_dual_fusion')
FREQUENCIES = ('1w', '1d', '60m')


class NewowNotificationPolicy(Base):
    __tablename__ = 'newow_notification_policies'
    policy_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    topic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    products: Mapped[list] = mapped_column(JSON, nullable=False)
    cursor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_batch_id: Mapped[str | None] = mapped_column(String(96))


class NewowNotificationDelivery(Base):
    __tablename__ = 'newow_notification_deliveries'
    __table_args__ = (UniqueConstraint('stream_id', 'signal_id', name='uq_newow_delivery_signal'),
        Index('ix_newow_delivery_batch_status', 'status', 'batch_id'),
        CheckConstraint("status IN ('BATCH_PROCESSED','ATTEMPTED_UNKNOWN','PROVIDER_ACCEPTED','FAILED_OR_UNKNOWN','EXPIRED_NO_SEND')", name='ck_newow_delivery_status'))
    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(96), nullable=False)
    signal_id: Mapped[str] = mapped_column(String(160), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(96), nullable=False)
    topic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(256))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def configured_topic_hash() -> str:
    config = _load_from_env()
    return sha256(str(config.transport_config['htdy_topic']).encode()).hexdigest()


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('NEWOW_NOTIFICATION_TIME_INVALID')
    if not isinstance(value, datetime):
        raise ValueError('NEWOW_NOTIFICATION_TIME_INVALID')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _notification_origin(batch):
    confirmed = _utc(batch.observed_at)
    timing = batch.source_evidence.get("observation_timing_v1")
    if timing is None:
        return confirmed
    if not isinstance(timing, dict) or set(timing) != {"raw_received_at", "confirmed_at"}:
        raise ValueError("NEWOW_NOTIFICATION_TIMING_INVALID")
    raw = _utc(timing["raw_received_at"])
    if _utc(timing["confirmed_at"]) != confirmed or raw > confirmed:
        raise ValueError("NEWOW_NOTIFICATION_TIMING_INVALID")
    return raw


def enable_newow_notifications(session, *, products, enabled_at, topic_hash=None):
    if not isinstance(enabled_at, datetime) or enabled_at.tzinfo is None or enabled_at.utcoffset() is None:
        raise ValueError('NEWOW_NOTIFICATION_TIME_INVALID')
    values = sorted(set(products))
    if not values or any(not isinstance(x, str) or not x.isalpha() or x != x.lower() for x in values):
        raise ValueError('NEWOW_NOTIFICATION_SCOPE_INVALID')
    topic = topic_hash or configured_topic_hash()
    policy = session.get(NewowNotificationPolicy, 'newow_actions_v1')
    if policy is not None and policy.enabled:
        if policy.products != values or policy.topic_hash != topic:
            raise ValueError('NEWOW_NOTIFICATION_POLICY_CONFLICT')
        return policy
    if policy is None:
        policy = NewowNotificationPolicy(policy_id='newow_actions_v1')
        session.add(policy)
    policy.enabled = True
    policy.enabled_at = _utc(enabled_at)
    policy.topic_hash = topic
    policy.products = values
    policy.cursor_at = None
    policy.cursor_batch_id = None
    session.commit()
    return policy


def notification_status(session):
    policy = session.get(NewowNotificationPolicy, 'newow_actions_v1')
    counts = dict(session.execute(select(NewowNotificationDelivery.status, func.count()).where(NewowNotificationDelivery.status != 'BATCH_PROCESSED').group_by(NewowNotificationDelivery.status)).all())
    return {'deliveries': counts, 'stream_count': len(policy.products) * 12 if policy else 0, 'enabled': bool(policy and policy.enabled), 'enabled_at': policy.enabled_at.isoformat() if policy else None,
            'products': len(policy.products) if policy else 0, 'strategies': list(STRATEGIES), 'frequencies': list(FREQUENCIES)}


class NewowNotificationDispatcher:
    def __init__(self, session_factory, *, transport=None, topic_hash=None, clock=None, assert_owned=None, should_stop=None):
        self.session_factory = session_factory
        self.transport = transport
        self.topic_hash = topic_hash
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.assert_owned = assert_owned or (lambda: None)
        self.should_stop = should_stop or (lambda: False)

    def tick(self, *, limit=200):
        # Session-level PG lock spans claim commits and excludes concurrent cursor advancement.
        with self.session_factory() as probe:
            engine = probe.get_bind()
        if engine.dialect.name != 'postgresql':
            return self._tick(limit=limit)
        with engine.connect() as connection:
            acquired = connection.execute(text('SELECT pg_try_advisory_lock(1852143479, 1)')).scalar()
            connection.commit()
            if not acquired:
                return {'enabled': True, 'processed': 0, 'attempted': 0, 'busy': True}
            try:
                from sqlalchemy.orm import Session
                return self._tick(limit=limit, session_factory=lambda: Session(bind=connection, expire_on_commit=False))
            finally:
                connection.execute(text('SELECT pg_advisory_unlock(1852143479, 1)'))
                connection.commit()

    def _tick(self, *, limit=200, session_factory=None):
        if not 1 <= limit <= 200:
            raise ValueError('NEWOW_NOTIFICATION_BATCH_LIMIT')
        with (session_factory or self.session_factory)() as session:
            policy = session.get(NewowNotificationPolicy, 'newow_actions_v1')
            if policy is None or not policy.enabled:
                return {'enabled': False, 'processed': 0, 'attempted': 0}
            topic = self.topic_hash or configured_topic_hash()
            if topic != policy.topic_hash:
                raise ValueError('NEWOW_NOTIFICATION_TOPIC_CHANGED')
            transport = self.transport or build_notification_transport_from_env()
            query = select(ReferenceBatch, ReferenceStream).join(ReferenceStream, ReferenceBatch.stream_id == ReferenceStream.stream_id).join(ReferenceRevision, and_(ReferenceRevision.stream_id == ReferenceStream.stream_id, ReferenceRevision.revision_id == ReferenceStream.active_revision_id)).where(
                ReferenceStream.recording_mode == 'forward_observation', ReferenceStream.enabled.is_(True),
                ReferenceStream.health == 'READY', ReferenceRevision.status == 'active',
                ReferenceBatch.revision_id == ReferenceStream.active_revision_id,
                ReferenceBatch.seq <= ReferenceStream.latest_seq,
                ReferenceStream.strategy_code.in_(STRATEGIES), ReferenceStream.frequency.in_(FREQUENCIES),
                ReferenceStream.product.in_(policy.products), ReferenceBatch.kind == 'calculation',
                ReferenceBatch.outcome == 'committed', ReferenceBatch.processed_at > policy.enabled_at)
            # A pre-commit processed_at is not a commit watermark. Persist per-batch
            # receipts so later commits with older timestamps are still discovered.
            query = query.where(~select(NewowNotificationDelivery.delivery_id).where(
                NewowNotificationDelivery.batch_id == ReferenceBatch.batch_id,
                NewowNotificationDelivery.status == 'BATCH_PROCESSED').exists())
            rows = session.execute(query.order_by(ReferenceBatch.processed_at, ReferenceBatch.batch_id).limit(limit)).all()
            attempted = 0
            processed = 0
            for batch, stream in rows:
                for point in require_envelope(batch.source_evidence.get('presentation_v1')):
                    if self.should_stop():
                        return {'enabled': True, 'processed': processed, 'attempted': attempted}
                    candidate = self._candidate(session, policy, batch, stream, point)
                    if candidate is None:
                        continue
                    signal, delivery = candidate
                    identity = sha256((stream.stream_id + ':' + signal).encode()).hexdigest()
                    now = _utc(self.clock())
                    observed = _notification_origin(batch)
                    if now < observed:
                        raise ValueError('NEWOW_NOTIFICATION_TIME_INVALID')
                    expired = (now - observed).total_seconds() > 30
                    self.assert_owned()
                    insert = pg_insert if session.bind.dialect.name == 'postgresql' else sqlite_insert
                    result = session.execute(insert(NewowNotificationDelivery).values(
                        delivery_id=identity, stream_id=stream.stream_id, signal_id=signal, batch_id=batch.batch_id,
                        topic_hash=topic, status='EXPIRED_NO_SEND' if expired else 'ATTEMPTED_UNKNOWN', attempted_at=None if expired else now
                    ).on_conflict_do_nothing(index_elements=['stream_id', 'signal_id']).returning(NewowNotificationDelivery.delivery_id)).scalar_one_or_none()
                    session.commit()  # irrevocable claim BEFORE external provider call
                    if result is None or expired:
                        continue
                    attempted += 1
                    self.assert_owned()
                    send_now = _utc(self.clock())
                    if send_now < observed:
                        raise ValueError("NEWOW_NOTIFICATION_TIME_INVALID")
                    if (send_now - observed).total_seconds() > 30:
                        row = session.get(NewowNotificationDelivery, identity)
                        row.status, row.attempted_at = 'EXPIRED_NO_SEND', None
                        session.commit()
                        attempted -= 1
                        continue
                    content = delivery.content + f"\n处理延迟：{(send_now - observed).total_seconds():.1f}秒"
                    delivery = NotificationDelivery(title=delivery.title, content=content, audience=delivery.audience)
                    try:
                        acceptance = transport.send(delivery)
                        status = 'PROVIDER_ACCEPTED'
                    except Exception:
                        status = 'FAILED_OR_UNKNOWN'
                    self.assert_owned()
                    row = session.get(NewowNotificationDelivery, identity)
                    row.status = status
                    row.finished_at = _utc(self.clock())
                    if status == 'PROVIDER_ACCEPTED':
                        reference = getattr(acceptance, 'reference', None)
                        row.provider_reference = reference if isinstance(reference, str) and len(reference) <= 256 else None
                    session.commit()
                self.assert_owned()
                receipt_id = sha256(('batch:' + batch.batch_id).encode()).hexdigest()
                insert = pg_insert if session.bind.dialect.name == 'postgresql' else sqlite_insert
                session.execute(insert(NewowNotificationDelivery).values(
                    delivery_id=receipt_id, stream_id=stream.stream_id,
                    signal_id='__batch__:' + batch.batch_id, batch_id=batch.batch_id,
                    topic_hash=topic, status='BATCH_PROCESSED', attempted_at=_utc(self.clock())
                ).on_conflict_do_nothing(index_elements=['stream_id', 'signal_id']))
                policy.cursor_at, policy.cursor_batch_id = batch.processed_at, batch.batch_id
                session.commit()
                processed += 1
            return {'enabled': True, 'processed': processed, 'attempted': attempted}

    @staticmethod
    def _candidate(session, policy, batch, stream, point):
        if point.get('kind') != 'action' or not isinstance(point.get('value'), dict):
            return None
        value = point['value']
        kind = value.get('kind')
        signal = value.get('signal_id')
        contract, price = value.get('physical_contract'), value.get('reference_price')
        if stream.strategy_code == 'newow_dual_fusion':
            signal = value.get('source_signal_id')
            kind = {'OPEN_LONG': 'BUILD', 'CLOSE': 'CLEAR'}.get(kind)
            action = session.execute(select(ReferenceActionRow).where(
                ReferenceActionRow.stream_id == stream.stream_id, ReferenceActionRow.batch_id == batch.batch_id,
                ReferenceActionRow.source_action_id == signal)).scalar_one_or_none()
            if action is None:
                return None
            contract, price = action.physical_contract, action.reference_price
        if kind not in {'BUILD', 'REDUCE', 'CLEAR'} or not isinstance(signal, str) or not signal or len(signal) > 160 or signal.startswith('__batch__:'):
            return None
        eligibility = value.get('trade_eligibility', 'ELIGIBLE')
        if eligibility == 'WARMUP_ONLY':
            return None
        if eligibility not in {'ELIGIBLE', 'NO_ELIGIBLE_ENTRY', 'INITIAL_CLEAR_NO_ENTRY'}:
            raise ValueError('NEWOW_NOTIFICATION_ELIGIBILITY_INVALID')
        if eligibility != 'ELIGIBLE' and kind != 'CLEAR':
            raise ValueError('NEWOW_NOTIFICATION_ELIGIBILITY_INVALID')
        end, observed = value.get('bar_end'), value.get('observed_at')
        if end is None or observed is None:
            return None
        end, observed = _utc(end), _utc(observed)
        if batch.observed_at is None or observed != _utc(batch.observed_at):
            raise ValueError('NEWOW_NOTIFICATION_OBSERVATION_CONFLICT')
        raw_observed = _notification_origin(batch)
        if end <= _utc(policy.enabled_at) or raw_observed <= _utc(policy.enabled_at):
            return None
        if not isinstance(contract, str) or not contract or price is None:
            return None
        price = Decimal(str(price))
        if not price.is_finite() or price <= 0:
            raise ValueError('NEWOW_NOTIFICATION_PRICE_INVALID')
        strategy = dict(zip(STRATEGIES, ('趋势', '震荡', '主升浪', '双策略')))[stream.strategy_code]
        action_name = {'BUILD': '建仓', 'REDUCE': '减仓', 'CLEAR': '清仓'}[kind]
        return signal, NotificationDelivery(title=f'牛哇{strategy} · {stream.product.upper()} · {action_name}',
            content=f'策略：{strategy}　品种：{stream.product.upper()}　周期：{stream.frequency}\n合约：{contract}\n动作：{action_name}　页面参考价：{price}\nBar：{end.isoformat()}\n原始观察：{raw_observed.isoformat()}\n仅供研究观察，不是交易指令。', audience='htdy_observers')
