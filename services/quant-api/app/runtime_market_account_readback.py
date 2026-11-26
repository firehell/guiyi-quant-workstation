"""Independent read-only account watermarks for a Market source handoff."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import re

from app.market_data.observation_stream import ObservationEnvelope, _text
from app.runtime_cohort_errors import CohortError
from app.subing_model.account import decode_execution
from app.subing_portfolio_journal import PortfolioJournal, source_hashes, stamp
from guiyi_quant.htdy_account_execution.scope import scope_status
from guiyi_quant.htdy_account_execution.store import LocalStore


def tq_watermark(path, account_id, expected, now):
    state = LocalStore.inspect_tip(path)
    if state.account_id != account_id:
        raise CohortError("TQ_HANDOFF_ACCOUNT_MISMATCH")
    scope = scope_status(state, now)
    watermarks = {
        row.product.lower(): {
            "contract": row.owner,
            "bar_end": row.last_bar.isoformat() if row.last_bar else None,
        }
        for row in state.products
        if row.product.lower() in expected
    }
    current = {
        name: (row["contract"], stamp(row["bar_end"]) if row["bar_end"] else None)
        for name, row in watermarks.items()
    }
    orders = sum(not row.reconciled for row in state.orders)
    reservations = sum(not row.released for row in state.reservations)
    obligations_clear = (
        scope["status"] == "ACTIVE"
        and {item.lower() for item in scope.get("products", ())} == set(expected)
        and not (orders or reservations or state.unresolved_fill_ids or state.blocked_products)
        and not any(row.rolling or row.must_close for row in state.products)
    )
    return {
        "status": "verified" if current == expected and obligations_clear else "blocked",
        "scope_status": scope["status"],
        "sqlite_proof": "projection_and_committed_tip",
        "readback_valid": state.readback_valid,
        "readback_valid_until": state.readback.valid_until.isoformat(),
        "unreconciled_orders": orders,
        "unreleased_reservations": reservations,
        "unresolved_fills": len(state.unresolved_fill_ids),
        "watermarks": watermarks,
        "mismatched_products": sorted(name for name in expected if current.get(name) != expected[name]),
    }


def _paper_observation(stream, day, product, row, *, generation_prefix):
    bar = decode_execution(row["execution"]).bar
    stream_id = row["producer_stream_id"]
    if not re.fullmatch(r"[0-9]+-[0-9]+", stream_id):
        raise CohortError("SUBING_HANDOFF_SOURCE_ID_INVALID")
    found = stream.redis.xrange(stream.key(day), min=stream_id, max=stream_id, count=1)
    if not found:
        raise CohortError("SUBING_HANDOFF_SOURCE_MISSING")
    identifier, fields = found[0]
    raw = _text(fields.get("envelope", fields.get(b"envelope")))
    event = ObservationEnvelope.from_json(raw, stream_id=_text(identifier))
    indexed = stream.redis.hget(stream.identity_key(day), bar.source_identity)
    index = json.loads(indexed) if indexed else {}
    # The original Paper decoder ignores the new field. Its persisted input
    # refers to the exact envelope, so verify generation from that envelope.
    generation = json.loads(raw).get("source_generation")
    mode_matches = (
        generation is None if generation_prefix is None else
        isinstance(generation, str)
        and re.fullmatch(r"rqdata-tick:[0-9a-f]{32}:[1-9][0-9]*", generation) is not None
        and generation.startswith(generation_prefix)
    )
    if (
        not mode_matches
        or event.trading_day != day or bar.trading_day != day
        or event.channel != f"live:bar:{product}:1m"
        or event.observation_id != bar.source_identity
        or event.data["contract"] != bar.physical_contract
        or stamp(event.data["bar_end"]) != bar.bar_end
        or event.confirmed_at != bar.confirmed_at
        or not event.notification_eligible
        or any(
            (Decimal(str(event.data[field])) if event.data.get(field) is not None else None)
            != getattr(bar, field)
            for field in ("open", "high", "low", "close", "volume", "open_interest")
        )
        or index.get("id") != stream_id or index.get("payload") != raw
    ):
        raise CohortError("SUBING_HANDOFF_SOURCE_MISMATCH")
    return {
        "contract": bar.physical_contract,
        "bar_end": bar.bar_end.isoformat(),
        "stream_id": stream_id,
        "observation_id": event.observation_id,
        "source_generation": generation,
    }


def paper_watermark(store, run_id, stream, day: date, expected, *, generation_prefix=None, source_root=None):
    # ModelStore independently verifies the journal hash chain. Replay verifies
    # both projection and the exact active policy/source-code identity.
    head, events = store.load(run_id)
    if source_root is not None and (
        set(head["identity"]["code_hashes"]) != set(source_hashes())
        or any(
            (source_root / name).resolve(strict=True) != source_root / name
            or sha256((source_root / name).read_bytes()).hexdigest() != digest
            for name, digest in head["identity"]["code_hashes"].items()
        )
    ):
        raise CohortError("SUBING_HANDOFF_CODE_IDENTITY_CHANGED")

    class Snapshot:
        def load(self, requested_run):
            if requested_run != run_id:
                raise CohortError("SUBING_HANDOFF_RUN_CHANGED")
            return head, events

    journal = PortfolioJournal.restore(Snapshot(), run_id)
    if journal.day != day or set(journal.products) != set(expected):
        raise CohortError("SUBING_HANDOFF_DAY_OR_SCOPE_MISMATCH")
    terminals = {}
    for batch in reversed(events):
        if batch["day"] != day.isoformat() or len(terminals) == len(expected):
            break
        for product, row in batch["rows"].items():
            if product not in terminals:
                terminals[product] = _paper_observation(
                    stream, day, product, row, generation_prefix=generation_prefix,
                )
    actual = {
        product: (row["contract"], datetime.fromisoformat(row["bar_end"]))
        for product, row in terminals.items()
    }
    return {
        "status": "verified" if actual == expected else "blocked",
        "run_id": run_id,
        "sequence": head["sequence"],
        "tail_hash": head["tail_hash"],
        "committed_minute": journal.portfolio.last_at.isoformat(),
        "watermarks": terminals,
        "mismatched_products": sorted(name for name in expected if actual.get(name) != expected[name]),
    }


def _paper_reader():
    """Run the audit against the original Paper checkout, using a private pipe."""
    from contextlib import closing
    from pathlib import Path
    import sys

    from redis import Redis
    from sqlalchemy import select

    from app.market_data.observation_stream import ObservationStream
    from app.subing_model.store import ModelStore, runs

    stage = "request"
    try:
        request = json.load(sys.stdin)
        root = Path(request["root"])
        from app.subing_model.worker import ROOT

        if ROOT != root:
            raise CohortError("SUBING_HANDOFF_REPLAY_ROOT_CHANGED")
        day = date.fromisoformat(request["trading_day"])
        expected = {
            product: (contract, stamp(at))
            for product, (contract, at) in request["expected"].items()
        }
        stage = "database_configuration"
        store = ModelStore(request["database_url"])
        try:
            store.engine = store.engine.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True,
            )
            with closing(Redis.from_url(
                request["redis_url"], socket_connect_timeout=3, socket_timeout=5,
            )) as redis:
                stream = ObservationStream(redis, kind="completed")

                def redis_frontier():
                    run_id = redis.info("server").get("run_id")
                    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{40}", run_id):
                        raise CohortError("SUBING_HANDOFF_REDIS_INSTANCE_UNPROVEN")
                    return [sha256(run_id.encode("ascii")).hexdigest(), stream.tail(day)]

                stage = "journal_and_source"
                if redis_frontier() != request["redis_frontier"]:
                    raise CohortError("SUBING_HANDOFF_REDIS_FRONTIER_CHANGED")
                result = paper_watermark(store, request["run_id"], stream, day, expected, source_root=root)
                result["redis_frontier"] = redis_frontier()
                if result["redis_frontier"] != request["redis_frontier"]:
                    raise CohortError("SUBING_HANDOFF_REDIS_FRONTIER_CHANGED")
            stage = "frontier"
            with store.engine.connect() as connection:
                frontier = connection.execute(
                    select(runs.c.sequence, runs.c.tail_hash).where(runs.c.run_id == request["run_id"])
                ).one()
            if tuple(frontier) != (result["sequence"], result["tail_hash"]):
                raise CohortError("SUBING_HANDOFF_FRONTIER_CHANGED")
        finally:
            store.engine.dispose()
    except CohortError as exc:
        result = {"status": "blocked", "code": str(exc)}
    except Exception as exc:
        error = exc.args[0] if len(exc.args) == 1 else None
        code = error if isinstance(error, str) and error in {
            "MODEL_JOURNAL_INVALID", "MODEL_TAIL_INVALID", "PORTFOLIO_CODE_IDENTITY_CHANGED",
            "PORTFOLIO_RESTART_PARITY_FAILED", "PORTFOLIO_MINUTE_GAP", "PORTFOLIO_DAY_CONTINUITY_UNPROVEN",
        } else "SUBING_HANDOFF_PINNED_REPLAY_FAILED"
        result = {"status": "blocked", "code": code, "stage": stage}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    _paper_reader()
