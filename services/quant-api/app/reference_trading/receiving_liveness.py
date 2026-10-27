"""Read-only receiving liveness, independent of calculation state and old-tail catch-up.

Snapshots prove a captured Redis ACK frontier against immutable DB originals and
frozen routes. A later ACK may advance during validation, but never regresses or
silently becomes part of the earlier verified prefix. No ACK, retry, state update,
protocol activation, process operation or calculation is performed here.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from sqlalchemy import exists, func, select, tuple_

from app.db.readonly import readonly_transaction
from app.reference_trading.inbox import (
    DAILY_LIMIT,
    UNFINISHED_BYTES_LIMIT,
    _MAX_ENVELOPE_BYTES,
    _digest,
    _envelope,
    _route_identity,
    _validate_active,
    _verified_input,
)
from app.reference_trading.models import (
    ReferenceActivationReceipt,
    ReferenceInboxDelivery,
    ReferenceInboxInput,
    ReferenceRevision,
    ReferenceStream,
)
from app.reference_trading.receiving_handover import (
    KIND as SOURCE_KIND,
    MAX_DAYS,
    _id,
    _progress,
    _protocol,
    _text,
    valid_receiving_handover_intent,
)
from app.reference_trading.repository import _identity_from_row

KIND = "reference_receiving_liveness_v1"
PATH = "services/quant-api/app/reference_trading/receiving_liveness.py"
ERROR = "REFERENCE_RECEIVING_LIVENESS_UNPROVEN"
_BATCH = 128
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class ReceivingLivenessError(ValueError):
    """Unknown input, authority or progress; contains no source/secret details."""


def _require(condition):
    if not condition:
        raise ReceivingLivenessError(ERROR)


def _instant(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    _require(
        isinstance(result, datetime)
        and result.tzinfo is not None
        and result.utcoffset() is not None
    )
    return result.astimezone(UTC)


def _hash(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def target_supports_receiving_liveness(root):
    """Future native cohorts may require this exact tracked implementation kind.

    Recovery of an older v2 owner uses its separately frozen controller/owner
    contracts; it does not claim that the old checkout contains this new module.
    """
    from app.runtime_bindings import _git, _tracked

    try:
        if PATH not in _tracked(Path(root)):
            return False
        source = _git(Path(root), "show", "HEAD:" + PATH)
        _require(len(source) <= 262144)
        values = [
            ast.literal_eval(node.value)
            for node in ast.parse(source).body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "KIND"
                for target in node.targets
            )
        ]
        return values == [KIND]
    except Exception:
        return False


def _authority(protocol, intent, source, target, schema_proof):
    _require(
        isinstance(schema_proof, dict)
        and valid_receiving_handover_intent(intent, target=target)
    )
    _require(intent["authority_sha256"] == _digest(schema_proof))
    _require(
        isinstance(source, dict)
        and set(source)
        == {
            "schema_version",
            "kind",
            "intent_sha256",
            "progress",
            "count",
            "bytes",
            "days",
            "capacity_sha256",
            "content_sha256",
        }
    )
    _require(
        type(source["schema_version"]) is int
        and source["schema_version"] == 1
        and source["kind"] == SOURCE_KIND
        and source["intent_sha256"] == intent["intent_sha256"]
        and _hash(source["capacity_sha256"])
        and source["content_sha256"] == _digest(source["days"])
    )
    _require(set(source["progress"]) == set(intent["baseline"]) == set(source["days"]))
    _require(
        type(source["count"]) is int
        and 0 <= source["count"] <= MAX_DAYS * DAILY_LIMIT
        and type(source["bytes"]) is int
        and 0 <= source["bytes"] <= UNFINISHED_BYTES_LIMIT
    )
    for day, value in source["progress"].items():
        _require(
            date.fromisoformat(day).isoformat() == day
            and set(value) == {"cursor", "tail"}
        )
        baseline = intent["baseline"][day]
        _require(
            _id(baseline["cursor"]) <= _id(value["cursor"]) <= _id(value["tail"])
            and _id(baseline["tail"]) <= _id(value["tail"])
        )
        metric = source["days"][day]
        _require(
            set(metric) == {"count", "bytes", "sha256"}
            and type(metric["count"]) is int
            and 0 <= metric["count"] <= DAILY_LIMIT
            and type(metric["bytes"]) is int
            and 0 <= metric["bytes"] <= UNFINISHED_BYTES_LIMIT
            and _hash(metric["sha256"])
        )
    _require(
        sum(row["count"] for row in source["days"].values()) == source["count"]
        and sum(row["bytes"] for row in source["days"].values()) == source["bytes"]
    )
    active = _protocol(protocol)
    _require(
        active is not None
        and active["status"] == "active"
        and active["binding"] == intent["binding"]
    )
    if intent["status"] == "requested":
        _require(
            active["boundaries"] == source["progress"] and "activated_at" in active
        )
        _instant(active["activated_at"])
        original = {
            key: value
            for key, value in active.items()
            if key not in {"activated_at", "boundaries"}
        }
        original["status"] = "requested"
        _require(_digest(original) == intent["protocol_sha256"])
    else:
        # An already-active protocol retains its original activation boundary.
        # Its exact frozen preimage, not an overwritten boundary, binds this attempt.
        _require(_digest(active) == intent["protocol_sha256"])
    return active


def _prefix(session, events, day, check_budget, hashes):
    input_hash, route_hash = hashes
    count, size = 0, 0
    for start in range(0, len(events), _BATCH):
        check_budget()
        batch = events[start : start + _BATCH]
        by_id = {event.stream_id: event for event in batch}
        items = session.scalars(
            select(ReferenceInboxInput).where(
                ReferenceInboxInput.trading_day == day,
                ReferenceInboxInput.journal_id.in_(by_id),
            )
        ).all()
        _require(len(items) == len(batch))
        by_input = {item.input_id: item for item in items}
        routes = session.scalars(
            select(ReferenceInboxDelivery)
            .where(ReferenceInboxDelivery.input_id.in_(by_input))
            .order_by(ReferenceInboxDelivery.input_id, ReferenceInboxDelivery.stream_id)
            .limit(_BATCH * 512 + 1)
        ).all()
        _require(len(routes) <= _BATCH * 512)
        streams = session.scalars(
            select(ReferenceStream).where(
                ReferenceStream.stream_id.in_([row.stream_id for row in routes])
            )
        ).all()
        revisions = session.scalars(
            select(ReferenceRevision).where(
                tuple_(ReferenceRevision.stream_id, ReferenceRevision.revision_id).in_(
                    [(row.stream_id, row.revision_id) for row in routes]
                )
            )
        ).all()
        receipts = session.scalars(
            select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.receipt_id.in_(
                    [row.activation_receipt_id for row in routes]
                )
            )
        ).all()
        frozen = {key: [] for key in by_input}
        for row in routes:
            _require(
                row.delivery_id
                == _digest(
                    [day.isoformat(), by_input[row.input_id].journal_id, row.stream_id]
                )
            )
            _validate_active(session, row, lock=False)
            stream = session.get(ReferenceStream, row.stream_id)
            identity = _identity_from_row(stream)
            item = by_input[row.input_id]
            _require(
                identity.stream_id == row.stream_id
                and stream.identity_hash
                == row.stream_id.removeprefix("reference-stream:")
                and identity.product.lower() == item.product
                and identity.frequency == item.frequency
            )
            frozen[row.input_id].append(row)
        item_by_journal = {item.journal_id: item for item in items}
        for event in batch:
            check_budget()
            item = item_by_journal[event.stream_id]
            original = _verified_input(item)
            _require(
                item.input_id == _digest([day.isoformat(), event.stream_id])
                and original.to_json() == event.to_json()
                and original.stream_id == event.stream_id
                and len(frozen[item.input_id]) == item.target_count
                and _digest([_route_identity(row) for row in frozen[item.input_id]])
                == item.routing_sha256
                and (original.notification_eligible or item.target_count == 0)
            )
            input_hash.update(
                json.dumps(
                    [
                        item.journal_id,
                        item.input_id,
                        item.envelope_sha256,
                        item.payload_bytes,
                    ],
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            route_hash.update(
                json.dumps(
                    [item.journal_id, item.routing_sha256, item.target_count],
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            count += 1
            size += item.payload_bytes
        # Keep the same batch-loaded readonly identity map alive for validation.
        _ = streams, revisions, receipts
    return count, size, input_hash.hexdigest(), route_hash.hexdigest()


def _source_day(journal, day, old, ack, expected, check_budget, accept_prefix):
    frontier, count, size = old["cursor"], 0, 0
    digest, seen, accepted = sha256(), {}, []
    # Preserve the complete frozen old interval, then verify every newly ACKed
    # original beyond it. UnACKed new appends need not be accepted to prove that
    # the fixed old suffix is intact. Raw payload memory stays one bounded chunk.
    for upper, frozen_source in ((old["tail"], True), (ack, False)):
        while _id(frontier) < _id(upper):
            check_budget()
            rows = journal.read(
                "reference", day, count=128, after=frontier, through=upper
            )
            _require(bool(rows))
            for event in rows:
                _require(
                    _id(frontier) < _id(event.stream_id) <= _id(upper)
                    and event.trading_day == day
                    and event.observation_id not in seen
                )
                _, _, _, canonical, fingerprint, payload_bytes, _ = _envelope(event)
                seen[event.observation_id] = (
                    event.stream_id,
                    sha256(canonical.encode()).hexdigest(),
                )
                _require(len(seen) <= DAILY_LIMIT)
                if frozen_source:
                    digest.update(
                        json.dumps(
                            [
                                event.stream_id,
                                event.observation_id,
                                fingerprint,
                                payload_bytes,
                            ],
                            separators=(",", ":"),
                        ).encode()
                        + b"\n"
                    )
                    count += 1
                    size += payload_bytes
                    _require(count <= DAILY_LIMIT and size <= UNFINISHED_BYTES_LIMIT)
                if _id(event.stream_id) <= _id(ack):
                    accepted.append(event)
                    if len(accepted) == _BATCH:
                        accept_prefix(accepted)
                        accepted.clear()
                frontier = event.stream_id
            check_budget()
    metric = {"count": count, "bytes": size, "sha256": digest.hexdigest()}
    identity_upper = ack if _id(ack) > _id(old["tail"]) else old["tail"]
    _require(frontier == identity_upper and metric == expected)
    _require(journal.redis.hlen(journal.identity_key(day)) <= DAILY_LIMIT)
    verified = set()
    for raw_key, raw_value in journal.redis.hscan_iter(
        journal.identity_key(day), count=512
    ):
        check_budget()
        key, identity = _text(raw_key), json.loads(_text(raw_value))
        identifier = identity["id"]
        if _id(old["cursor"]) < _id(identifier) <= _id(identity_upper):
            _require(key in seen and seen[key][0] == identifier)
            content = identity.get("content", identity.get("payload"))
            _require(
                isinstance(content, str)
                and sha256(content.encode()).hexdigest() == seen[key][1]
            )
            if "payload" in identity:
                _require(
                    isinstance(identity["payload"], str)
                    and sha256(identity["payload"].encode()).hexdigest() == seen[key][1]
                )
            verified.add(key)
    _require(verified == set(seen))
    if accepted:
        accept_prefix(accepted)
    return metric


def snapshot_receiving(
    session_factory,
    protocol,
    journal,
    *,
    intent,
    source_proof,
    target,
    schema_proof,
    check_budget=lambda: None,
    sampled_at=None,
    owner_cycle_at=None,
):
    """Independently verify one captured ACK prefix and the complete frozen suffix.

    ``owner_cycle_at`` comes from a separately verified fresh receiving_cycle
    owner state. None is allowed only for a parked/pre-execution source snapshot.
    Caller checks OS lock, owner PID/generation/binding and the CLOSED session.
    """
    try:
        check_budget()
        sampled = _instant(sampled_at or datetime.now(UTC))
        cycle = _instant(owner_cycle_at) if owner_cycle_at is not None else None
        _require(cycle is None or 0 <= (sampled - cycle).total_seconds() <= 30)
        active = _authority(protocol, intent, source_proof, target, schema_proof)
        registered, current = _progress(journal)
        _require(
            registered == intent["registered_day"]
            and set(current) == set(source_proof["progress"])
        )
        for day, old in source_proof["progress"].items():
            _require(
                _id(old["cursor"])
                <= _id(current[day]["cursor"])
                <= _id(current[day]["tail"])
                and _id(current[day]["tail"]) >= _id(old["tail"])
            )
        days = {}
        with (
            session_factory() as session,
            readonly_transaction(session, timeout_seconds=20),
        ):
            for text_day, old in sorted(source_proof["progress"].items()):
                day, ack = date.fromisoformat(text_day), current[text_day]["cursor"]
                hashes, totals = (sha256(), sha256()), [0, 0]

                def accept_prefix(events):
                    count, size, _, _ = _prefix(
                        session, events, day, check_budget, hashes
                    )
                    totals[0] += count
                    totals[1] += size

                metric = _source_day(
                    journal,
                    day,
                    old,
                    ack,
                    source_proof["days"][text_day],
                    check_budget,
                    accept_prefix,
                )
                count, size = totals
                persisted_count = session.scalar(
                    select(func.count())
                    .select_from(ReferenceInboxInput)
                    .where(
                        ReferenceInboxInput.trading_day == day,
                        tuple_(
                            ReferenceInboxInput.journal_ms,
                            ReferenceInboxInput.journal_sequence,
                        )
                        > _id(old["cursor"]),
                        tuple_(
                            ReferenceInboxInput.journal_ms,
                            ReferenceInboxInput.journal_sequence,
                        )
                        <= _id(ack),
                    )
                )
                _require(persisted_count == count)
                input_hash, route_hash = (digest.hexdigest() for digest in hashes)
                days[text_day] = {
                    "old_cursor": old["cursor"],
                    "old_tail": old["tail"],
                    "ack": ack,
                    "source_count": metric["count"],
                    "source_bytes": metric["bytes"],
                    "source_sha256": metric["sha256"],
                    "acknowledged_count": count,
                    "acknowledged_bytes": size,
                    "ack_inputs_sha256": input_hash,
                    "ack_routes_sha256": route_hash,
                }
            unfinished = exists(
                select(1).where(
                    ReferenceInboxDelivery.input_id == ReferenceInboxInput.input_id,
                    ReferenceInboxDelivery.status != "COMPLETED",
                )
            )
            used = int(
                session.scalar(
                    select(
                        func.coalesce(func.sum(ReferenceInboxInput.payload_bytes), 0)
                    ).where(unfinished)
                )
            )
            day_inputs = {
                day.isoformat(): count
                for day, count in session.execute(
                    select(ReferenceInboxInput.trading_day, func.count())
                    .where(
                        ReferenceInboxInput.trading_day.in_(
                            [date.fromisoformat(day) for day in days]
                        )
                    )
                    .group_by(ReferenceInboxInput.trading_day)
                )
            }
            _require(
                0 <= used <= UNFINISHED_BYTES_LIMIT
                and all(
                    type(count) is int and 0 <= count <= DAILY_LIMIT
                    for count in day_inputs.values()
                )
            )
        check_budget()
        final_registered, final = _progress(journal)
        _require(
            final_registered == registered
            and set(final) == set(current)
            and protocol.read() == active
        )
        for day, old in source_proof["progress"].items():
            _require(
                _id(current[day]["cursor"])
                <= _id(final[day]["cursor"])
                <= _id(final[day]["tail"])
                and _id(final[day]["tail"])
                >= _id(current[day]["tail"])
                >= _id(old["tail"])
            )
        for day, row in days.items():
            row["current_tail"] = current[day]["tail"]
            row["final_tail"] = final[day]["tail"]
        acknowledged = sum(row["acknowledged_count"] for row in days.values())
        result = {
            "schema_version": 2,
            "kind": KIND,
            "sampled_at": sampled.isoformat(),
            "owner_cycle_at": cycle.isoformat() if cycle else None,
            "intent_sha256": intent["intent_sha256"],
            "source_proof_sha256": _digest(source_proof),
            "target_sha256": _digest(target),
            "binding": protocol.binding,
            "protocol_sha256": _digest(active),
            "boundaries_sha256": _digest(active["boundaries"]),
            "registered_day": registered,
            "days": days,
            "capacity": {"unfinished_bytes": used, "day_inputs": day_inputs},
            "source_count": source_proof["count"],
            "source_bytes": source_proof["bytes"],
            "acknowledged_count": acknowledged,
            "acknowledged_bytes": sum(
                row["acknowledged_bytes"] for row in days.values()
            ),
            "remaining_count": sum(
                max(row["source_count"] - row["acknowledged_count"], 0)
                for row in days.values()
            ),
            "old_tail_reached": all(
                _id(row["ack"]) >= _id(row["old_tail"]) for row in days.values()
            ),
        }
        result["snapshot_sha256"] = _digest(result)
        check_budget()
        return result
    except Exception:
        raise ReceivingLivenessError(ERROR) from None


def _valid_snapshot(value):
    fields = {
        "schema_version",
        "kind",
        "sampled_at",
        "owner_cycle_at",
        "intent_sha256",
        "source_proof_sha256",
        "target_sha256",
        "binding",
        "protocol_sha256",
        "boundaries_sha256",
        "registered_day",
        "days",
        "capacity",
        "source_count",
        "source_bytes",
        "acknowledged_count",
        "acknowledged_bytes",
        "remaining_count",
        "old_tail_reached",
        "snapshot_sha256",
    }
    _require(
        isinstance(value, dict)
        and set(value) == fields
        and value.get("kind") == KIND
        and type(value.get("schema_version")) is int
        and value["schema_version"] == 2
        and _hash(value.get("snapshot_sha256"))
        and value["snapshot_sha256"]
        == _digest(
            {key: item for key, item in value.items() if key != "snapshot_sha256"}
        )
    )
    _require(
        0 < len(value["days"]) <= MAX_DAYS and value["registered_day"] in value["days"]
    )
    for key in (
        "intent_sha256",
        "source_proof_sha256",
        "target_sha256",
        "binding",
        "protocol_sha256",
        "boundaries_sha256",
    ):
        _require(_hash(value[key]))
    _instant(value["sampled_at"])
    if value["owner_cycle_at"] is not None:
        _instant(value["owner_cycle_at"])
    _require(
        all(
            type(value[key]) is int and value[key] >= 0
            for key in (
                "source_count",
                "source_bytes",
                "acknowledged_count",
                "acknowledged_bytes",
                "remaining_count",
            )
        )
    )
    capacity = value["capacity"]
    _require(
        isinstance(capacity, dict)
        and set(capacity) == {"unfinished_bytes", "day_inputs"}
        and type(capacity["unfinished_bytes"]) is int
        and 0 <= capacity["unfinished_bytes"] <= UNFINISHED_BYTES_LIMIT
        and isinstance(capacity["day_inputs"], dict)
        and set(capacity["day_inputs"]).issubset(value["days"])
        and all(
            type(count) is int and 0 <= count <= DAILY_LIMIT
            for count in capacity["day_inputs"].values()
        )
    )
    for day, row in value["days"].items():
        _require(
            date.fromisoformat(day).isoformat() == day
            and set(row)
            == {
                "old_cursor",
                "old_tail",
                "current_tail",
                "final_tail",
                "ack",
                "source_count",
                "source_bytes",
                "source_sha256",
                "acknowledged_count",
                "acknowledged_bytes",
                "ack_inputs_sha256",
                "ack_routes_sha256",
            }
            and type(row["source_count"]) is int
            and type(row["source_bytes"]) is int
        )
        _require(
            _id(row["old_cursor"]) <= _id(row["old_tail"])
            and _id(row["old_cursor"]) <= _id(row["ack"]) <= _id(row["current_tail"])
            and _id(row["old_tail"])
            <= _id(row["current_tail"])
            <= _id(row["final_tail"])
        )
        _require(
            type(row["acknowledged_count"]) is int
            and 0 <= row["acknowledged_count"] <= DAILY_LIMIT
            and 0 <= row["source_count"] <= DAILY_LIMIT
        )
        _require(
            type(row["acknowledged_bytes"]) is int
            and 0 <= row["acknowledged_bytes"] <= DAILY_LIMIT * _MAX_ENVELOPE_BYTES
            and 0 <= row["source_bytes"] <= UNFINISHED_BYTES_LIMIT
        )
        _require(
            all(
                _hash(row[key])
                for key in ("source_sha256", "ack_inputs_sha256", "ack_routes_sha256")
            )
        )
    _require(
        value["acknowledged_count"]
        == sum(row["acknowledged_count"] for row in value["days"].values())
        and value["acknowledged_bytes"]
        == sum(row["acknowledged_bytes"] for row in value["days"].values())
        and value["source_count"]
        == sum(row["source_count"] for row in value["days"].values())
        and value["source_bytes"]
        == sum(row["source_bytes"] for row in value["days"].values())
        and value["remaining_count"]
        == sum(
            max(row["source_count"] - row["acknowledged_count"], 0)
            for row in value["days"].values()
        )
        and type(value["old_tail_reached"]) is bool
        and value["old_tail_reached"]
        == all(
            _id(row["ack"]) >= _id(row["old_tail"]) for row in value["days"].values()
        )
    )


def receiving_snapshot_identity(value):
    """Stable parked preimage identity; only sample/cycle times are excluded."""
    try:
        _valid_snapshot(value)
        return _digest(
            {
                key: item
                for key, item in value.items()
                if key not in {"sampled_at", "owner_cycle_at", "snapshot_sha256"}
            }
        )
    except Exception:
        raise ReceivingLivenessError(ERROR) from None


def receiving_sample_is_fresh(value, *, now):
    """Expiry is not corruption; invalid clocks and sample integrity still fail."""
    try:
        _valid_snapshot(value)
        sampled, cycle, instant = (
            _instant(value["sampled_at"]),
            _instant(value["owner_cycle_at"]),
            _instant(now),
        )
        _require(0 <= (sampled - cycle).total_seconds() <= 30 and instant >= sampled)
        return (instant - cycle).total_seconds() <= 30
    except Exception:
        raise ReceivingLivenessError(ERROR) from None


def verify_receiving_continuity(before, after):
    """Preserve the full verified prefix across expiry; this grants no liveness."""
    try:
        for value in (before, after):
            _valid_snapshot(value)
            _require(
                0
                <= (
                    _instant(value["sampled_at"]) - _instant(value["owner_cycle_at"])
                ).total_seconds()
                <= 30
            )
        _require(
            _instant(after["sampled_at"]) > _instant(before["sampled_at"])
            and _instant(after["owner_cycle_at"]) >= _instant(before["owner_cycle_at"])
        )
        for key in (
            "intent_sha256",
            "source_proof_sha256",
            "target_sha256",
            "binding",
            "protocol_sha256",
            "boundaries_sha256",
            "registered_day",
            "source_count",
            "source_bytes",
        ):
            _require(before[key] == after[key])
        _require(set(before["days"]) == set(after["days"]))
        for day, row in before["days"].items():
            current = after["days"][day]
            _require(
                all(
                    row[key] == current[key]
                    for key in (
                        "old_cursor",
                        "old_tail",
                        "source_count",
                        "source_bytes",
                        "source_sha256",
                    )
                )
            )
            _require(
                _id(current["ack"]) >= _id(row["ack"])
                and _id(current["current_tail"]) >= _id(row["final_tail"])
                and current["acknowledged_count"] >= row["acknowledged_count"]
                and current["acknowledged_bytes"] >= row["acknowledged_bytes"]
            )
            if current["ack"] == row["ack"]:
                _require(
                    all(
                        current[key] == row[key]
                        for key in (
                            "acknowledged_count",
                            "acknowledged_bytes",
                            "ack_inputs_sha256",
                            "ack_routes_sha256",
                        )
                    )
                )
            else:
                _require(
                    current["acknowledged_count"] > row["acknowledged_count"]
                    and current["acknowledged_bytes"] > row["acknowledged_bytes"]
                    and current["ack_inputs_sha256"] != row["ack_inputs_sha256"]
                    and current["ack_routes_sha256"] != row["ack_routes_sha256"]
                )
        advanced = after["acknowledged_count"] - before["acknowledged_count"]
        return {
            "advanced_count": advanced,
            "caught_up_idle": all(
                row["ack"] == row["current_tail"] == row["final_tail"]
                for value in (before, after)
                for row in value["days"].values()
            ),
        }
    except Exception:
        raise ReceivingLivenessError(ERROR) from None


def verify_receiving_nonregression(before, after, *, now=None):
    """Two fresh receiving-cycle samples prove progress, never calculation health."""
    instant = now or datetime.now(UTC)
    if not all(
        receiving_sample_is_fresh(value, now=instant) for value in (before, after)
    ):
        raise ReceivingLivenessError(ERROR)
    comparison = verify_receiving_continuity(before, after)
    if _instant(after["owner_cycle_at"]) <= _instant(before["owner_cycle_at"]):
        raise ReceivingLivenessError(ERROR)
    return comparison


def receiving_context_identity(value):
    """Static contract/source identity for comparing independently verified frontiers."""
    try:
        _valid_snapshot(value)
        keys = (
            "intent_sha256",
            "source_proof_sha256",
            "target_sha256",
            "binding",
            "protocol_sha256",
            "boundaries_sha256",
            "registered_day",
            "source_count",
            "source_bytes",
        )
        return _digest(
            {
                **{key: value[key] for key in keys},
                "days": {
                    day: {
                        key: row[key]
                        for key in (
                            "old_cursor",
                            "old_tail",
                            "source_count",
                            "source_bytes",
                            "source_sha256",
                        )
                    }
                    for day, row in value["days"].items()
                },
            }
        )
    except Exception:
        raise ReceivingLivenessError(ERROR) from None


def prove_receiving_liveness(before, after, *, closed_idle=False, now=None):
    """Prove progress or an independently verified empty current queue.

    The legacy closed_idle argument no longer supplies authority to accept an
    idle receiver. Two fresh cycles and both captured current frontiers do.
    """
    try:
        _require(type(closed_idle) is bool)
        comparison = verify_receiving_nonregression(before, after, now=now)
        advanced = comparison["advanced_count"]
        _require(advanced > 0 or comparison["caught_up_idle"])
        mode = (
            "durable_receiving_caught_up_idle"
            if advanced == 0
            else "durable_receiving"
            if after["old_tail_reached"]
            else "durable_receiving_backlog_liveness"
        )
        return {
            "schema_version": 2,
            "kind": KIND,
            "mode": mode,
            "calculation_ready": False,
            "before_sha256": before["snapshot_sha256"],
            "after_sha256": after["snapshot_sha256"],
            "advanced_count": advanced,
            "remaining_count": after["remaining_count"],
            "old_tail_reached": after["old_tail_reached"],
        }
    except Exception:
        raise ReceivingLivenessError(ERROR) from None
