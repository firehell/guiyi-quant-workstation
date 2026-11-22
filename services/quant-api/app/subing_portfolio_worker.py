"""Explicit foreground consumer of the existing completed observation stream."""

import argparse
import fcntl
import os
import json
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session

from app.api.subing_portfolio import ACTIVE_PORTFOLIO, HEARTBEAT, read_registration
from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.aggregation import expected_intraday_ends
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataService
from app.market_data.new_subing_research import validate_series
from app.market_data.observation_stream import DAILY_LIMIT, ObservationEnvelope, ObservationStream, _text
from app.market_data.storage import CanonicalMonthlyStore
from app.private_settings import read_private_settings_content
from app.subing_model.factors import Factors
from app.subing_model.pipeline import SH, bar
from app.subing_model.store import ModelStore, runs
from app.subing_model.worker import atomic, facts_for, settings_and_redis
from app.subing_portfolio_paths import DB_PATH, FACTS_REGISTRY, STATE_ROOT
from app.subing_portfolio_supervision import trading_day, refresh_facts
from app.subing_portfolio_journal import KIND, LEGACY_KIND, PortfolioJournal, PreparedObservation, stamp, encode_minute
from guiyi_quant.subing_decision import _wire, _digest
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS


def prepare_day(settings, sql, day, products, *, warmup=True):
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    contexts, factors = {}, {}
    with Session(sql, autoflush=False) as db, readonly_transaction(db, timeout_seconds=180):
        catalog = MarketCatalog(db, root)
        market = MarketDataService(catalog, CanonicalMonthlyStore(root))
        for product in products:
            days = [d for d, opened in catalog.calendar_days(
                product, day - timedelta(days=14), day + timedelta(days=14)
            ) if opened]
            try:
                index = days.index(day)
            except ValueError:
                raise ValueError("PORTFOLIO_CALENDAR_INCOMPLETE") from None
            if not 0 < index < len(days) - 1:
                raise ValueError("PORTFOLIO_CALENDAR_INCOMPLETE")
            previous, following = days[index - 1], days[index + 1]
            proof = market.historical_metadata_evidence(symbol=product, since=previous, through=following)
            mapping = catalog.main_map(product, day, day)
            if len(mapping) != 1:
                raise ValueError("PORTFOLIO_OWNER_MAPPING_MISSING")
            contract = mapping[0].contract
            windows = tuple(market.session_windows(symbol=product, trading_day=day))
            next_windows = market.session_windows(symbol=product, trading_day=following)
            cutoff = max(w.end for w in market.session_windows(symbol=product, trading_day=previous))
            context = dict(
                contract=contract, metadata_hash=_digest(_wire(proof)), previous=str(previous), first_open=windows[0].start.isoformat(),
                day_end=windows[-1].end.isoformat(), next_open=min(w.start for w in next_windows).isoformat(),
                sessions=[[w.start.isoformat(), w.end.isoformat()] for w in windows],
                **{f"expected_{f}": [at.isoformat() for at in expected_intraday_ends(windows, f)]
                   for f in ("1m", "30m", "60m")},
            )
            if not warmup:
                if proof != market.historical_metadata_evidence(symbol=product, since=previous, through=following):
                    raise ValueError("PORTFOLIO_METADATA_CHANGED")
                contexts[product] = context
                continue
            factor = Factors(contract)
            for name in ("1d", "30m", "60m"):
                freq = BarFrequency(name)
                source_args = dict(symbol=product, contract=contract, frequency=freq, before=cutoff)
                source = market.contract_source_evidence(**source_args)
                expected = market.expected_contract_replay_endpoints(
                    symbol=product, contract=contract, frequency=freq,
                    trading_day=previous, cutoff=cutoff,
                )
                if not expected:
                    raise ValueError("PORTFOLIO_WARMUP_INCOMPLETE")
                result = market.query_contract_trading_days(
                    ContractTradingDayQuery(product, contract, freq, expected[0][1], previous)
                )
                validate_series(result, product=product, contract=contract, frequency=freq,
                                expected=expected, allow_daily_no_trade=name == "1d")
                if source != market.contract_source_evidence(**source_args):
                    raise ValueError("PORTFOLIO_WARMUP_SOURCE_CHANGED")
                for item in result.bars:
                    if not item.is_strict_no_trade:
                        factor.step(name, item)
            if not factor.daily or factor.frame is None or factor.hourly is None:
                raise ValueError("PORTFOLIO_WARMUP_INCOMPLETE")
            if proof != market.historical_metadata_evidence(symbol=product, since=previous, through=following):
                raise ValueError("PORTFOLIO_METADATA_CHANGED")
            contexts[product], factors[product] = context, factor
    return contexts, factors


