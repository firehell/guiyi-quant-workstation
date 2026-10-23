"""Versioned numeric source revisions; first-seen and Canonical remain separate facts.

Only the MDS reconciliation reader may construct this proof after its physical
owner, Session, endpoint and quality checks. No prices, old comparisons, captures
or checkpoints are overwritten by this module.
"""
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import re

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.repository import RepositoryConflict

POLICY = "rqdata_live_history_revision_v1"
KEY = "source_revision_v1"
PREFIX = "source-revision:"
FIELDS = frozenset(("bar_end", "trading_day", "open", "high", "low", "close",
                    "volume", "turnover", "open_interest"))


def _require(value):
    if not value:
        raise RepositoryConflict("SOURCE_REVISION_PROOF_INVALID")


def _sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _bar(raw):
    _require(isinstance(raw, dict) and set(raw) == FIELDS)
    try:
        end = datetime.fromisoformat(raw["bar_end"])
        day = date.fromisoformat(raw["trading_day"])
        _require(end.tzinfo is not None and end.utcoffset() is not None
                 and day.isoformat() == raw["trading_day"])
        numbers = {key: None if raw[key] is None else Decimal(raw[key])
                   for key in FIELDS - {"bar_end", "trading_day"}}
        _require(all(value is None or value.is_finite() for value in numbers.values()))
        _require(all(numbers[key] is not None and numbers[key] > 0
                     for key in ("open", "high", "low", "close")))
        _require(numbers["low"] <= min(numbers["open"], numbers["close"])
                 <= max(numbers["open"], numbers["close"]) <= numbers["high"])
        _require(numbers["volume"] is not None)
        _require(all(value is None or value >= 0 for value in numbers.values()))
        _require(all(numbers[key] is None or numbers[key] == numbers[key].to_integral_value()
                     for key in ("volume", "open_interest")))
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise RepositoryConflict("SOURCE_REVISION_PROOF_INVALID") from error
    return end, numbers


def build_revision_proof(evidence, canonical_bar, canonical_source, *, provider):
    """Classify only valid, same-identity numeric differences, never unknowns."""
    try:
        _require(provider == "rqdata" and isinstance(evidence, dict))
        _require(evidence["source_kind"] == "completed_live"
                 and evidence["eligibility"] == "completed_observation")
        payload, source = evidence["input_payload"], evidence["source_proof"]
        raw = payload["bar"]
        end, left = _bar(raw)
        canonical_end, right = _bar(canonical_bar)
        observed = datetime.fromisoformat(evidence["observed_at"])
        _require(observed.tzinfo is not None and observed.utcoffset() is not None
                 and end <= observed and end == canonical_end
                 and raw["bar_end"] == evidence["bar_end"] == canonical_bar["bar_end"]
                 and raw["trading_day"] == canonical_bar["trading_day"])
        product, contract = payload["product"], payload["contract"]
        _require(isinstance(product, str) and re.fullmatch("[a-z]{1,2}", product)
                 and isinstance(contract, str)
                 and re.fullmatch(re.escape(product.upper()) + "[0-9]{4}", contract))
        _require(source["frequency"] == "60m" and source["owner_segment_id"]
                 and source["calculation_segment_id"]
                 and canonical_source["contract"] == contract
                 and canonical_source["frequency"] == source["frequency"])
        _require(manifest_sha256(raw) == source["source_sha256"] == payload["source_bar_sha256"])
        _require(canonical_source["partitions"] and all(
            _sha(part["content_sha256"]) and "quality_sha256" in part
            and (part["quality_sha256"] is None or _sha(part["quality_sha256"]))
            for part in canonical_source["partitions"]))
        _require(all((left[key] is None) == (right[key] is None) for key in left))
        differences = {key: {"observed": raw[key], "canonical": canonical_bar[key]}
                       for key in sorted(left) if left[key] != right[key]}
        if not differences:
            return None
        comparable = {key: (raw[key] if key in left and left[key] == right[key]
                            else canonical_bar[key]) for key in raw}
        return {"policy_version": POLICY, "provider": provider,
                "verification": "MDS_PHYSICAL_OWNER_ENDPOINT_QUALITY",
                "capture": evidence, "observed_bar": raw, "canonical_bar": canonical_bar,
                "canonical_source": canonical_source,
                "source_revision": "canonical:" + manifest_sha256(canonical_source),
                "captured_sha256": manifest_sha256(raw),
                "canonical_sha256": manifest_sha256(comparable), "differences": differences}
    except (KeyError, TypeError, ValueError) as error:
        raise RepositoryConflict("SOURCE_REVISION_PROOF_INVALID") from error


