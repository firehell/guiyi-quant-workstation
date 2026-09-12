"""Composition for explicit diagnostic-only interrupted-run closeout."""

from datetime import datetime
from pathlib import Path

from app.market_data.after_market_closeout import close_interrupted_run
from app.market_data.session_clock import SHANGHAI


def run_closeout_command(args, *, session_factory, manager_factory):
    # Main's default factories belong to the executing checkout, NOT the target.
    # Never use them for cross-root closeout, even when they appear healthy.
    from redis import Redis
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.url import normalize_database_url
    from app.market_data.closeout_binding import RuntimeDataBinding, _redis_url
    from app.market_data.composition import build_historical_data_manager
    from app.market_data.live_market import RedisLiveStore

    engine = redis = outcome = None
    try:
        binding = RuntimeDataBinding(Path(args.runtime_root), args.runtime_commit, args.expected_status_sha256)
        engine = create_engine(normalize_database_url(binding.settings["DATABASE_URL"]))
        redis = Redis.from_url(_redis_url(binding.settings))
        store = RedisLiveStore(redis)
        with Session(engine, autoflush=False) as session:
            manager = build_historical_data_manager(session,
                data_root=Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"]), config_root=binding.root,
                provider_settings=binding.settings)
            def verify(root, commit):
                if root != binding.root or commit != binding.commit:
                    raise ValueError
                binding.check(manager, session, redis, store, lambda: datetime.now(SHANGHAI))
            outcome = close_interrupted_run(manager, root=binding.root,
                expected_commit=binding.commit, expected_status_sha256=args.expected_status_sha256,
                products=binding.products, live_store=store, verify_identity=verify,
                now=lambda: datetime.now(SHANGHAI), apply=args.apply)
            return outcome
    except Exception:
        if outcome is not None:
            return {**outcome, "status": "blocked", "error_code": "AFTER_MARKET_CLOSEOUT_CLEANUP_FAILED"}
        return {"schema_version": 1, "command": "data.close-interrupted-after-market", "status": "blocked",
                "readonly": not args.apply, "status_written": False, "provider_requests": 0, "data_writes": 0,
                "error_code": "AFTER_MARKET_CLOSEOUT_BINDING_UNAVAILABLE"}
    finally:
        if redis is not None:
            try:
                redis.close()
            except Exception:
                pass
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
