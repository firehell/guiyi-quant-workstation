"""Read-only message projection of committed forward Newow display facts."""

from datetime import date

from sqlalchemy import select

from app.db.readonly import readonly_transaction
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceRevision,
    ReferenceStream,
)
from app.reference_trading.presentation import require_envelope
from app.reference_trading.query import QueryConflict

STRATEGIES = ("trend", "oscillation", "main_rise", "dual_fusion")
FREQUENCIES = ("1w", "1d", "60m")


def read_messages(
    factory,
    *,
    since: date,
    through: date,
    product: str | None = None,
    strategy: str | None = None,
    frequency: str | None = None,
    limit: int = 500,
):
    if (
        since > through
        or (through - since).days > 93
        or strategy not in (None, *STRATEGIES)
        or frequency not in (None, *FREQUENCIES)
        or not 1 <= limit <= 500
        or product is not None
        and (not product.isascii() or not product.isalpha() or len(product) > 8)
    ):
        raise QueryConflict("QUERY_INVALID")
    statement = (
        select(ReferenceStream, ReferenceBatch)
        .join(
            ReferenceRevision,
            (ReferenceRevision.stream_id == ReferenceStream.stream_id)
            & (ReferenceRevision.revision_id == ReferenceStream.active_revision_id),
        )
        .join(
            ReferenceBatch,
            (ReferenceBatch.stream_id == ReferenceStream.stream_id)
            & (ReferenceBatch.revision_id == ReferenceRevision.revision_id),
        )
        .where(
            ReferenceStream.recording_mode == "forward_observation",
            ReferenceStream.strategy_code.in_([f"newow_{s}" for s in STRATEGIES]),
            ReferenceStream.frequency.in_(FREQUENCIES),
            ReferenceStream.health == "READY",
            ReferenceRevision.status == "active",
            ReferenceBatch.kind == "calculation",
            ReferenceBatch.seq <= ReferenceStream.latest_seq,
            ReferenceBatch.observed_at.is_not(None),
            ReferenceBatch.source_evidence["presentation_v1"]["last_day"].as_string()
            >= since.isoformat(),
            ReferenceBatch.source_evidence["presentation_v1"]["first_day"].as_string()
            <= through.isoformat(),
        )
    )
    if product:
        statement = statement.where(ReferenceStream.product == product.lower())
    if strategy:
        statement = statement.where(
            ReferenceStream.strategy_code == f"newow_{strategy}"
        )
    if frequency:
        statement = statement.where(ReferenceStream.frequency == frequency)
    items = []
    point_count = 0
    with factory() as session, readonly_transaction(session, timeout_seconds=20):
        rows = session.execute(
            statement.order_by(
                ReferenceBatch.observed_at.desc(), ReferenceBatch.batch_id
            ).limit(10001)
        )
        for count, (stream, batch) in enumerate(rows):
            if count >= 10000:
                raise QueryConflict("QUERY_BUDGET_EXCEEDED")
            points = require_envelope(batch.source_evidence.get("presentation_v1"))
            point_count += len(points)
            if point_count > 100000:
                raise QueryConflict("QUERY_BUDGET_EXCEEDED")
            contracts = {
                p["value"].get("bar_end"): p["value"].get("physical_contract")
                for p in points
                if p.get("kind") == "indicator" and isinstance(p.get("value"), dict)
            }
            for index, point in enumerate(points):
                if point.get("kind") not in {"action", "hint"}:
                    continue
                if (
                    not since.isoformat()
                    <= point.get("trading_day", "")
                    <= through.isoformat()
                ):
                    continue
                value = point.get("value")
                if not isinstance(value, dict) or not isinstance(
                    value.get("bar_end"), str
                ):
                    raise QueryConflict("PRESENTATION_CORRUPT")
                items.append(
                    {
                        "id": f"{batch.batch_id}:{index}",
                        "stream_id": stream.stream_id,
                        "revision_id": batch.revision_id,
                        "symbol": stream.product,
                        "strategy": stream.strategy_code.removeprefix("newow_"),
                        "frequency": stream.frequency,
                        "contract": value.get("physical_contract")
                        or contracts.get(value["bar_end"]),
                        "bar_end": value["bar_end"],
                        "trading_day": point["trading_day"],
                        "observed_at": batch.observed_at.isoformat(),
                        "point": point,
                        "page_parity": True,
                        "executable": False,
                    }
                )
    items.sort(key=lambda item: (item["bar_end"], item["id"]), reverse=True)
    return {
        "items": items[:limit],
        "truncated": len(items) > limit,
        "limit": limit,
        "recording_mode": "forward_observation",
        "page_parity": True,
        "executable": False,
    }