def read_completed(stream, day, contexts, after):
    result = {}
    ends = {(product, freq): {stamp(at) for at in context["expected_" + freq]}
            for product, context in contexts.items() for freq in ("1m", "30m", "60m")}
    rows = stream.redis.xrange(stream.key(day), min=f"({after}", count=DAILY_LIMIT + 1)
    if len(rows) > DAILY_LIMIT:
        raise ValueError("PORTFOLIO_OBSERVATION_LIMIT")
    for identifier, fields in rows:
        raw = fields.get(b"envelope", fields.get("envelope"))
        event = ObservationEnvelope.from_json(raw, stream_id=_text(identifier))
        parts = event.channel.split(":")
        if len(parts) != 4 or parts[:2] != ["live", "bar"]:
            continue
        product, freq = parts[2:]
        if product not in contexts or freq not in ("1m", "30m", "60m"):
            continue
        source = stream.redis.hget(stream.identity_key(day), event.observation_id)
        minute = bar(event.data)
        if (
            not source or json.loads(source)["payload"] != _text(raw)
            or json.loads(source)["id"] != event.stream_id
            or event.observation_id != f"{day}:{event.data['contract']}:{freq}:{event.data['bar_end']}"
            or not event.notification_eligible or event.confirmed_at is None
            or event.confirmed_at < minute.bar_end or event.source_observed_at > event.confirmed_at
            or event.trading_day != day or minute.trading_day != day
            or event.data["contract"] != contexts[product]["contract"]
            or minute.bar_end not in ends[product, freq]
        ):
            raise ValueError("PORTFOLIO_OBSERVATION_INVALID")
        key = (minute.bar_end, product, freq)
        if key in result:
            raise ValueError("PORTFOLIO_OBSERVATION_DUPLICATE")
        result[key] = event
    return result, _text(rows[-1][0]) if rows else after


def validate_current_facts(value, product, context, day, now):
    """Bind the existing capture contract before allowing any Paper mutation."""
    from scripts.research.subing_model_facts import CAPTURE_VERSION, FEE_POLICY
    try:
        contract = context["contract"]
        captured = stamp(value["captured_at"])
        body = value["contracts"][contract]
        assumption = value["fee_assumption"]
        snapshot = stamp(body["field_sources"]["snapshot_at"])
        if (value["schema_version"] != 1 or value["source"] != "rqdata"
            or value["capture_version"] != CAPTURE_VERSION
            or value["time_semantics"] != "current_effective_execution_facts"
            or value["fee_policy_version"] != FEE_POLICY
            or not re.fullmatch(r"[0-9a-f]{64}", value["plan_hash"])
            or set(value["contracts"]) != {contract}
            or body["start"] != str(day) or body["end"] != str(day)
            or assumption["contract"] != contract or assumption["target_day"] != str(day)
            or type(assumption["assumed"]) is not bool
            or assumption["source_day"] != (context["previous"] if assumption["assumed"] else str(day))
            or not snapshot <= captured <= now
            or not any(stamp(start) <= snapshot <= stamp(end) for start, end in context["sessions"])):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"PORTFOLIO_CURRENT_FACTS_INVALID_{product.upper()}") from None


