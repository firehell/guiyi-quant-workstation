"""Explicit one-shot captured Live repair; planning is read-only and provider-free."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from app.core.env import PROJECT_ROOT
from app.market_data.domain import normalize_contract_for_symbol


class CapturedRecoveryCliError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_captured_arguments(args: argparse.Namespace) -> None:
    if (re.fullmatch(r'[a-z]{1,2}', args.symbol) is None
            or normalize_contract_for_symbol(args.symbol, args.contract) != args.contract
            or re.fullmatch(r'[a-f0-9]{64}', args.source_sha256) is None
            or not Path(args.source).is_absolute()
            or bool(args.apply) != bool(args.plan)
            or bool(args.apply) != bool(args.plan_sha256)):
        raise ValueError('CLI_ARGUMENT_INVALID')
    if args.apply and (not Path(args.plan).is_absolute()
                       or re.fullmatch(r'[a-f0-9]{64}', args.plan_sha256) is None):
        raise ValueError('CLI_ARGUMENT_INVALID')


def read_captured_file(path: Path, *, max_bytes: int = 512 * 1024) -> bytes:
    """Bounded single read from an explicitly selected owned regular file."""
    try:
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or not 0 < info.st_size <= max_bytes):
                raise ValueError
            raw = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
            if (len(raw) != info.st_size or len(raw) > max_bytes
                    or (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError
        return raw
    except (OSError, ValueError):
        raise CapturedRecoveryCliError('CAPTURED_FILE_INVALID') from None


def _after_market_preflight(trading_day) -> None:
    from app.market_data.after_market import public_after_market_status
    try:
        raw = json.loads(read_captured_file(PROJECT_ROOT / '.run' / 'after-market-status.json'))
        public = public_after_market_status(raw)
        if not public or public.get('schema_version') not in {2, 3, 4} or 'current_run' not in raw:
            raise ValueError
        # A running or already attempted same-day publication needs a new input
        # diagnosis. Do not repair a stale Live view after its consumer has changed.
        last = public.get('last_run')
        if public['current_run'] is not None or (
            isinstance(last, dict) and str(last.get('trading_day', '')) >= trading_day.isoformat()
        ):
            raise ValueError
    except (OSError, ValueError, TypeError):
        raise CapturedRecoveryCliError('CAPTURED_AFTER_MARKET_REVIEW_REQUIRED') from None


def _request(session, store, args, now):
    from sqlalchemy import select
    from app.market_data.live_recovery import LiveRecoveryRequest
    from app.market_data.market_phase import MarketPhaseResolver, MarketPhase
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.session_clock import SHANGHAI, resolved_session_windows_for_trading_day
    from app.models.market_tables import Contract, TradingCalendar

    if now.tzinfo is None or now.astimezone(SHANGHAI).date() != args.trading_day:
        raise CapturedRecoveryCliError('CAPTURED_DAY_INVALID')
    products = load_operational_products()
    snapshot = store.subscriptions(args.trading_day)
    if (args.symbol not in products or snapshot is None or set(snapshot) != set(products)
            or snapshot.get(args.symbol) != args.contract):
        raise CapturedRecoveryCliError('CAPTURED_SUBSCRIPTION_INVALID')
    contract = session.scalar(select(Contract).where(Contract.contract_code == args.contract))
    if (contract is None or contract.instrument_symbol != args.symbol or contract.provider != 'rqdata'
            or contract.listed_date is None or contract.expired_date is None
            or not contract.listed_date <= args.trading_day <= contract.expired_date):
        raise CapturedRecoveryCliError('CAPTURED_CONTRACT_INVALID')
    calendar = session.scalar(select(TradingCalendar).where(
        TradingCalendar.exchange_code == contract.exchange_code,
        TradingCalendar.trade_date == args.trading_day))
    phase = MarketPhaseResolver(session).resolve(args.symbol, now)
    if (calendar is None or not calendar.is_trading_day or phase.phase != MarketPhase.CLOSED
            or phase.trading_day not in (None, args.trading_day)):
        raise CapturedRecoveryCliError('CAPTURED_DAY_INVALID')
    sessions = tuple(item.window for item in resolved_session_windows_for_trading_day(
        session, exchange=contract.exchange_code, symbol=args.symbol, trading_day=args.trading_day))
    return LiveRecoveryRequest(args.trading_day, args.symbol, args.contract,
                               tuple(sorted(snapshot.items())), sessions, now)


def disable_captured_client_retry(client) -> None:
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    client.set_retry(Retry(NoBackoff(), 0))
    client.get_connection_kwargs().update(socket_connect_timeout=3, socket_timeout=5)


def run_captured_recovery(args, *, session_factory, clock=lambda: datetime.now(UTC)) -> dict:
    validate_captured_arguments(args)
    source = read_captured_file(Path(args.source))
    if hashlib.sha256(source).hexdigest() != args.source_sha256:
        raise CapturedRecoveryCliError('CAPTURED_SOURCE_HASH_INVALID')
    plan = None
    if args.apply:
        try:
            document = json.loads(read_captured_file(Path(args.plan)))
            plan = document['plan']
            if (document.get('command') != 'runtime.recover-live-captured'
                    or document.get('status') != 'planned'
                    or not isinstance(plan, dict)
                    or plan['plan_sha256'] != args.plan_sha256):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise CapturedRecoveryCliError('CAPTURED_PLAN_INVALID') from None

    from sqlalchemy import text
    from app.market_data.captured_live_recovery import plan_captured_recovery, apply_captured_recovery
    from app.market_data.captured_recovery_runtime import verify_captured_recovery_runtime
    from app.market_data.composition import build_market_read_service
    from app.market_data.live_recovery_guard import recovery_guard, after_market_recovery_guard
    from app.market_data.live_market import RedisLiveStore

    with session_factory() as session:
        if session.get_bind().dialect.name == 'postgresql':
            session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        elif session.get_bind().dialect.name == 'sqlite':
            session.execute(text('PRAGMA query_only = ON'))
        else:
            raise CapturedRecoveryCliError('CAPTURED_DATABASE_INVALID')
        with session.no_autoflush:
            store = build_market_read_service(session)._live_store
            if not isinstance(store, RedisLiveStore):
                raise CapturedRecoveryCliError('CAPTURED_STORE_INVALID')
            disable_captured_client_retry(store._redis)

            def identity():
                raw = store._redis.get('alert:heartbeat')
                return verify_captured_recovery_runtime(
                    now=clock(), live_heartbeat=store.heartbeat(),
                    alert_heartbeat=json.loads(raw) if raw else None)

            current_identity = identity()
            _after_market_preflight(args.trading_day)
            request = _request(session, store, args, clock())
            if not args.apply:
                body = plan_captured_recovery(store, request, source,
                                             runtime_identity=current_identity, clock=clock)
                return {'schema_version': 1, 'command': 'runtime.recover-live-captured',
                        'status': 'planned', 'readonly': True, 'provider_requests': 0, 'plan': body}

            @contextmanager
            def guarded():
                with after_market_recovery_guard(), recovery_guard(args.symbol):
                    if identity() != current_identity:
                        raise CapturedRecoveryCliError('CAPTURED_RUNTIME_DRIFT')
                    _after_market_preflight(args.trading_day)
                    yield

            assert isinstance(plan, dict)
            body = apply_captured_recovery(store, request, source, plan,
                                          runtime_identity=current_identity, clock=clock,
                                          commit_guard=guarded)
            status = body.get('status')
            return {'schema_version': 1, 'command': 'runtime.recover-live-captured',
                    'status': 'passed' if status == 'RECOVERED' else 'noop' if status == 'NOOP' else 'failed',
                    'readonly': status == 'NOOP', 'provider_requests': 0, 'result': body,
                    'notification_sent': False, 'runtime_ready': False}
