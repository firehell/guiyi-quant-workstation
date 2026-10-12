"""Read-only exact gap planning against the entire retained completed journal."""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json

from app.market_data.observation_stream import ObservationEnvelope, DAILY_LIMIT
from app.reference_trading.repository import RepositoryConflict


def _digest(rows):
    return sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class JournalRecoveryAuthority:
    def __init__(self, journal, authority):
        if journal.kind != "completed":
            raise ValueError("RECOVERY_COMPLETED_JOURNAL_REQUIRED")
        self.journal, self.authority = journal, authority

    def freeze(self, identity, previous_watermark, *, day, expected_cursor, tail_id=None):
        """Freeze exact originals, including already-acknowledged but uncomputed Bars.

        Only absent authoritative endpoints form the interruption. This first
        bounded renewal accepts a missing prefix; internal holes fail closed.
        """
        if self.journal.cursor("reference", day) != expected_cursor:
            raise RepositoryConflict("RECOVERY_CURSOR_DRIFT")
        tail_id = tail_id or self.journal.tail(day)
        raw_rows = self.journal.redis.xrange(self.journal.key(day), min="-", max=tail_id,
                                             count=DAILY_LIMIT + 1)
        if len(raw_rows) > DAILY_LIMIT:
            raise RepositoryConflict("RECOVERY_JOURNAL_BUDGET_EXCEEDED")
        selected = []
        for raw_id, fields in raw_rows:
            item_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            raw = fields.get(b"envelope", fields.get("envelope"))
            if raw is None:
                raise RepositoryConflict("RECOVERY_JOURNAL_INVALID")
            text = raw.decode() if isinstance(raw, bytes) else raw
            item = ObservationEnvelope.from_json(text, stream_id=item_id)
            if item.channel != f"live:bar:{identity.product}:{identity.frequency}":
                continue
            end = datetime.fromisoformat(item.data["bar_end"])
            if previous_watermark is not None and end <= previous_watermark:
                continue
            if (not item.notification_eligible or item.confirmed_at is None
                    or item.trading_day != day or item.confirmed_at < end):
                raise RepositoryConflict("RECOVERY_JOURNAL_INVALID")
            self.authority.owner_segments(identity, item.data["contract"], day, end)
            selected.append((end, item_id, text))
        selected.sort(key=lambda item: (item[0], item[1]))
        if not selected or len({item[0] for item in selected}) != len(selected):
            raise RepositoryConflict("RECOVERY_JOURNAL_INVALID")
        originals = [ObservationEnvelope.from_json(raw, stream_id=item_id)
                     for _end, item_id, raw in selected]
        contracts = {item.data["contract"] for item in originals}
        if len(contracts) != 1:
            raise RepositoryConflict("RECOVERY_CONTRACT_CONFLICT")
        contract = next(iter(contracts))
        expected = self.authority.expected_endpoints(identity, contract, day,
                                                     previous_watermark, selected[-1][0])
        actual = tuple(item[0] for item in selected)
        if set(actual) - set(expected):
            raise RepositoryConflict("RECOVERY_SESSION_CONFLICT")
        missing = tuple(end for end in expected if end not in actual)
        if not missing or any(end <= missing[-1] for end in actual):
            raise RepositoryConflict("RECOVERY_PREFIX_GAP_REQUIRED")
        if self.authority.expected_endpoints(identity, contract, day,
                missing[-1], actual[0]) != (actual[0],):
            raise RepositoryConflict("RECOVERY_NEXT_ENDPOINT_CONFLICT")
        rows = [[item_id, raw] for _end, item_id, raw in selected]
        proof = dict(day=day.isoformat(), reference_cursor=expected_cursor, tail_id=tail_id,
                     previous_watermark=previous_watermark.isoformat() if previous_watermark else None,
                     product=identity.product, frequency=identity.frequency, contract=contract,
                     missing_endpoints=[end.isoformat() for end in missing],
                     replay_envelopes=rows, replay_sha256=_digest(rows))
        return proof, missing

    def verify_gap(self, identity, previous_watermark, proof):
        fresh, missing = self.freeze(identity, previous_watermark,
            day=date.fromisoformat(proof["day"]), expected_cursor=proof["reference_cursor"],
            tail_id=proof["tail_id"])
        if fresh != proof:
            raise RepositoryConflict("RECOVERY_SOURCE_DRIFT")
        return missing

    @staticmethod
    def replay_envelopes(proof):
        rows = proof["replay_envelopes"]
        if _digest(rows) != proof["replay_sha256"]:
            raise RepositoryConflict("RECOVERY_SOURCE_DRIFT")
        return tuple(ObservationEnvelope.from_json(raw, stream_id=item_id)
                     for item_id, raw in rows)


def replay_expired_originals(worker, routes, proof, *, now):
    """Explicit repair, never natural recording evidence; leaves Redis cursor intact.

    Only expired originals may enter this maintenance replay. The normal dispatcher
    still reads their original raw time and persists EXPIRED_NO_SEND for candidates.
    Every group's four routes finish before the next original is considered.
    """
    for item in JournalRecoveryAuthority.replay_envelopes(proof):
        received = item.raw_received_at or item.source_observed_at
        if now.tzinfo is None or received > now or (now - received).total_seconds() <= 30:
            raise RepositoryConflict("RECOVERY_REPLAY_NOT_EXPIRED")
        worker.source_envelope = item
        worker.source_observed_at = item.confirmed_at
        worker.raw_received_at = received
        try:
            worker.process_live_observation(routes, datetime.fromisoformat(item.data["bar_end"]))
        finally:
            worker.source_envelope = None
            worker.source_observed_at = None
            worker.raw_received_at = None
