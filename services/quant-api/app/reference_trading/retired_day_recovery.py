"""Explicit Oct-22 retired-day absence proof; never an automatic recovery policy.

Unlike an open day's apparent silence, a retired journal is fenced by native
monotonic NEW_DAY and both source/completed APPEND registration checks.
"""
from datetime import UTC, date, datetime
import json

from app.market_data.observation_stream import DAILY_LIMIT, ObservationEnvelope
from app.reference_trading.journal_recovery import _digest
from app.reference_trading.repository import RepositoryConflict


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


def _require(value, code):
    if not value:
        raise RepositoryConflict(code)


class RetiredDayAbsenceAuthority:
    """Prove only the sealed Oct-22 H1 suffix, preserving every saved original."""

    def __init__(self, journal, authority, *, source, contract_for_day, verify_fence):
        if journal.kind != "completed" or source.kind != "source":
            raise ValueError("RETIRED_DAY_AUTHORITY_INVALID")
        self.journal, self.source, self.authority = journal, source, authority
        self.contract_for_day, self.verify_fence = contract_for_day, verify_fence
        self._validated_snapshots = {}

    def _sealed(self):
        day, next_day = date(2026, 10, 22), date(2026, 10, 23)
        registrations = {}
        for stream, consumers in ((self.source, ("live",)), (self.journal, ("alert", "reference"))):
            for consumer in consumers:
                registered = stream.registered_day(consumer)
                _require(registered == next_day, "RETIRED_DAY_NOT_SEALED")
                registrations[f"{stream.kind}:{consumer}"] = registered.isoformat()
                for retired in (date(2026, 10, 21), day):
                    cursor = stream.cursor(consumer, retired)
                    _require(cursor == stream.tail(retired), "RETIRED_DAY_NOT_DRAINED")
                    registrations[f"{stream.kind}:{consumer}:{retired}"] = cursor
        return registrations

    def _snapshot(self, stream, day):
        _require(stream.redis.exists(stream.key(day)) and stream.redis.exists(stream.identity_key(day)),
                 "RETIRED_DAY_JOURNAL_MISSING")
        rows = stream.redis.xrange(stream.key(day), count=DAILY_LIMIT + 1)
        _require(0 < len(rows) <= DAILY_LIMIT, "RECOVERY_JOURNAL_BUDGET_EXCEEDED")
        raw_index = stream.redis.hgetall(stream.identity_key(day))
        cached = self._validated_snapshots.get((stream.kind, day))
        # Every admission still reads and compares every raw row and index byte.
        # Only repeat JSON decoding is avoided, never source revalidation.
        if cached is not None and tuple(rows) == cached[0] and raw_index == cached[1]:
            _require(stream.tail(day) == cached[3]["tail"], "RETIRED_DAY_JOURNAL_CHANGED")
            return cached[2], dict(cached[3])
        _require(cached is None, "RETIRED_DAY_JOURNAL_CHANGED")
        index = {_text(k): _text(v) for k, v in raw_index.items()}
        originals = []
        for raw_id, fields in rows:
            item_id = _text(raw_id)
            raw = _text(fields.get(b"envelope", fields.get("envelope")))
            try:
                event = ObservationEnvelope.from_json(raw, stream_id=item_id)
                record = json.loads(index[event.observation_id])
            except (ValueError, KeyError, TypeError) as error:
                raise RepositoryConflict("RETIRED_DAY_JOURNAL_INVALID") from error
            _require(event.trading_day == day and record.get("id") == item_id
                     and record.get("payload") == raw, "RETIRED_DAY_INDEX_CONFLICT")
            content = json.loads(event.to_json())
            if stream.kind == "source":
                content.pop("source_observed_at")
                content.pop("raw_received_at")
            fingerprint = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
            _require("content" not in record or record["content"] == fingerprint,
                     "RETIRED_DAY_INDEX_CONFLICT")
            originals.append((event, [item_id, raw]))
        _require(len(index) == len(rows), "RETIRED_DAY_INDEX_CONFLICT")
        snapshot = {"tail": stream.tail(day), "count": len(rows),
                    "rows_sha256": _digest([row for _, row in originals]),
                    "index_sha256": _digest(sorted(index.items()))}
        self._validated_snapshots[stream.kind, day] = (
            tuple((item_id, dict(fields)) for item_id, fields in rows), dict(raw_index), originals, dict(snapshot))
        return originals, snapshot

    def freeze(self, identity, previous_watermark):
        day = date(2026, 10, 22)
        cutoff = datetime(2026, 10, 22, 7, tzinfo=UTC)
        _require(identity.frequency == "60m" and previous_watermark is not None
                 and datetime(2026, 10, 21, 7, tzinfo=UTC) <= previous_watermark < cutoff < datetime.now(UTC),
                 "RETIRED_DAY_SCOPE_INVALID")
        fence = self.verify_fence()
        _require(isinstance(fence, dict) and fence, "RETIRED_DAY_FENCE_UNPROVEN")
        registrations = self._sealed()
        journals = {}
        # Scan every retained day intersecting the watermark, not only the last
        # day: an already saved original may never be relabelled as absent.
        days = (date(2026, 10, 21), day)
        for candidate in days:
            for stream in (self.source, self.journal):
                originals, snapshot = self._snapshot(stream, candidate)
                journals[f"{stream.kind}:{candidate}"] = snapshot
                if stream.kind == "completed":
                    for event, _ in originals:
                        if event.channel != f"live:bar:{identity.product}:60m":
                            continue
                        end = datetime.fromisoformat(event.data["bar_end"])
                        _require(not previous_watermark < end <= cutoff,
                                 "RETIRED_DAY_SAVED_ORIGINAL_FIRST")
        contract = self.contract_for_day(identity.product, day)
        endpoints = self.authority.expected_endpoints(identity, contract, day, previous_watermark, cutoff)
        _require(endpoints and tuple(sorted(set(endpoints))) == tuple(endpoints)
                 and all(previous_watermark < end <= cutoff for end in endpoints),
                 "RETIRED_DAY_ENDPOINTS_INVALID")
        owners = [self.authority.owner_segments(identity, contract, day, end) for end in endpoints]
        _require(self._sealed() == registrations and self.verify_fence() == fence,
                 "RETIRED_DAY_FENCE_CHANGED")
        proof = {"kind": "RETIRED_DAY_ABSENCE_V1", "day": day.isoformat(),
                 "product": identity.product, "frequency": identity.frequency,
                 "contract": contract, "cutoff": cutoff.isoformat(),
                 "previous_watermark": previous_watermark.isoformat(),
                 "missing_endpoints": [end.isoformat() for end in endpoints],
                 "owners": [list(owner) for owner in owners],
                 "registrations": registrations, "journals": journals, "fence": fence}
        return proof, tuple(endpoints)

    def verify_gap(self, identity, previous_watermark, proof):
        fresh, missing = self.freeze(identity, previous_watermark)
        _require(fresh == proof, "RECOVERY_SOURCE_DRIFT")
        return missing
