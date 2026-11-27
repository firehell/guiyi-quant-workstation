"""Bind the frozen native Paper worker to the formal completed stream."""

from decimal import Decimal
from functools import wraps
from pathlib import Path

from guiyi_quant.compute import REGISTRY

from app.market_data.market_foundation_scope import FormalMarketReadRedis, require_formal_tick_binding

from .isolated_simulation import bind_completed_paper_factors, paper_live_scopes
from .owned_live import verify_tick_original
from .runtime import ComputeRuntime


def continue_frozen_paper(worker, *, stream_class, private_config):
    """Adapt the single foreground owner. The pinned worker runs its own main."""
    from sqlalchemy.engine import make_url

    from app.db.url import normalize_database_url
    from app.private_settings import read_private_settings_content, runtime_dependency_settings

    original_settings = worker.settings_and_redis
    original_consume = worker.consume_day
    bound = None
    stream = None
    connection = None

    @wraps(original_settings)
    def formal_settings():
        nonlocal bound, stream, connection
        settings, redis = original_settings()
        connection = redis
        try:
            config = read_private_settings_content(private_config)
            if (b"# guiyi-market-source: rqdata_tick" not in config.splitlines()
                    or runtime_dependency_settings(config) != settings):
                raise ValueError("PORTFOLIO_FORMAL_MARKET_SETTINGS_UNPROVEN")
            root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
            url = make_url(normalize_database_url(settings["DATABASE_URL"]))
            require_formal_tick_binding(redis, url, root)
            bound = FormalMarketReadRedis(redis, url, root)
            stream = stream_class(bound, kind="completed")
        except BaseException:
            redis.close()
            raise
        return settings, bound

    @wraps(original_consume)
    def consume(journal, day, contexts, factors, native_stream, registry, **kwargs):
        if stream is None or native_stream.redis is not bound or kwargs.get("initial") is not None:
            raise ValueError("PORTFOLIO_FORMAL_CONTINUATION_UNPROVEN")
        primed = None
        if journal.day == day:
            # The native journal owns its recorded source IDs. A restart
            # must prove the target stream contains the already committed prefix.
            rows, cursor = worker.read_completed(stream, day, contexts, "0-0")
            verify_source_prefix(journal, day, rows, stream, worker.stamp, worker.bar)
            primed = (rows, cursor, None)
        with ComputeRuntime(REGISTRY, owned_live_scopes=paper_live_scopes(day, contexts)) as runtime:
            owned = bind_completed_paper_factors(
                runtime, stream, journal, day, contexts, factors,
            )
            return original_consume(journal, day, contexts, owned, stream, registry,
                                    **{**kwargs, "initial": primed})

    # Only this entrypoint substitutes these two existing composition seams.
    # Journal verification, recovery, scheduler and execution remain native.
    worker.settings_and_redis = formal_settings
    worker.consume_day = consume
    try:
        worker.main()
    finally:
        worker.settings_and_redis = original_settings
        worker.consume_day = original_consume
        if connection is not None:
            connection.close()


def verify_source_prefix(journal, day, target, stream, stamp, decode_bar):
    row, events = journal.store.load(journal.run_id)
    if row["identity"] != journal.identity or row["sequence"] != journal.sequence:
        raise ValueError("PORTFOLIO_FORMAL_CONTINUATION_UNPROVEN")
    for payload in events:
        if payload["day"] != day.isoformat():
            continue
        endpoint = stamp(payload["minute"])
        for product, minute in payload["rows"].items():
            event = target.get((endpoint, product, "1m"))
            recorded = minute["execution"]["bar"]
            if event is None or event.stream_id != minute["producer_stream_id"]:
                raise ValueError("PORTFOLIO_COMPLETED_PREFIX_MISMATCH")
            original = stream.read_original(day, recorded["source_identity"])
            verify_tick_original(original, product, recorded["physical_contract"], "1m", day)
            candle = decode_bar(original.data)
            if (original.stream_id != event.stream_id or original.confirmed_at != stamp(recorded["confirmed_at"])
                    or candle.bar_end != endpoint
                    or any(getattr(candle, key) != (None if recorded[key] is None else Decimal(recorded[key]))
                           for key in ("open", "high", "low", "close", "volume", "open_interest"))):
                raise ValueError("PORTFOLIO_COMPLETED_PREFIX_MISMATCH")
