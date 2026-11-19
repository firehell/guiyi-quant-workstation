"""Explicit foreground consumer of the existing completed observation stream."""

import argparse
import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
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
from app.subing_model.store import ModelStore
from app.subing_model.worker import DB_PATH, atomic, facts_for, settings_and_redis
from app.subing_portfolio_journal import PortfolioJournal, PreparedObservation, stamp
from guiyi_quant.subing_decision import _wire
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS, PORTFOLIO_PRODUCTS


def prepare_day(settings, sql, day, products):
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    contexts, factors = {}, {}
    with Session(sql, autoflush=False) as db, readonly_transaction(db, timeout_seconds=180):
        catalog = MarketCatalog(db, root)
        market = MarketDataService(catalog, CanonicalMonthlyStore(root))
        for product in products:
            days = [d for d, opened in catalog.calendar_days(
                product, day - timedelta(days=14), day + timedelta(days=14)
            ) if opened]
            index = days.index(day)
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
                contract=contract, previous=str(previous), first_open=windows[0].start.isoformat(),
                day_end=windows[-1].end.isoformat(), next_open=min(w.start for w in next_windows).isoformat(),
                sessions=[[w.start.isoformat(), w.end.isoformat()] for w in windows],
                **{f"expected_{f}": [at.isoformat() for at in expected_intraday_ends(windows, f)]
                   for f in ("1m", "30m", "60m")},
            )
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


def registered_facts(registry, day, contexts, now):
    facts = {}
    for product, context in contexts.items():
        value = facts_for(registry / f"{product}.json", day)
        if value is None:
            raise ValueError(f"PORTFOLIO_EXECUTION_FACTS_MISSING_{product.upper()}")
        contract = context["contract"]
        if contract not in value["contracts"] or stamp(value["captured_at"]) > now:
            raise ValueError(f"PORTFOLIO_EXECUTION_FACTS_INVALID_{product.upper()}")
        facts[product] = value
    return facts


def consume_day(journal, day, contexts, factors, stream, registry, *, once=False):
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
    rows, cursor = {}, "0-0"
    facts = registered_facts(registry, day, contexts, datetime.now(UTC))
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
            if any(key not in rows for key in required):
                if now - endpoint > timedelta(minutes=2):
                    raise ValueError("PORTFOLIO_BATCH_INCOMPLETE")
                break
            if any(rows[key].confirmed_at > now for key in required):
                raise ValueError("PORTFOLIO_OBSERVATION_FROM_FUTURE")
            previous = journal.portfolio.last_at or journal.started_at
            eligible = endpoint > previous
            prepared, charts = {}, {}
            for key in required:
                _, product, freq = key
                event = rows.pop(key)
                minute = bar(event.data)
                factor = factors[product]
                if freq != "1m":
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
        atomic(HEARTBEAT, dict(run_id=journal.run_id, at=datetime.now(UTC), status="RUNNING" if endpoint else "SESSION_COMPLETE"))
        if once or endpoint is None:
            return
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--facts-registry", required=True, type=Path)
    parser.add_argument("--start", choices=("14", "16"))
    parser.add_argument("--check", choices=("14", "16"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.check and args.start:
        parser.error("choose --check or --start")
    settings, redis = settings_and_redis()
    sql = create_engine(normalize_database_url(settings["DATABASE_URL"]), connect_args={"connect_timeout": 5})
    stream = ObservationStream(redis, kind="completed")
    store = None
    run_id = None
    try:
        active = read_registration(ACTIVE_PORTFOLIO)
        if args.start or args.check:
            products = EXPANDED_PORTFOLIO_PRODUCTS if (args.start or args.check) == "16" else PORTFOLIO_PRODUCTS
        else:
            if active is None:
                raise ValueError("PORTFOLIO_NOT_STARTED")
            products = None
        if args.check:
            contexts, _ = prepare_day(settings, sql, args.day, products)
            registered_facts(args.facts_registry, args.day, contexts, datetime.now(UTC))
            print("PORTFOLIO_INPUTS_AVAILABLE")
            return
        store = ModelStore(read_private_settings_content(DB_PATH).decode())
        with store.engine.connect() as owner:
            if not owner.scalar(text("SELECT pg_try_advisory_lock(183047232)")):
                raise ValueError("PORTFOLIO_WORKER_ALREADY_RUNNING")
            if args.start:
                if read_registration(ACTIVE_PORTFOLIO) is not None:
                    raise ValueError("PORTFOLIO_ALREADY_INITIALIZED")
                contexts, factors = prepare_day(settings, sql, args.day, products)
                now = datetime.now(UTC)
                registered_facts(args.facts_registry, args.day, contexts, now)
                if not min(stamp(c["first_open"]) for c in contexts.values()) <= now < max(stamp(c["day_end"]) for c in contexts.values()):
                    raise ValueError("PORTFOLIO_START_OUTSIDE_TRADING_DAY")
                run_id = f"subing-portfolio-{args.start}-{now:%Y%m%dT%H%M%S%f}"
                journal = PortfolioJournal.create(store, run_id, now, products=products)
                atomic(ACTIVE_PORTFOLIO, dict(run_id=run_id))
            else:
                run_id = active["run_id"]
                journal = PortfolioJournal.restore(store, run_id)
                contexts, factors = prepare_day(settings, sql, args.day, journal.products)
                if journal.day == args.day and contexts != journal.contexts:
                    raise ValueError("PORTFOLIO_SESSION_CONTEXT_CHANGED")
            consume_day(journal, args.day, contexts, factors, stream, args.facts_registry, once=args.once)
    except Exception as exc:
        code = str(exc)
        if not code.startswith("PORTFOLIO_") or not code.isidentifier():
            code = "PORTFOLIO_INPUT_OR_STORAGE_UNAVAILABLE"
        if run_id and read_registration(ACTIVE_PORTFOLIO) == {"run_id": run_id}:
            atomic(HEARTBEAT, dict(run_id=run_id, at=datetime.now(UTC), status="INTERRUPTED", code=code))
        raise SystemExit(code) from None
    finally:
        if store:
            store.engine.dispose()
        sql.dispose()
        redis.close()


if __name__ == "__main__":
    main()
