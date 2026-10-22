"""Read-only provenance for normal retained completed originals, never repair receipts."""

from datetime import date, datetime
from hashlib import sha256
import json

from app.market_data.observation_stream import (
    DAILY_LIMIT,
    ObservationEnvelope,
    ObservationStream,
    _text,
)
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.repository import RepositoryConflict


def _require(value):
    if not value:
        raise RepositoryConflict("RETAINED_OBSERVATION_UNVERIFIED")


def read_retained_interval(
    journal: ObservationStream,
    *,
    product: str,
    day: date,
    after: datetime,
    before: datetime,
    expected_endpoints: tuple[datetime, ...],
    knowledge_at: datetime,
) -> tuple[tuple[ObservationEnvelope, dict], ...]:
    """Check exact envelope/index bytes and a caller's authoritative ordered Session range.

    No cursor or registration writes. New unrelated rows may append; changing an
    original in the selected bounded interval changes its durable provenance.
    """
    _require(
        journal.kind == "completed"
        and after < before
        and after <= knowledge_at
        and tuple(sorted(set(expected_endpoints))) == expected_endpoints
        and len(expected_endpoints) <= 256
        and all(
            after < end < before and end <= knowledge_at for end in expected_endpoints
        )
    )
    rows = journal.redis.xrange(
        journal.key(day), min="-", max="+", count=DAILY_LIMIT + 1
    )
    _require(len(rows) <= DAILY_LIMIT)
    selected = []
    for identifier, fields in rows:
        raw = fields.get(b"envelope", fields.get("envelope"))
        _require(raw is not None)
        text = _text(raw)
        try:
            event = ObservationEnvelope.from_json(text, stream_id=_text(identifier))
            if event.channel != f"live:bar:{product}:60m":
                continue
            end = datetime.fromisoformat(event.data["bar_end"])
            if not after < end < before:
                continue
            _require(
                event.trading_day == day
                and event.data["trading_day"] == day.isoformat()
                and event.notification_eligible
                and event.raw_received_at is not None
                and event.confirmed_at is not None
                and end <= event.confirmed_at <= knowledge_at
                and event.raw_received_at
                == event.source_observed_at
                <= event.confirmed_at
                and event.observation_id
                == f"{day}:{event.data['contract']}:60m:{end.isoformat()}"
            )
            index_raw = journal.redis.hget(
                journal.identity_key(day), event.observation_id
            )
            _require(index_raw is not None)
            index = json.loads(index_raw)
            _require(
                index.get("id") == event.stream_id
                and index.get("payload") == text
                and ("content" not in index or index["content"] == event.to_json())
            )
            selected.append((end, event, text, _text(index_raw)))
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise RepositoryConflict("RETAINED_OBSERVATION_UNVERIFIED") from error
    selected.sort(key=lambda row: row[0])
    _require(tuple(row[0] for row in selected) == expected_endpoints)
    interval_hash = manifest_sha256(
        [[event.stream_id, text, index] for _, event, text, index in selected]
    )
    result = []
    for _, event, text, index in selected:
        envelope_hash = sha256(text.encode()).hexdigest()
        index_hash = sha256(index.encode()).hexdigest()
        proof = {
            "provenance": "retained_completed_observation_v1",
            "journal_key": journal.key(day),
            "journal_id": event.stream_id,
            "observation_id": event.observation_id,
            "envelope_sha256": envelope_hash,
            "identity_index_sha256": index_hash,
            "interval_sha256": interval_hash,
            "original_readback_sha256": manifest_sha256(
                {
                    "journal_key": journal.key(day),
                    "journal_id": event.stream_id,
                    "envelope": text,
                    "identity_index": index,
                }
            ),
        }
        result.append((event, proof))
    return tuple(result)
