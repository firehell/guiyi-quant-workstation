"""Run the existing historical Reference projector from a verified Market receipt."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Callable
from datetime import UTC, date, datetime
import json
from pathlib import Path
import re
from time import monotonic
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.db.readonly import readonly_transaction
from app.market_data.after_market_history import _bytes, publish_history
from app.market_data.market_archive import (
    MarketArchiveReceipt, RECEIPT_DIRECTORY, archive_receipt, read_archive_receipt,
    reference_catalog_revision, require_isolated_archive,
)
from app.reference_trading.historical_refresh import build_historical_refresh, canonical_newow_history_identity
from app.reference_trading.recording_scope import FREQUENCIES, STRATEGIES
from app.services.newow_reference_mode import market_foundation_isolated


_CONSUMED = "newow-reference-consumed"
_MAX_ELAPSED = 1_800.0
_MAX_TICKS = 4_320


def _acknowledged_routes(sandbox: Path, identity: str) -> tuple[str, ...]:
    try:
        existing = json.loads(_bytes(sandbox / _CONSUMED / f"{identity}.json"))
    except FileNotFoundError:
        return ()
    routes = existing.get("routes") if isinstance(existing, dict) else None
    if (not isinstance(routes, list) or not routes
            or any(not isinstance(key, str) or re.fullmatch(r"reference-stream:[0-9a-f]{64}", key) is None
                   for key in routes)
            or routes != sorted(set(routes)) or existing.get("receipt") != identity):
        raise ValueError("MARKET_REFERENCE_ACK_INVALID")
    return tuple(routes)


def consume_receipt(
    sandbox: Path, receipt: MarketArchiveReceipt, *,
    refresh: Callable[[MarketArchiveReceipt, set[str], Callable[[], bool]], tuple[str, ...]],
    stop_requested: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """A finished cohort is acknowledged once; partial progress stays in the native runner."""
    acknowledgement = sandbox / _CONSUMED / f"{receipt.identity}.json"
    existing = _acknowledged_routes(sandbox, receipt.identity)
    if existing:
        return {"status": "already_consumed", "receipt": receipt.identity, "routes": len(existing)}

    deadline = monotonic() + _MAX_ELAPSED
    def cancelled():
        return stop_requested() or monotonic() >= deadline

    completed: set[str] = set()
    expected = None
    stalled = 0
    for _ in range(_MAX_TICKS):
        if cancelled():
            break
        before = len(completed)
        routes = tuple(sorted(refresh(receipt, completed, cancelled)))
        if not routes:
            return {"status": "no_routes", "receipt": receipt.identity}
        if (len(routes) != len(set(routes)) or not completed <= set(routes)
                or expected is not None and routes != expected):
            raise ValueError("MARKET_REFERENCE_SCOPE_CHANGED")
        expected = routes
        stalled = 0 if len(completed) > before else stalled + 1
        if len(completed) == len(routes):
            publish_history(acknowledgement, {"receipt": receipt.identity, "routes": list(routes)})
            return {"status": "completed", "receipt": receipt.identity, "routes": len(routes)}
        if stalled > len(routes):
            break
    return {"status": "pending", "receipt": receipt.identity, "routes_complete": len(completed)}


def run_receipt(
    sandbox: Path, receipt: MarketArchiveReceipt, *, session_factory,
    canonical_root: Path | None = None, stop_requested: Callable[[], bool] = lambda: False,
    formal: bool = False,
) -> dict:
    from app.market_data.product_retirement import assert_products_not_retired

    assert_products_not_retired(tuple(receipt.revisions))

    def verify_publication(product):
        # Called inside the native Catalog maintenance lease when planning,
        # verifying or committing one product. Never hold that lease for a cohort.
        with session_factory() as session, readonly_transaction(session, timeout_seconds=30):
            actual = (reference_catalog_revision(session, product, receipt.trading_day, archive_scope=True)
                      if formal else reference_catalog_revision(session, product, receipt.trading_day))
        if actual != receipt.revisions.get(product):
            raise ValueError("MARKET_ARCHIVE_SOURCE_CHANGED")

    runner = build_historical_refresh(
        session_factory,
        state_path=sandbox / "newow-historical-refresh-state.json",
        publication_products=tuple(receipt.revisions),
        verify_publication=verify_publication,
    )

    expected = {
        (product, frequency_index, strategy_index)
        for product in receipt.revisions
        for frequency_index in range(len(FREQUENCIES))
        for strategy_index in range(len(STRATEGIES))
    }

    def refresh(source, completed, cancelled):
        runner.tick(now=source.finished_at, cancelled=cancelled, completed_routes=completed)
        if runner.last_progress.get("reason") == "MARKET_ARCHIVE_SOURCE_CHANGED":
            raise ValueError("MARKET_ARCHIVE_SOURCE_CHANGED")
        if {key for _stream_id, key in runner.last_scope} != expected:
            raise ValueError("MARKET_REFERENCE_SCOPE_INCOMPLETE")
        return tuple(stream_id for stream_id, _key in runner.last_scope)

    from app.market_data.live_recovery_guard import _file_guard

    with _file_guard("newow-receipt.lock", root=sandbox / "live-recovery-guards", wait=False, legacy_root=True):
        result = consume_receipt(sandbox, receipt, refresh=refresh, stop_requested=stop_requested)
    if not stop_requested() and result["status"] in {"completed", "already_consumed"}:
        from app.market_data.newow.market_reference_sections import materialize_sections

        result["sections"] = materialize_sections(
            sandbox, receipt, session_factory=session_factory, verify_publication=verify_publication,
            canonical_root=canonical_root, formal=formal, stop_requested=stop_requested,
        )
    return result


def latest_reference(product: str, strategy: str, frequency: str, *, session_factory) -> dict | None:
    """Select the existing committed calculation and expose its exact read window."""
    from sqlalchemy import and_, func, select

    from app.market_data.product_retirement import assert_not_retired
    from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream

    assert_not_retired(product)
    if re.fullmatch(r"[a-z]{1,8}", product) is None or strategy not in STRATEGIES or frequency not in FREQUENCIES:
        raise ValueError("MARKET_REFERENCE_SCOPE_INVALID")
    identity = canonical_newow_history_identity(product, strategy, frequency)
    with session_factory() as session, readonly_transaction(session, timeout_seconds=15):
        row = session.execute(select(
            ReferenceBatch.revision_id, ReferenceBatch.seq,
            ReferenceBatch.computed_through, ReferenceBatch.processed_at,
            ReferenceBatch.dependency_manifest["query_since"].as_string(),
            func.coalesce(
                ReferenceBatch.source_evidence["page_material_v1"]["binding"]["result_trading_day"].as_string(),
                ReferenceBatch.dependency_manifest["query_through"].as_string(),
            ),
        ).select_from(ReferenceStream).join(ReferenceRevision, and_(
            ReferenceRevision.stream_id == ReferenceStream.stream_id,
            ReferenceRevision.revision_id == ReferenceStream.active_revision_id,
        )).join(ReferenceBatch, and_(
            ReferenceBatch.batch_id == ReferenceRevision.checkpoint_batch_id,
            ReferenceBatch.stream_id == ReferenceStream.stream_id,
            ReferenceBatch.revision_id == ReferenceRevision.revision_id,
            ReferenceBatch.seq == ReferenceRevision.last_seq,
            ReferenceBatch.seq == ReferenceStream.latest_seq,
        )).where(
            ReferenceStream.stream_id == identity.stream_id,
            ReferenceRevision.status == "active",
            ReferenceBatch.kind == "calculation",
            ReferenceBatch.outcome == "committed",
        )).one_or_none()
    if row is None:
        return None
    revision, sequence, cutoff, processed, since, through = row
    if (cutoff is None or processed is None or not isinstance(since, str)
            or not isinstance(through, str) or date.fromisoformat(since) > date.fromisoformat(through)):
        raise ValueError("MARKET_REFERENCE_RESULT_INVALID")
    # SQLite strips timezone information from test rows. Canonical endpoints are UTC.
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    if processed.tzinfo is None:
        processed = processed.replace(tzinfo=UTC)
    return {
        "stream_id": identity.stream_id, "revision_id": revision, "seq": sequence,
        "since": since, "through": through, "cutoff": cutoff, "computed_at": processed,
    }


def latest_formal_reference(product: str, strategy: str, frequency: str, *, session_factory) -> dict | None:
    """Expose the Market result only after the exact formal receipt was acknowledged."""
    from app.market_data.market_archive import current_retained_receipt, formal_archive_root
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.product_retirement import assert_not_retired

    assert_not_retired(product)
    root = formal_archive_root()
    receipt = current_retained_receipt(root, now=datetime.now(UTC))
    if receipt is None:
        return None
    if set(receipt.revisions) != set(load_operational_products()):
        raise ValueError("MARKET_ARCHIVE_RECEIPT_SCOPE_INVALID")
    if product not in receipt.revisions:
        return None
    routes = _acknowledged_routes(root, receipt.identity)
    if not routes:
        return None
    result = latest_reference(product, strategy, frequency, session_factory=session_factory)
    if result is None or result["stream_id"] not in routes or result["cutoff"] > receipt.finished_at:
        return None
    return {**result, "receipt": receipt.identity}


def present_saved_chart(
    reader, stream_id: str, *, since: date, through: date, cutoff: datetime,
    snapshot: str, bar_from: datetime, bar_through: datetime,
) -> dict:
    """Relate stored actions and hints to a matching persisted, hashed chart frame."""
    stored = reader.presentation_facts(
        stream_id, since=since, through=through, cutoff=cutoff, snapshot_token=snapshot,
        bar_from=bar_from, bar_through=bar_through, kinds=("indicator", "action", "hint"),
        max_points=8_000,
    )
    frames = []
    indexed = {}
    for point in stored["indicator"]:
        row = point["value"]
        source_hash = row.get("source_bar_sha256")
        if (row.get("version") != "newow_bar_state_v1" or not isinstance(source_hash, str)
                or re.fullmatch(r"[a-f0-9]{64}", source_hash) is None
                or not isinstance(row.get("physical_contract"), str)
                or not isinstance(row.get("main_values"), dict)):
            continue
        frame = {
            **row, "trading_day": point["trading_day"], "formula_versions": point["formula_versions"],
            "actions": [], "hints": [],
        }
        frames.append(frame)
        for key, target in (("action_ids", "actions"), ("hint_ids", "hints")):
            for identifier in row.get(key, ()):
                identity = (target, point["trading_day"], row["bar_end"], identifier)
                # Ambiguous matches carry no display authority.
                indexed[identity] = None if identity in indexed else frame

    for key, destination in (("action", "actions"), ("hint", "hints")):
        for point in stored[key]:
            value = point["value"]
            identifier = (value.get("signal_id") or value.get("source_signal_id")
                          if key == "action" else value.get("hint_id"))
            target = indexed.get((destination, point["trading_day"], value["bar_end"], identifier))
            if target is not None and all(value.get(field, target.get(field)) == target.get(field)
                                          for field in ("physical_contract", "segment_id", "calculation_segment_id")):
                target[destination].append(value)
    return {"snapshot": snapshot, "frames": frames,
            "main_status": "saved" if frames else "not_materialized",
            "auxiliary_status": "not_materialized",
            "explanation_status": "not_materialized",
            "comparator_status": "not_materialized"}


def _current_scope_receipt(receipt, products):
    from app.market_data.product_retirement import RS_RETIREMENT_SCOPE_DELTA

    if receipt is None or set(receipt.revisions) == products:
        return receipt
    if set(receipt.revisions) == products | RS_RETIREMENT_SCOPE_DELTA:
        return None
    raise ValueError("MARKET_ARCHIVE_RECEIPT_SCOPE_INVALID")


def warmup_formal_receipts(*, archive_root: Path | None = None) -> dict:
    """Prove the formal receipt source without calculating or polling Live."""
    from app.db.session import engine
    from app.market_data.composition import canonical_root
    from app.market_data.market_archive import current_retained_receipt, formal_archive_root
    from app.market_data.market_foundation_scope import require_formal_tick_binding
    from app.market_data.operational_universe import load_operational_products
    from app.redis_connections import get_redis_connection

    with get_redis_connection() as redis:
        binding = require_formal_tick_binding(redis, engine.url, canonical_root())
    receipt = _current_scope_receipt(
        current_retained_receipt(
            formal_archive_root() if archive_root is None else archive_root, now=datetime.now(UTC),
        ),
        set(load_operational_products()),
    )
    return {"receipt_only": True, "binding": binding,
            "receipt": None if receipt is None else receipt.identity, "natural_archive_verified": False}


def serve_formal_receipts(ownership, *, stop_requested):
    """Supervised, receipt-only Reference role. No Live subscription or transport."""
    from time import sleep

    from app.compute_runtime.formal_publications import FormalCanonicalPublications
    from app.db.session import SessionLocal, engine
    from app.market_data.composition import canonical_root
    from app.market_data.market_archive import current_retained_receipt, formal_archive_root
    from app.market_data.market_foundation_scope import require_formal_tick_binding
    from app.market_data.operational_universe import load_operational_products
    from app.redis_connections import get_redis_connection
    from redis.exceptions import RedisError

    canonical = canonical_root()
    products = set(load_operational_products())
    completed_receipt = None

    def stopping():
        return stop_requested() or ownership.should_drain()

    heartbeat_at = monotonic()

    def check_owner():
        nonlocal heartbeat_at
        ownership.assert_owned()
        if stopping():
            return True
        if monotonic() - heartbeat_at >= 5:
            ownership.mark_ready({"reference_receipts": "calculating"})
            heartbeat_at = monotonic()
        return False

    with (get_redis_connection() as redis,
          FormalCanonicalPublications(engine, canonical, now=lambda: datetime.now(UTC)) as compute):
        while not check_owner():
            try:
                require_formal_tick_binding(redis, engine.url, canonical)
                root = formal_archive_root()
                receipt = _current_scope_receipt(
                    current_retained_receipt(root, now=datetime.now(UTC)), products,
                )
                status = "waiting_archive" if receipt is None else "current"
                if receipt is not None and receipt.identity != completed_receipt:
                    ownership.mark_ready({"reference_receipts": "calculating"})
                    try:
                        result = run_receipt(root, receipt, session_factory=SessionLocal,
                                             canonical_root=canonical, stop_requested=check_owner, formal=True)
                    except RuntimeError as error:
                        if str(error) != "LIVE_RECOVERY_BUSY":
                            raise
                        result = {"status": "pending"}
                    except (OSError, ValueError, SQLAlchemyError):
                        result = {"status": "unavailable"}
                    if (result["status"] in {"completed", "already_consumed"}
                            and result.get("sections", {}).get("status") == "completed"):
                        completed_receipt = receipt.identity
                    else:
                        status = "unavailable" if result["status"] == "unavailable" else "pending"
                try:
                    compute_status = compute.poll(root, receipt, stop_requested=check_owner)
                except (OSError, ValueError, RuntimeError, SQLAlchemyError):
                    compute_status = "pending"
                if stopping():
                    break
                health = {"reference_receipts": status, "canonical_compute": compute_status}
                if status == "unavailable":
                    ownership.mark_not_ready({**health, "failure_code": "MARKET_REFERENCE_RECEIPT_UNAVAILABLE"})
                else:
                    ownership.mark_ready(health)
            except (OSError, ValueError, RedisError, SQLAlchemyError):
                ownership.mark_not_ready({"reference_receipts": "unavailable",
                                          "failure_code": "MARKET_REFERENCE_RECEIPT_UNAVAILABLE"})
            for _ in range(5):
                if stopping():
                    return
                sleep(1)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", help="Exact Market archive receipt SHA-256; defaults to current status")
    arguments = parser.parse_args()
    if arguments.receipt is not None and not re.fullmatch(r"[0-9a-f]{64}", arguments.receipt):
        raise SystemExit("MARKET_ARCHIVE_RECEIPT_INVALID")
    from app.market_data.market_foundation_scope import formal_tick_requested, require_formal_tick_binding

    formal = formal_tick_requested()
    if not market_foundation_isolated() and not formal:
        raise SystemExit("MARKET_FOUNDATION_ISOLATION_REQUIRED")
    if formal and arguments.receipt is None:
        raise SystemExit("MARKET_ARCHIVE_RECEIPT_REQUIRED")
    from app.db.session import SessionLocal, engine
    from app.market_data.composition import canonical_root
    from app.redis_connections import REDIS_URL
    from app.market_data.after_market import _load_status
    from app.market_data.market_archive import retain_archive_receipt

    try:
        root = canonical_root()
        if formal:
            from app.market_data.market_archive import formal_archive_root
            from app.redis_connections import get_redis_connection

            with get_redis_connection() as redis:
                require_formal_tick_binding(redis, engine.url, root)
            sandbox = formal_archive_root()
        else:
            sandbox = require_isolated_archive(engine.url, REDIS_URL, root)
        now = datetime.now(UTC)
        identity = arguments.receipt
        if identity is None:
            status_path = sandbox / "after-market-status.json"
            current = archive_receipt(_load_status(status_path), now=now)
            if current is None:
                raise ValueError("MARKET_ARCHIVE_RECEIPT_INVALID")
            retain_archive_receipt(status_path, now=now)
            identity = current.identity
        receipt = read_archive_receipt(sandbox / RECEIPT_DIRECTORY / f"{identity}.json", now=now)
        if formal:
            from app.market_data.operational_universe import load_operational_products

            if set(receipt.revisions) != set(load_operational_products()):
                raise ValueError("MARKET_ARCHIVE_RECEIPT_SCOPE_INVALID")
            # The supervised worker and this recovery entry serialize the
            # actual calculation for this receipt in the shared runner.
        result = run_receipt(sandbox, receipt, session_factory=SessionLocal, canonical_root=root, formal=formal)
    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as error:
        code = str(error)
        if not re.fullmatch(r"MARKET_[A-Z_]{1,64}", code):
            code = "MARKET_REFERENCE_UNAVAILABLE"
        raise SystemExit(code) from None
    print(json.dumps(result, sort_keys=True))
    if result["status"] in {"pending", "no_routes"} or result.get("sections", {}).get("status") == "pending":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
