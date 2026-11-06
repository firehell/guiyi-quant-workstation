"""Supervise the existing development model and prepare daily execution facts.

No Broker, Market subscription, historical publication or notification endpoint.
"""
import argparse
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataService
from app.market_data.new_subing_research import validate_series
from app.market_data.observation_stream import ObservationStream
from app.market_data.storage import CanonicalMonthlyStore
from app.subing_model import worker
from app.subing_model.pipeline import Pipeline
from app.subing_model.store import ModelStore, digest
from app.subing_model_recovery import POLICY, apply_event, flat_without_obligations, consumed_bars, verify_overlap
from app.subing_projection_source import registered_source
from guiyi_quant.subing_decision import _wire

SERVICE_VERSION = 'subing_development_supervision_v1'


def capture_slot(now, first_open, day_end):
    """Three durable attempts/day, only after a current quote can exist.

    A failed/unknown attempt is never rerun. No provider call during closed days.
    """
    if now < first_open + timedelta(minutes=1) or now > day_end:
        return None
    seconds = (now - first_open).total_seconds()
    return 0 if seconds < 5 * 60 else 1 if seconds < 20 * 60 else 2


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, value):
    worker.atomic(path, value)
    fsync_directory(path.parent)


class Service:
    def __init__(self):
        self.root = registered_source('model_root')
        if self.root is None:
            raise ValueError('MODEL_REGISTERED_SOURCE_REQUIRED')
        self.active = json.loads((self.root / 'subing-model-active.json').read_text())
        from app.private_settings import read_private_settings_content
        self.store = ModelStore(read_private_settings_content(self.root / 'subing-model-database.url').decode())
        self.owner = self.store.engine.connect()
        if not self.owner.scalar(text('SELECT pg_try_advisory_lock(183047231)')):
            raise ValueError('MODEL_WORKER_ALREADY_RUNNING')
        self.settings, self.redis = worker.settings_and_redis()
        self.sql = create_engine(normalize_database_url(self.settings['DATABASE_URL']),
                                 connect_args={'connect_timeout': 5})
        self.stream = ObservationStream(self.redis, kind='completed')
        run, events = self.store.load(self.active['run_id'])
        self.identity = run['identity']
        self.history = events
        self.known = consumed_bars(self.identity, events)
        self.check_code()
        self.pipe = Pipeline(self.identity)
        for event in events:
            apply_event(self.pipe, event)
        if self.pipe.state() != run['state']:
            raise ValueError('MODEL_RESTART_PARITY_FAILED')
        self.context_cache = {}
        self.daily_day = None
        self.daily_pending, self.daily_proofs, self.daily_errors = {}, {}, {}
        self.blocked = None
        self.recovery_checked = None

    def check_code(self):
        if self.identity['code_hashes'] != worker.code_hashes():
            raise ValueError('MODEL_CODE_IDENTITY_CHANGED')

    def market(self):
        return Session(self.sql, autoflush=False)

    def context(self, day):
        if day not in self.context_cache:
            with self.market() as db, readonly_transaction(db, timeout_seconds=120):
                root = Path(self.settings['GUIYI_CANONICAL_DATA_ROOT'])
                cat = MarketCatalog(db, root)
                self.context_cache[day] = worker.contexts(
                    MarketDataService(cat, CanonicalMonthlyStore(root)), cat, day)
        return self.context_cache[day]

    def facts(self, day, ctx, now):
        index = self.root / 'subing-model-facts-index.json'
        current = worker.facts_for(index, day)
        if current:
            return current
        jm = ctx['jm']
        slot = capture_slot(now, datetime.fromisoformat(jm['first_open']),
                            datetime.fromisoformat(jm['day_end']))
        if slot is None:
            return None
        attempts = self.root / 'subing-model-facts-attempts'
        attempts.mkdir(mode=0o700, exist_ok=True)
        fsync_directory(self.root)
        target = attempts / f'{day}-{slot}'
        if target.exists():
            # A successfully captured but not-yet-registered asset can be read
            # after a crash. Failed/UNKNOWN provider calls are not repeated.
            asset = target / 'capture' / 'jm.json'
            if not asset.is_file():
                return None
        else:
            target.mkdir(mode=0o700)
            fsync_directory(attempts)
            atomic(target / 'intent.json', dict(day=str(day), slot=slot,
                contract=jm['contract'], max_calls=6, service_version=SERVICE_VERSION))
            result = subprocess.run([sys.executable, '-m', 'scripts.research.subing_model_facts',
                '--contract', jm['contract'], '--day', str(day), '--out', str(target / 'capture')],
                capture_output=True, timeout=180, check=False)
            atomic(target / 'result.json', dict(returncode=result.returncode,
                stdout_sha256=sha256(result.stdout).hexdigest()))
            if result.returncode:
                return None
            asset = target / 'capture' / 'jm.json'
        raw = asset.read_bytes()
        body = json.loads(raw)
        if body['contracts'][jm['contract']]['start'] != str(day):
            raise ValueError('MODEL_FACTS_DAY_INVALID')
        registry = json.loads(index.read_text()) if index.exists() else {}
        if str(day) in registry:
            return worker.facts_for(index, day)
        registry[str(day)] = dict(path=str(asset), sha256=sha256(raw).hexdigest())
        atomic(index, registry)
        return worker.facts_for(index, day)

    def daily_inputs(self, day, ctx):
        if self.daily_day == day:
            return
        from app.subing_model.market import prefix
        updates, proofs, errors = {}, {}, {}
        with self.market() as db, readonly_transaction(db, timeout_seconds=180):
            root = Path(self.settings['GUIYI_CANONICAL_DATA_ROOT'])
            cat = MarketCatalog(db, root)
            m = MarketDataService(cat, CanonicalMonthlyStore(root))
            for product in worker.PRODUCTS:
                through = date.fromisoformat(ctx[product]['previous'])
                last = self.pipe.factors[product].trends['1d'].last_end
                if last is not None and last.date() >= through:
                    continue
                try:
                    bars, proof = prefix(m, product, self.pipe.products[product]['contract'], '1d', through)
                    updates[product] = [_wire(asdict(b)) for b in bars if last is None or b.bar_end > last]
                    proofs[product] = proof
                except Exception as exc:
                    errors[product] = getattr(exc, 'code', None) or type(exc).__name__
        self.daily_pending, self.daily_proofs, self.daily_errors = updates, proofs, errors
        self.daily_day = day if not errors else None

    def recovery(self, day, ctx, now, *, preview=False):
        """Read complete Historical facts after close, preserving original Live log."""
        since = date.fromisoformat(self.pipe.source_day)
        if day < since or any(now < datetime.fromisoformat(c['day_end']) for c in ctx.values()):
            return False
        if day == since and all(self.pipe.last.get((p, '1m')) == datetime.fromisoformat(ctx[p]['day_end']) for p in worker.PRODUCTS):
            return False
        # Validate at most once/minute; a failed Canonical read never advances.
        key = (day, int(now.timestamp()) // 60)
        if self.recovery_checked == key:
            return False
        self.recovery_checked = key
        tail = self.stream.tail(day)
        updates = {}
        with self.market() as db, readonly_transaction(db, timeout_seconds=300):
            root = Path(self.settings['GUIYI_CANONICAL_DATA_ROOT'])
            cat = MarketCatalog(db, root)
            m = MarketDataService(cat, CanonicalMonthlyStore(root))
            for product in worker.PRODUCTS:
                contract = self.pipe.products[product]['contract']
                maps = cat.main_map(product, since, day)
                calendar = cat.calendar_days(product, since, day)
                if {d for d, opened in calendar} != {since + timedelta(days=i) for i in range((day - since).days + 1)}:
                    raise ValueError('MODEL_RECOVERY_CALENDAR_INCOMPLETE')
                required_days = [d for d, opened in calendar if opened]
                if sorted(x.trade_date for x in maps) != required_days or any(x.contract != contract for x in maps):
                    raise ValueError('MODEL_RECOVERY_ROLLOVER_REQUIRES_REVIEW')
                item = dict(contract=contract, bars={}, proofs={})
                for frequency in ('1m', '30m', '60m', '1d'):
                    freq = BarFrequency(frequency)
                    cutoff = datetime.fromisoformat(ctx[product]['day_end'])
                    source = m.contract_source_evidence(symbol=product, contract=contract,
                                                         frequency=freq, before=cutoff)
                    expected = m.expected_contract_replay_endpoints(symbol=product,
                        contract=contract, frequency=freq, trading_day=day, cutoff=cutoff)
                    known = self.known.get((product, frequency), {})
                    read_since = min((b.trading_day for b in known.values()), default=since)
                    expected = [(end, d) for end, d in expected if d >= read_since]
                    rows = m.query_contract_trading_days(ContractTradingDayQuery(
                        product, contract, freq, read_since, day))
                    validate_series(rows, product=product, contract=contract, frequency=freq, expected=expected)
                    if source != m.contract_source_evidence(symbol=product, contract=contract,
                                                            frequency=freq, before=cutoff):
                        raise ValueError('MODEL_RECOVERY_SOURCE_CHANGED')
                    verify_overlap(self.known.get((product, frequency), {}), rows.bars)
                    item['bars'][frequency] = _wire([asdict(b) for b in rows.bars])
                    item['proofs'][frequency] = dict(source=_wire(source), hash=digest(item['bars'][frequency]))
                updates[product] = item
        if self.stream.tail(day) != tail:
            raise ValueError('MODEL_RECOVERY_STREAM_CHANGED')
        payload = dict(event_id=f'{POLICY}:{day}:{tail}', recovery_policy=POLICY,
            observed_at=datetime.now(UTC).isoformat(), products=updates, source_day=str(day), cursor=tail,
            account_can_resume=flat_without_obligations(self.pipe.account))
        if preview:
            return payload
        self.commit(payload)
        self.daily_day = None
        return True

    def commit(self, payload):
        seq = self.pipe.sequence
        apply_event(self.pipe, payload)
        payload['outcome'] = self.pipe.last_outcome
        self.store.append(self.active['run_id'], payload, self.pipe.state(), seq)
        self.history.append(payload)
        self.known = consumed_bars(self.identity, self.history)

    def tick(self):
        self.check_code()
        now = datetime.now(UTC)
        day = date.fromisoformat(self.pipe.source_day)
        latest = max(self.stream.days())
        latest_ctx = self.context(latest)
        self.recovery(day, self.context(day), now)
        if latest > day and self.recovery(latest, latest_ctx, now):
            day = latest
        ctx = self.context(day)
        if latest > day and self.stream.tail(day) == self.pipe.source_cursor:
            if any(self.pipe.last.get((p, '1m')) != datetime.fromisoformat(ctx[p]['day_end']) for p in worker.PRODUCTS):
                raise ValueError('DAY_END_OBSERVATION_MISSING')
            day, ctx = latest, latest_ctx
            cursor = '0-0'
        else:
            cursor = self.pipe.source_cursor
        facts = self.facts(day, ctx, now)
        # Do not latch an otherwise healthy account merely because a freshly
        # opened Session is still awaiting its first valid execution facts.
        if not facts and now <= datetime.fromisoformat(ctx['jm']['day_end']):
            return 'WAIT_CURRENT_EXECUTION_FACTS'
        self.daily_inputs(day, ctx)
        if 'jm' in self.daily_errors:
            return 'WAIT_CURRENT_DAILY_FACTS'
        rows, tail = worker.read_rows(self.stream, day, cursor)
        now = datetime.now(UTC)
        if rows or tail != self.pipe.source_cursor or str(day) != self.pipe.source_day:
            if any(datetime.fromisoformat(e['confirmed_at']) > now for e in rows):
                raise ValueError('FUTURE_OBSERVATION')
            payload = dict(event_id=str(day) + ':' + tail, observed_at=now.isoformat(),
                observations=rows, contexts=ctx, facts=facts, daily_updates=self.daily_pending,
                daily_sources=self.daily_proofs, daily_errors=self.daily_errors,
                cursor=tail, source_day=str(day))
            self.commit(payload)
            self.daily_pending, self.daily_proofs = {}, {}
        return 'RUNNING'

    def heartbeat(self, status, code=None):
        atomic(self.root / 'subing-model-heartbeat.json', dict(run_id=self.active['run_id'],
            status=status, code=code, at=datetime.now(UTC), source_day=self.pipe.source_day,
            sequence=self.pipe.sequence, service_version=SERVICE_VERSION))

    def close(self):
        self.owner.close()
        self.sql.dispose()
        self.store.engine.dispose()
        self.redis.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--recovery-preview', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    service = Service()
    try:
        if args.check:
            print(json.dumps(dict(status='MODEL_REPLAY_VERIFIED', sequence=service.pipe.sequence, run_id=service.active['run_id'], source_day=service.pipe.source_day, source_code_hashes=len(service.identity['code_hashes']))))
            return
        if args.recovery_preview:
            day=max(service.stream.days())
            plan=service.recovery(day,service.context(day),datetime.now(UTC),preview=True)
            if not plan:
                raise ValueError('MODEL_RECOVERY_NOT_NEEDED_OR_NOT_CLOSED')
            atomic(args.recovery_preview,plan)
            print(json.dumps(dict(status='MODEL_RECOVERY_PLAN_READY',plan_hash=digest(plan),products=len(plan['products']),account_can_resume=plan['account_can_resume'])))
            return
        while True:
            # Any failed/mutated in-memory pipeline must exit and reconstruct
            # under the one worker lock. Never continue after commit UNKNOWN.
            try:
                status = service.tick()
                service.heartbeat(status)
            except Exception as exc:
                code = getattr(exc, 'code', None)
                if not code and isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() and str(exc).isupper():
                    code = str(exc)
                service.heartbeat('STOPPED', code or type(exc).__name__.upper())
                raise SystemExit(2) from None
            if args.once:
                return
            time.sleep(5)
    finally:
        service.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() and str(exc).isupper() else type(exc).__name__.upper()
        print(json.dumps(dict(status='MODEL_SERVICE_STOPPED', code=code)))
        raise SystemExit(2) from None