def validate_revision_proof(proof):
    """Recompute hashes and field differences before projecting persisted evidence."""
    try:
        _require(isinstance(proof, dict) and proof.get("policy_version") == POLICY)
        rebuilt = build_revision_proof(proof["capture"], proof["canonical_bar"],
                                       proof["canonical_source"], provider=proof["provider"])
        _require(rebuilt is not None and rebuilt == proof)
    except (KeyError, TypeError, ValueError) as error:
        raise RepositoryConflict("SOURCE_REVISION_PROOF_INVALID") from error
    return proof


def _capture_binding(capture):
    from app.reference_trading.capture import ForwardCapture

    try:
        wire = capture.source_evidence["forward_capture_v1"]
        rebuilt = ForwardCapture(capture.stream_id, capture.revision_id, wire["generation"],
                                 wire["source_key"], datetime.fromisoformat(wire["bar_end"]),
                                 datetime.fromisoformat(wire["observed_at"]), wire["source_kind"],
                                 wire["input_payload"], wire["source_proof"], wire["eligibility"])
        _require(capture.kind == "capture" and rebuilt.capture_hash == capture.payload_hash
                 == wire["hash"] and rebuilt.evidence() == capture.source_evidence)
    except (KeyError, TypeError, ValueError) as error:
        raise RepositoryConflict("SOURCE_REVISION_CAPTURE_INVALID") from error
    return wire


def activation_window_valid(capture, stream, receipts):
    """Validate the original generation against the native successor chain."""
    def aware(value):
        return value.replace(tzinfo=value.tzinfo or UTC)

    generation = capture.source_evidence["forward_capture_v1"]["generation"]
    chain = {row.generation: row for row in receipts if row.stream_id == capture.stream_id}
    if (type(generation) is not int or stream is None or capture.processed_at is None
            or not 0 < generation <= stream.activation_generation):
        return False
    for number in range(generation, stream.activation_generation + 1):
        row = chain.get(number)
        if row is None or row.revision_id != capture.revision_id:
            return False
        if number > generation and aware(chain[number - 1].activated_at) > aware(row.activated_at):
            return False
    receipt = chain[generation]
    ends = [aware(receipt.disabled_at)] if receipt.disabled_at is not None else []
    if generation < stream.activation_generation:
        ends.append(aware(chain[generation + 1].activated_at))
    return (aware(receipt.activated_at) <= aware(capture.processed_at)
            and (not ends or aware(capture.processed_at) < min(ends)))


def _activation_binding(capture, stream, receipt, receipts):
    wire = capture.source_evidence["forward_capture_v1"]
    _require(stream is not None and receipt is not None
             and stream.recording_mode == "forward_observation" and stream.frequency == "60m"
             and stream.strategy_code in {"newow_trend", "newow_oscillation", "newow_main_rise"}
             and stream.product.lower() == wire["input_payload"]["product"]
             and stream.frequency == wire["source_proof"]["frequency"]
             and receipt.stream_id == capture.stream_id and receipt.revision_id == capture.revision_id
             and receipt.generation == wire["generation"] <= stream.activation_generation
             and capture.processed_at is not None)

    def aware(value):
        return value.replace(tzinfo=value.tzinfo or UTC)

    _require(activation_window_valid(capture, stream, receipts))
    return {"receipt_id": receipt.receipt_id, "stream_id": receipt.stream_id,
            "revision_id": receipt.revision_id, "generation": receipt.generation,
            "plan_hash": receipt.plan_hash, "activated_at": aware(receipt.activated_at).isoformat(),
            "recording_start": aware(receipt.recording_start).isoformat()}


def _fact(capture, comparison, proof, activation):
    validate_revision_proof(proof)
    wire = _capture_binding(capture)
    _require(comparison.status == "mismatch" and comparison.capture_batch_id == capture.batch_id
             and proof["capture"] == wire
             and proof["source_revision"] == comparison.source_revision
             and proof["captured_sha256"] == comparison.captured_sha256
             and proof["canonical_sha256"] == comparison.canonical_sha256)
    return {"policy_version": POLICY, "capture_id": capture.batch_id,
            "capture_revision_id": capture.revision_id,
            "capture_generation": wire["generation"], "capture_payload_hash": capture.payload_hash,
            "activation": activation, "reconciliation_id": comparison.reconciliation_id, "proof": proof}