def registered_facts(registry, day, contexts, now, *, observations=None):
    facts = {}
    for product, context in contexts.items():
        value = facts_for(registry / f"{product}.json", day)
        if value is None:
            raise ValueError(f"PORTFOLIO_EXECUTION_FACTS_MISSING_{product.upper()}")
        validate_current_facts(value, product, context, day, now)
        contract = context["contract"]
        if contract not in value["contracts"] or stamp(value["captured_at"]) > now:
            raise ValueError(f"PORTFOLIO_EXECUTION_FACTS_INVALID_{product.upper()}")
        if observations is not None:
            candidates = [event for (at, p, frequency), event in observations.items()
                          if p == product and frequency == "1m" and event.confirmed_at <= now]
            if not candidates:
                raise ValueError(f"PORTFOLIO_EXECUTION_FACTS_OBSERVATION_MISSING_{product.upper()}")
            latest = max(candidates, key=lambda event: stamp(event.data["bar_end"]))
            encode_minute(product, PreparedObservation(latest, value, {}, {}), context,
                          stamp(latest.data["bar_end"]), day, now)
        facts[product] = value
    return facts


class ObservationGap(ValueError):
    """First outstanding endpoint and total missing bars per physical input."""

    def __init__(self, code, missing, contexts):
        super().__init__(code)
        grouped = {}
        for at, product, frequency in missing:
            item = grouped.setdefault((product, frequency), dict(
                product=product, contract=contexts[product].get("contract"), frequency=frequency,
                first_missing_at=at.isoformat(), count=0,
            ))
            item["count"] += 1
        self.missing = list(grouped.values())


def preflight_prefix(stream, day, contexts, now, *, with_cursor=False):
    """Validate the actual observation prefix before creating a new cash identity."""
    rows, cursor = read_completed(stream, day, contexts, "0-0")
    missing = []
    for product, context in contexts.items():
        for frequency in ("1m", "30m", "60m"):
            for raw in context["expected_" + frequency]:
                at = stamp(raw)
                if at <= now - timedelta(minutes=2) and (at, product, frequency) not in rows:
                    missing.append((at, product, frequency))
    if missing:
        raise ObservationGap("PORTFOLIO_INITIAL_PREFIX_INCOMPLETE", missing, contexts)
    if any(at <= now and event.confirmed_at > now for (at, _, _), event in rows.items()):
        raise ValueError("PORTFOLIO_OBSERVATION_FROM_FUTURE")
    return (rows, cursor) if with_cursor else rows


def prime_factors(factors, observations, through):
    for (at, product, frequency), event in sorted(observations.items(),
            key=lambda row: (row[0][0], {"60m":0, "30m":1, "1m":2}[row[0][2]], row[0][1])):
        if frequency != "1m" and at <= through:
            factors[product].step(frequency, bar(event.data))


