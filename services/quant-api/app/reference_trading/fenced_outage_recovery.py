"""Task-local 2026-10-13 stopped-publisher interruption authority.

This is not an automatic failover policy. It proves absent past endpoints from
real retained journals while the exact repair controller keeps Feed absent.
No empty/synthetic journal or future endpoint can grant an interruption.
"""

from datetime import UTC, date, datetime
import json

from app.market_data.observation_stream import DAILY_LIMIT, ObservationEnvelope
from app.reference_trading.journal_recovery import _digest
from app.reference_trading.repository import RepositoryConflict


class FencedOutageAuthority:
    def __init__(self, journal, authority, *, verify_fence, contract_for_day, cutoff):
        if (
            journal.kind != "completed"
            or cutoff.tzinfo is None
            or cutoff > datetime.now(UTC)
        ):
            raise ValueError("OUTAGE_AUTHORITY_INVALID")
        self.journal, self.authority = journal, authority
        self.verify_fence, self.contract_for_day, self.cutoff = (
            verify_fence,
            contract_for_day,
            cutoff,
        )

    def freeze(
        self, identity, previous_watermark, *, day, expected_cursor, tail_id=None
    ):
        if day != date(2026, 10, 13) or identity.frequency != "60m":
            raise RepositoryConflict("OUTAGE_SCOPE_INVALID")
        fence = self.verify_fence()
        if self.current_cursor(day) != expected_cursor:
            raise RepositoryConflict("RECOVERY_CURSOR_DRIFT")
        tail = self.journal.tail(day)
        if tail_id is not None and tail_id != tail:
            raise RepositoryConflict("OUTAGE_JOURNAL_DRIFT")
        rows = self.journal.redis.xrange(
            self.journal.key(day), min="-", max="+", count=DAILY_LIMIT + 1
        )
        if len(rows) > DAILY_LIMIT:
            raise RepositoryConflict("RECOVERY_JOURNAL_BUDGET_EXCEEDED")
        originals = []
        for raw_id, fields in rows:
            item_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            raw = fields.get(b"envelope", fields.get("envelope"))
            if raw is None:
                raise RepositoryConflict("RECOVERY_JOURNAL_INVALID")
            raw = raw.decode() if isinstance(raw, bytes) else raw
            item = ObservationEnvelope.from_json(raw, stream_id=item_id)
            end = datetime.fromisoformat(item.data["bar_end"])
            if (
                item.trading_day != day
                or not item.notification_eligible
                or item.confirmed_at is None
                or item.confirmed_at < end
            ):
                raise RepositoryConflict("RECOVERY_JOURNAL_INVALID")
            originals.append([item_id, raw])
            if item.channel == f"live:bar:{identity.product}:60m":
                # Saved originals must go through durable replay first. Never
                # call their endpoints missing even if already acknowledged.
                if previous_watermark is None or end > previous_watermark:
                    raise RepositoryConflict("OUTAGE_SAVED_ORIGINAL_FIRST")
        contract = self.contract_for_day(identity.product, day)
        endpoints = self.authority.expected_endpoints(
            identity, contract, day, previous_watermark, self.cutoff
        )
        if any(end.tzinfo is None or end > self.cutoff for end in endpoints):
            raise RepositoryConflict("OUTAGE_FUTURE_ENDPOINT_FORBIDDEN")
        for end in endpoints:
            self.authority.owner_segments(identity, contract, day, end)
        proof = {
            "kind": "SERVICE_OUTAGE",
            "day": day.isoformat(),
            "product": identity.product,
            "frequency": identity.frequency,
            "contract": contract,
            "cutoff": self.cutoff.isoformat(),
            "reference_cursor": expected_cursor,
            "tail_id": tail,
            "previous_watermark": previous_watermark.isoformat()
            if previous_watermark
            else None,
            "missing_endpoints": [end.isoformat() for end in endpoints],
            "journal_count": len(originals),
            "journal_sha256": _digest(originals),
            "fence": fence,
            "replay_envelopes": [],
            "replay_sha256": _digest([]),
        }
        return json.loads(json.dumps(proof)), tuple(endpoints)

    def current_cursor(self, day):
        raw = self.journal.redis.get(self.journal.cursor_key("reference", day))
        if raw is None:
            if (
                self.journal.redis.exists(self.journal.key(day))
                or self.journal.redis.exists(self.journal.identity_key(day))
                or self.journal.registered_day("reference") >= day
            ):
                raise RepositoryConflict("OUTAGE_CURSOR_ABSENCE_UNPROVEN")
            return None
        return raw.decode() if isinstance(raw, bytes) else raw

    def verify_gap(self, identity, previous_watermark, proof):
        if datetime.fromisoformat(proof["cutoff"]) != self.cutoff:
            raise RepositoryConflict("OUTAGE_CUTOFF_DRIFT")
        fresh, missing = self.freeze(
            identity,
            previous_watermark,
            day=date.fromisoformat(proof["day"]),
            expected_cursor=proof["reference_cursor"],
            tail_id=proof["tail_id"],
        )
        if fresh != proof:
            raise RepositoryConflict("RECOVERY_SOURCE_DRIFT")
        return missing

    @staticmethod
    def replay_envelopes(proof):
        if proof["replay_envelopes"] or proof["replay_sha256"] != _digest([]):
            raise RepositoryConflict("OUTAGE_SAVED_ORIGINAL_FIRST")
        return ()