def append_source_revision(session, capture, comparison, proof, *, now):
    """Append in the comparison's transaction; idempotency never edits old facts."""
    from sqlalchemy import select
    from uuid import uuid4
    from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceStream

    receipts = session.scalars(select(ReferenceActivationReceipt).where(
        ReferenceActivationReceipt.stream_id == capture.stream_id)).all()
    receipt = next((row for row in receipts if row.generation ==
                    capture.source_evidence["forward_capture_v1"]["generation"]), None)
    activation = _activation_binding(capture, session.get(ReferenceStream, capture.stream_id), receipt, receipts)
    fact = _fact(capture, comparison, proof, activation)
    key = PREFIX + manifest_sha256([comparison.reconciliation_id, POLICY])
    existing = session.scalar(select(ReferenceBatch).where(
        ReferenceBatch.stream_id == capture.stream_id, ReferenceBatch.batch_key == key))
    if existing is not None:
        _require(existing.kind == "diagnostic" and existing.revision_id == capture.revision_id
                 and existing.source_evidence == {KEY: fact}
                 and existing.payload_hash == manifest_sha256(fact))
        return existing
    row = ReferenceBatch(batch_id=uuid4().hex, stream_id=capture.stream_id,
                         revision_id=capture.revision_id, batch_key=key,
                         payload_hash=manifest_sha256(fact), kind="diagnostic", outcome="diagnostic",
                         seq=None, expected_seq=capture.expected_seq, dependency_manifest={},
                         source_evidence={KEY: fact}, projected_action_pks=[],
                         diagnostics=["RQDATA_SOURCE_REVISED"], observed_at=capture.observed_at,
                         processed_at=now)
    session.add(row)
    session.flush()
    return row


def resolved_mismatches(session, comparisons):
    """One exact resolver shared by guards, quarantine, fusion and health.

    ``comparisons`` contains (comparison, capture) pairs. A stream-wide label or
    an unrelated diagnostic never waives a comparison. Corruption fails closed.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import load_only
    from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceStream

    if not comparisons:
        return {}
    expected = {r.reconciliation_id: (r, capture) for r, capture in comparisons}
    keys = {PREFIX + manifest_sha256([identifier, POLICY]): identifier for identifier in expected}
    stream_ids = {capture.stream_id for _, capture in comparisons}
    streams = {row.stream_id: row for row in session.scalars(select(ReferenceStream).where(
        ReferenceStream.stream_id.in_(stream_ids)))}
    receipts = {(row.stream_id, row.generation): row for row in session.scalars(
        select(ReferenceActivationReceipt).where(ReferenceActivationReceipt.stream_id.in_(stream_ids)))}
    result = {}
    for row in session.scalars(select(ReferenceBatch).options(load_only(
            ReferenceBatch.batch_id, ReferenceBatch.stream_id, ReferenceBatch.revision_id,
            ReferenceBatch.batch_key, ReferenceBatch.kind, ReferenceBatch.source_evidence,
            ReferenceBatch.payload_hash,
    )).where(
            ReferenceBatch.stream_id.in_({capture.stream_id for _, capture in comparisons}),
            ReferenceBatch.batch_key.in_(keys))):
        identifier = keys[row.batch_key]
        comparison, capture = expected[identifier]
        try:
            fact = row.source_evidence[KEY]
            activation = _activation_binding(capture, streams.get(capture.stream_id),
                receipts.get((capture.stream_id, capture.source_evidence["forward_capture_v1"]["generation"])),
                receipts.values())
            _require(row.kind == "diagnostic" and row.stream_id == capture.stream_id
                     and row.revision_id == capture.revision_id
                     and row.source_evidence == {KEY: _fact(capture, comparison, fact["proof"], activation)}
                     and row.payload_hash == manifest_sha256(fact))
        except (KeyError, TypeError, ValueError) as error:
            raise RepositoryConflict("SOURCE_REVISION_RECEIPT_INVALID") from error
        result[identifier] = fact
    return result