def consume_day(journal, day, contexts, factors, stream, registry, *, once=False, refresh=False, initial=None):
    by_end = {}
    for product, context in contexts.items():
        for raw in context["expected_1m"]:
            by_end.setdefault(stamp(raw), set()).add(product)
    endpoints = iter(sorted(by_end))
    endpoint = next(endpoints, None)
    higher = {
        (product, freq): {stamp(raw) for raw in context["expected_" + freq]}
        for product, context in contexts.items() for freq in ("30m", "60m")
    }
    rows, cursor, primed_through = initial if initial is not None else ({}, "0-0", None)
    rows = dict(rows)
    facts = {}
    while endpoint is not None:
        incoming, cursor = read_completed(stream, day, contexts, cursor)
        if incoming.keys() & rows.keys():
            raise ValueError("PORTFOLIO_OBSERVATION_DUPLICATE")
        rows.update(incoming)
        now = datetime.now(UTC)
        while endpoint is not None and endpoint <= now:
            required = [(endpoint, product, freq) for product in sorted(by_end[endpoint])
                        for freq in ("60m", "30m", "1m")
                        if freq == "1m" or endpoint in higher[product, freq]]
            missing = [key for key in required if key not in rows]
            if missing:
                if now - endpoint > timedelta(minutes=2):
                    raise ObservationGap("PORTFOLIO_BATCH_INCOMPLETE", missing, contexts)
                break
            if any(rows[key].confirmed_at > now for key in required):
                raise ValueError("PORTFOLIO_OBSERVATION_FROM_FUTURE")
            # Inactive/day-only products have no current quote at night. Preserve
            # their existing account obligations; require facts only when their
            # authoritative Session contributes a minute to this batch.
            needed = {product: contexts[product] for product in by_end[endpoint] if product not in facts}
            if needed:
                if refresh:
                    refresh_facts(registry, day, needed, now)
                    now = datetime.now(UTC)
                facts.update(registered_facts(registry, day, needed, now, observations=rows))
            previous = journal.portfolio.last_at or journal.started_at
            eligible = endpoint > previous
            prepared, charts = {}, {}
            for key in required:
                _, product, freq = key
                event = rows.pop(key)
                minute = bar(event.data)
                factor = factors[product]
                if freq != "1m":
                    if primed_through is None or endpoint > primed_through:
                        factor.step(freq, minute)
                    if freq == "30m":
                        charts[product] = _wire(dict(
                            at=endpoint, open=minute.open, high=minute.high, low=minute.low,
                            close=minute.close, ema21=factor.frame["ema21"],
                            **(factor.structure_point or {}),
                        ))
                elif eligible:
                    local = endpoint.astimezone(SH)
                    technical = factor.observation(minute, local.date() == day and (local.hour, local.minute) >= (14, 50))
                    structure = dict(factor.structure_point or {}, hourly=factor.hourly, base_regime=factor.frame["regime"])
                    prepared[product] = PreparedObservation(event, facts[product], technical, _wire(structure), charts.get(product))
            if eligible:
                if now - endpoint > timedelta(minutes=2):
                    raise ValueError("PORTFOLIO_BACKLOG_REVIEW_REQUIRED")
                journal.submit(day, endpoint, now, prepared, contexts=contexts if journal.day != day else None)
            endpoint = next(endpoints, None)
        in_session = any(stamp(start) <= now < stamp(end)
                         for context in contexts.values() for start, end in context["sessions"])
        state = ("RUNNING" if in_session else "SESSION_BREAK") if endpoint else "SESSION_COMPLETE"
        atomic(HEARTBEAT, dict(run_id=journal.run_id, at=datetime.now(UTC), status=state))
        if once or endpoint is None:
            return
        time.sleep(5)


def require_active_scope(products):
    if tuple(products) != EXPANDED_PORTFOLIO_PRODUCTS:
        raise ValueError("PORTFOLIO_ACTIVE_SCOPE_RETIRED")


def recover_registration(store):
    """A crash between DB commit and private binding must never create new equity."""
    with store.engine.connect() as connection:
        rows = connection.execute(select(runs.c.run_id, runs.c.identity).where(
            runs.c.identity["kind"].as_string().in_((KIND, LEGACY_KIND))
        )).all()
    shared = [run_id for run_id, identity in rows
              if tuple(identity["policy"].get("products", ())) == EXPANDED_PORTFOLIO_PRODUCTS]
    if len(shared) > 1:
        raise ValueError("PORTFOLIO_SHARED_OWNER_AMBIGUOUS")
    return {"run_id": shared[0]} if shared else None


def startup_wait_status(code):
    if code in {"PORTFOLIO_CALENDAR_INCOMPLETE", "PORTFOLIO_OWNER_MAPPING_MISSING"}:
        return "WAITING_MARKET_METADATA"
    if code == "PORTFOLIO_INITIAL_PREFIX_INCOMPLETE" or code.startswith(
        "PORTFOLIO_EXECUTION_FACTS_OBSERVATION_MISSING_"
    ):
        return "WAITING_OBSERVATIONS"
    if code.startswith("PORTFOLIO_EXECUTION_FACTS_MISSING_"):
        return "WAITING_EXECUTION_FACTS"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--facts-registry", type=Path, default=FACTS_REGISTRY)
    parser.add_argument("--start", choices=("16",))
    parser.add_argument("--check", choices=("16",))
    parser.add_argument("--refresh-facts", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.check and args.start:
        parser.error("choose --check or --start")
    settings, redis = settings_and_redis()
    sql = create_engine(normalize_database_url(settings["DATABASE_URL"]), connect_args={"connect_timeout": 5})
    stream = ObservationStream(redis, kind="completed")
    store = None
    run_id = None
    owns_lock = False
    initial_prepared = None
    initial_observations = None
    owner_file = None
    try:
        # Read-only preflight does not create state, a run, or invoke the provider.
        if args.check:
            now = datetime.now(UTC)
            day = args.day or trading_day(settings, sql, now)[0]
            contexts, _ = prepare_day(settings, sql, day, EXPANDED_PORTFOLIO_PRODUCTS)
            observations = preflight_prefix(stream, day, contexts, now)
            registered_facts(args.facts_registry, day, contexts, now, observations=observations)
            print("PORTFOLIO_INPUTS_AVAILABLE")
            return
        # A process lock survives PostgreSQL restarts/backend loss. The advisory
        # lock remains an additional DB-owner check, never the sole exclusion.
        owner_file = os.open(STATE_ROOT / "owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(owner_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("PORTFOLIO_WORKER_ALREADY_RUNNING") from None
        store = ModelStore(read_private_settings_content(DB_PATH).decode())
        with store.engine.connect() as owner:
            if not owner.scalar(text("SELECT pg_try_advisory_lock(183047232)")):
                raise ValueError("PORTFOLIO_WORKER_ALREADY_RUNNING")
            owns_lock = True
            atomic(HEARTBEAT, dict(run_id=None, at=datetime.now(UTC), status="WARMING_UP"))
            active = read_registration(ACTIVE_PORTFOLIO)
            recovered = active is None
            if recovered:
                active = recover_registration(store)
            if active:
                run_id = active['run_id']
                journal = PortfolioJournal.restore(store, run_id)
                require_active_scope(journal.products)
                if recovered:
                    atomic(ACTIVE_PORTFOLIO, active)
            elif args.start:
                # No ledger reset, equity transfer or historical fill replay.
                day = cached = light = checked_at = None
                while True:
                    now = datetime.now(UTC)
                    try:
                        current_day, _ = trading_day(settings, sql, now)
                        if args.day and args.day != current_day:
                            raise ValueError("PORTFOLIO_START_OUTSIDE_TRADING_DAY")
                        if day != current_day:
                            day, cached, light, checked_at = current_day, None, None, None
                        if checked_at is None or now - checked_at >= timedelta(seconds=30):
                            latest, _ = prepare_day(settings, sql, day, EXPANDED_PORTFOLIO_PRODUCTS, warmup=False)
                            if light != latest:
                                cached = None
                            light, checked_at = latest, now
                        ready_at = max(stamp(context["first_open"]) for context in light.values()) + timedelta(minutes=1)
                        if now < ready_at:
                            atomic(HEARTBEAT, dict(run_id=None, at=now, status="WAITING_EXECUTION_FACTS", next_open=ready_at))
                            if args.once:
                                return
                            time.sleep(5)
                            continue
                        if cached is None:
                            cached = prepare_day(settings, sql, day, EXPANDED_PORTFOLIO_PRODUCTS)
                        contexts, factors = cached
                        if contexts != light:
                            cached = None
                            continue
                        if args.refresh_facts:
                            now = datetime.now(UTC)
                            # Check the completed prefix before spending a fact capture slot.
                            preflight_prefix(stream, day, contexts, now)
                            refresh_facts(args.facts_registry, day, contexts, now)
                        now = datetime.now(UTC)
                        observations, cursor = preflight_prefix(stream, day, contexts, now, with_cursor=True)
                        registered_facts(args.facts_registry, day, contexts, now, observations=observations)
                    except ValueError as exc:
                        status = startup_wait_status(str(exc))
                        if status is None:
                            raise
                        atomic(HEARTBEAT, dict(run_id=None, at=datetime.now(UTC), status=status, code=str(exc),
                            missing=exc.missing if isinstance(exc, ObservationGap) else []))
                        if args.once:
                            return
                        time.sleep(5 if status == "WAITING_EXECUTION_FACTS" else 30)
                        continue
                    break
                primed_through = now - timedelta(minutes=2)
                prime_factors(factors, observations, primed_through)
                # Remember the verified stream cursor; do not re-fetch/re-hash
                # the full intraday prefix after creating the account identity.
                initial_observations = (observations, cursor, primed_through)
                now = datetime.now(UTC)
                actual_day, _ = trading_day(settings, sql, now)
                if day != actual_day or not any(
                    stamp(start) <= now < stamp(end)
                    for context in contexts.values() for start, end in context["sessions"]
                ):
                    raise ValueError("PORTFOLIO_START_OUTSIDE_TRADING_DAY")
                initial_prepared = (day, contexts, factors)
                run_id = f"subing-portfolio-16-{now:%Y%m%dT%H%M%S%f}"
                journal = PortfolioJournal.create(store, run_id, now, products=EXPANDED_PORTFOLIO_PRODUCTS)
                atomic(ACTIVE_PORTFOLIO, dict(run_id=run_id))
            else:
                raise ValueError("PORTFOLIO_NOT_STARTED")
            while True:
                now = datetime.now(UTC)
                selected, first_open = trading_day(settings, sql, now)
                # An interrupted prior day must be resolved, never skipped.
                day = journal.day if journal.day and journal.portfolio.last_at != journal.calendar_ends[-1] else selected
                if day == selected and now < first_open:
                    atomic(HEARTBEAT, dict(run_id=run_id, at=now, status="SESSION_CLOSED", next_open=first_open))
                    if args.once:
                        return
                    # Prepare the coming day before its first completed minute;
                    # warmup must not turn a normal day roll into a fill backlog.
                    if (first_open - now <= timedelta(minutes=15)
                        and (initial_prepared is None or initial_prepared[0] != day)):
                        contexts, factors = prepare_day(settings, sql, day, journal.products)
                        initial_prepared = (day, contexts, factors)
                    time.sleep(5)
                    continue
                if initial_prepared is not None and initial_prepared[0] == day:
                    _, contexts, factors = initial_prepared
                    initial_prepared = None
                else:
                    contexts, factors = prepare_day(settings, sql, day, journal.products)
                if journal.day == day and contexts != journal.contexts:
                    raise ValueError("PORTFOLIO_SESSION_CONTEXT_CHANGED")
                if journal.day and journal.day != day:
                    for product, previous in journal.contexts.items():
                        old_contract = previous['contract']
                        if contexts[product]['contract'] != old_contract:
                            old = journal.portfolio.accounts.get(old_contract)
                            if old and (old.layers or old.model.pending or old_contract in journal.portfolio.exit_owed):
                                raise ValueError("PORTFOLIO_ROLLOVER_REVIEW_REQUIRED")
                if args.refresh_facts:
                    refresh_facts(args.facts_registry, day, contexts, now)
                consume_day(journal, day, contexts, factors, stream, args.facts_registry, once=args.once, refresh=args.refresh_facts, initial=initial_observations)
                initial_observations = None
                if args.once:
                    return
                # Completed-day journal stays intact while waiting for next Session.
                time.sleep(5)
    except Exception as exc:
        code = str(exc)
        if not code.startswith("PORTFOLIO_") or not code.isidentifier():
            code = "PORTFOLIO_INPUT_OR_STORAGE_UNAVAILABLE"
        if owns_lock and STATE_ROOT.is_dir() and (not run_id or read_registration(ACTIVE_PORTFOLIO) == {"run_id": run_id}):
            atomic(HEARTBEAT, dict(run_id=run_id, at=datetime.now(UTC), status="BLOCKED", code=code,
                missing=exc.missing if isinstance(exc, ObservationGap) else []))
        raise SystemExit(code) from None
    finally:
        if owner_file is not None:
            os.close(owner_file)
        if store:
            store.engine.dispose()
        sql.dispose()
        redis.close()


if __name__ == "__main__":
    main()
