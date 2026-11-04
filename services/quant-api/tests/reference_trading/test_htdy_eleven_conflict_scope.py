"""Exact November incident: mixed generations, append-only boundary and narrow scope."""

from datetime import timedelta
import pytest
from sqlalchemy import select
from app.reference_trading import htdy_conflict_recovery as domain
from app.reference_trading.htdy_conflict_incidents import NOV03_VERSION, NOV03_BINDINGS
from app.reference_trading.htdy_activation import htdy_identity
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.models import (
    ReferenceStream,
    ReferenceRevision,
    ReferenceBatch,
    ReferenceActivationReceipt,
    ReferenceTradeRow,
    ReferenceActionRow,
)
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_htdy_conflict_recovery import (
    NOW,
    conflict_setup,
    add_open_trade,
)

PRODUCTS = ("ap", "cj", "jd", "lc", "lh", "pd", "pk", "ps", "pt", "sf", "sm")
OPEN = ("cj", "pd", "ps", "pt", "sm")


def eleven_setup(monkeypatch, engine=None):
    factory, recovery, _ = conflict_setup(engine, products=[*PRODUCTS, "rb"])
    return configure_eleven(factory, recovery, monkeypatch)


def configure_eleven(
    factory,
    recovery,
    monkeypatch,
    *,
    products=PRODUCTS,
    opened=OPEN,
    bindings=NOV03_BINDINGS,
    incident=NOV03_VERSION,
    binding_name="NOV03_BINDINGS",
):
    for product in opened:
        add_open_trade(factory, product, action_pk="original-action-" + product)
    ids = [htdy_identity(p).stream_id for p in products]
    frozen_bindings = bindings
    bindings = {}
    with factory() as db, db.begin():
        for sid in ids:
            stream = db.get(ReferenceStream, sid)
            revision = db.get(ReferenceRevision, (sid, stream.active_revision_id))
            receipt = db.scalar(
                select(ReferenceActivationReceipt).where(
                    ReferenceActivationReceipt.stream_id == sid
                )
            )
            cap = db.scalar(
                select(ReferenceBatch).where(
                    ReferenceBatch.stream_id == sid, ReferenceBatch.kind == "capture"
                )
            )
            # Separate fixture IDs, with the actual incident's mixed current generations.
            generation = frozen_bindings[sid][2]
            stream.activation_generation = receipt.generation = generation
            wire = cap.source_evidence["forward_capture_v1"]
            original = ForwardCapture(
                sid,
                revision.revision_id,
                generation,
                wire["source_key"],
                __import__("datetime").datetime.fromisoformat(wire["bar_end"]),
                __import__("datetime").datetime.fromisoformat(wire["observed_at"]),
                wire["source_kind"],
                wire["input_payload"],
                wire["source_proof"],
                wire["eligibility"],
            )
            cap.source_evidence, cap.payload_hash = (
                original.evidence(),
                original.capture_hash,
            )
            batch = db.get(ReferenceBatch, revision.checkpoint_batch_id)
            from guiyi_quant.reference_trading.strategy_checkpoint import (
                adapter_checkpoint_from_json,
            )

            cp = adapter_checkpoint_from_json(
                batch.checkpoint_text,
                expected_stream=htdy_identity(stream.product),
                expected_strategy_schema="htdy_first_seen_v1",
            )
            opened = cp.reference_state.open_trade
            bindings[sid] = (
                revision.revision_id,
                cap.batch_id,
                generation,
                batch.batch_id,
                None if opened is None else opened.reference_trade_id,
            )
    monkeypatch.setattr(domain, binding_name, bindings)
    recovery.incident = incident
    return factory, recovery, ids


def freeze(recovery, ids):
    return recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )


def test_eleven_atomic_retains_originals_five_open_and_unselected(monkeypatch):
    factory, recovery, ids = eleven_setup(monkeypatch)
    with factory() as db:
        originals = {
            b.batch_id: domain._row(b) for b in db.scalars(select(ReferenceBatch))
        }
        rb = domain._row(db.get(ReferenceStream, htdy_identity("rb").stream_id))
        actions = len(db.scalars(select(ReferenceActionRow)).all())
    plan = freeze(recovery, ids)
    assert plan["version"] == NOV03_VERSION
    result = recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert set(result) == set(ids) and recovery.readback(plan) == result
    with factory() as db:
        assert all(
            domain._row(db.get(ReferenceBatch, k)) == v for k, v in originals.items()
        )
        assert domain._row(db.get(ReferenceStream, htdy_identity("rb").stream_id)) == rb
        interrupted = db.scalars(
            select(ReferenceTradeRow).where(
                ReferenceTradeRow.status == "DATA_INTERRUPTED"
            )
        ).all()
        assert len(interrupted) == 5
        assert all(
            r.exit_reference_price is None and r.reference_return is None
            for r in interrupted
        )
        assert len(db.scalars(select(ReferenceActionRow)).all()) == actions == 5
        assert all(
            db.get(ReferenceStream, sid).activation_generation
            == domain.NOV03_BINDINGS[sid][2] + 1
            for sid in ids
        )
        assert domain.retired_delivery_ids(db, stream_ids=ids) == ()
    with pytest.raises(RepositoryConflict):
        freeze(recovery, ids)


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "duplicate",
        "revision",
        "capture",
        "generation",
        "checkpoint",
        "open_id",
        "open_set",
    ],
)
def test_eleven_exact_preimage_drift_rejected_before_boundary(monkeypatch, change):
    factory, recovery, ids = eleven_setup(monkeypatch)
    if change == "scope":
        ids[-1] = htdy_identity("rb").stream_id
    elif change == "duplicate":
        ids[-1] = ids[0]
    elif change == "open_set":
        add_open_trade(factory, "ap", action_pk="extra-ap")
    else:
        sid = ids[0] if change != "open_id" else htdy_identity("cj").stream_id
        index = {
            "revision": 0,
            "capture": 1,
            "generation": 2,
            "checkpoint": 3,
            "open_id": 4,
        }[change]
        current = list(domain.NOV03_BINDINGS[sid])
        current[index] = "foreign" if index != 2 else 9
        monkeypatch.setattr(
            domain, "NOV03_BINDINGS", {**domain.NOV03_BINDINGS, sid: tuple(current)}
        )
    with pytest.raises(RepositoryConflict):
        freeze(recovery, ids)
    with factory() as db:
        assert not any(
            domain.KEY in b.source_evidence for b in db.scalars(select(ReferenceBatch))
        )


def test_eleven_rehashed_readback_outside_scope_rejected(monkeypatch):
    _, recovery, ids = eleven_setup(monkeypatch)
    p = freeze(recovery, ids)
    p["items"][0]["binding"]["stream_id"] = "outside"
    p["plan_hash"] = domain._hash({k: v for k, v in p.items() if k != "plan_hash"})
    with pytest.raises(RepositoryConflict, match="SCOPE_INVALID"):
        recovery.readback(p)


@pytest.mark.parametrize("cause", ["prior_retirement", "new_source", "fence"])
def test_eleven_prior_proof_source_and_fence_fail_closed(monkeypatch, cause):
    factory, recovery, ids = eleven_setup(monkeypatch)
    if cause == "prior_retirement":
        import app.reference_trading.inbox_recovery as inbox

        def invalid(*a, **kw):
            raise RepositoryConflict("HTDY_CONFLICT_RETIREMENT_INVALID")

        monkeypatch.setattr(inbox, "verified_resolution_ids", invalid)
        with pytest.raises(RepositoryConflict, match="RETIREMENT_INVALID"):
            freeze(recovery, ids)
        return
    p = freeze(recovery, ids)
    if cause == "new_source":
        original = recovery.verify_source
        recovery.verify_source = lambda *a: {**original(*a), "changed": True}
    else:
        calls = []

        def lost():
            calls.append(True)
            if len(calls) == 2:
                raise RepositoryConflict("FENCE_LOST")

        recovery.assert_fenced = lost
    with pytest.raises(RepositoryConflict):
        recovery.apply(p, expected_plan_hash=p["plan_hash"], now=NOW)
    assert recovery.readback(p) is None
    with factory() as db:
        assert all(
            db.get(ReferenceStream, sid).activation_generation
            == domain.NOV03_BINDINGS[sid][2]
            for sid in ids
        )


def repeated_retirement(factory, recovery, ids, monkeypatch, *, tamper=False):
    """A real prior boundary, natural successor commit and a second native boundary."""
    from copy import deepcopy
    from dataclasses import replace
    from datetime import datetime
    from hashlib import sha256
    import json
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.htdy import evaluate_htdy_capture
    from app.reference_trading.inbox import ReferenceInboxRepository
    from app.reference_trading.inbox_recovery import verified_resolution_ids
    from app.reference_trading.models import ReferenceInboxDelivery
    from app.reference_trading.htdy_conflict_source import _fact, _bar, FIELDS
    from tests.reference_trading.test_htdy_conflict_source import (
        fixture as source_fixture,
    )
    from tests.reference_trading.test_htdy_conflict_recovery import _inbox
    from tests.reference_trading.test_inbox import event
    from guiyi_quant.reference_trading.strategy_checkpoint import (
        adapter_checkpoint_from_json,
    )
    import app.reference_trading.repository as repository_module

    old_delivery = _inbox(factory)
    first = freeze(recovery, ids)
    recovery.apply(first, expected_plan_hash=first["plan_hash"], now=NOW)
    repo = ReferenceRepository(factory)
    identity = htdy_identity("rb")
    sid = identity.stream_id
    state = repo.read_state(sid)
    token, seed = repo.load_checkpoint(sid)
    source, _, template, template_capture = source_fixture()
    old_template = adapter_checkpoint_from_json(
        json.dumps(template["checkpoint"]),
        expected_stream=source_fixture()[1],
        expected_strategy_schema="htdy_first_seen_v1",
    )
    end = NOW + timedelta(hours=2)
    delta = end - old_template.computed_through
    clock = [end + timedelta(seconds=1)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(repository_module, "datetime", Clock)

    def shifted(raw):
        raw = deepcopy(raw)
        stamp = datetime.fromisoformat(raw["bar_end"]) + delta
        raw["bar_end"], raw["trading_day"] = stamp.isoformat(), stamp.date().isoformat()
        return raw

    old_raw = [
        dict(
            bar_end=(b.bar_end + delta).isoformat(),
            trading_day=(b.bar_end + delta).date().isoformat(),
            **{f: str(getattr(b, f)) for f in FIELDS},
            turnover=None,
            open_interest=None,
        )
        for b in old_template.strategy_state.window
    ]

    def make_capture(raw, source_key, proof_extra=None):
        bar_end = datetime.fromisoformat(raw[-1]["bar_end"])
        proof = {
            **template_capture.source_proof,
            "window_sha256": sha256(
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "event_bar_end": bar_end.isoformat(),
            **(proof_extra or {}),
        }
        if proof_extra is None:
            proof.pop("inbox_delivery_id", None)
            proof.pop("journal_envelope_sha256", None)
        return ForwardCapture(
            sid,
            state.revision_id,
            2,
            source_key,
            bar_end,
            bar_end + timedelta(seconds=1),
            "completed_live",
            {
                "bars": raw,
                "bar_contracts": ["RB2610"] * 32,
                "contract": "RB2610",
                "trading_day": raw[-1]["trading_day"],
                "bar": raw[-1],
            },
            proof,
            "first_seen",
        )

    natural = make_capture(old_raw, "natural-successor")
    natural_id = repo.capture_forward(natural)
    prepared = evaluate_htdy_capture(
        token,
        seed,
        {**natural.evidence(), "capture_id": natural_id},
        dependency_manifest=state.dependency_manifest,
    )
    assert repo.commit_batch(token, prepared).seq == 2
    pending_raw = [shifted(x) for x in template_capture.input_payload["bars"]]
    pending_end = datetime.fromisoformat(pending_raw[-1]["bar_end"])
    clock[0] = pending_end + timedelta(seconds=1)
    new_event = replace(event("20-0", end=pending_end), channel="live:bar:rb:60m")
    new_delivery = (
        ReferenceInboxRepository(factory)
        .ingest(new_event, ingested_at=clock[0])
        .delivery_ids[0]
    )
    pending = make_capture(
        pending_raw,
        "second-context-conflict",
        {
            "inbox_delivery_id": new_delivery,
            "journal_envelope_sha256": sha256(new_event.to_json().encode()).hexdigest(),
        },
    )
    pending_id = repo.capture_forward(pending)
    _, cp = repo.load_checkpoint(sid)
    with factory() as db:
        revision = db.get(ReferenceRevision, (sid, state.revision_id))
        checkpoint_id = revision.checkpoint_batch_id
    opened = cp.reference_state.open_trade
    monkeypatch.setattr(
        domain,
        "NOV03_BINDINGS",
        {
            sid: (
                state.revision_id,
                pending_id,
                2,
                checkpoint_id,
                None if opened is None else opened.reference_trade_id,
            )
        },
    )
    recovery.incident = NOV03_VERSION
    base_proof = source(source_fixture()[1], template, {})

    def current_source(identity, binding, manifest):
        proof = deepcopy(base_proof)
        proof.update(
            checkpoint_sha256=binding["checkpoint_sha256"],
            capture_sha256=pending.capture_hash,
            boundary_end=pending.bar_end.isoformat(),
            boundary_trading_day=pending_raw[-1]["trading_day"],
        )
        conflicts = []
        for a, raw in zip(cp.strategy_state.window[1:], pending_raw[:-1]):
            b = _bar(raw)
            fields = {
                f: {"old": str(getattr(a, f)), "new": str(getattr(b, f))}
                for f in FIELDS
                if getattr(a, f) != getattr(b, f)
            }
            if fields:
                conflicts.append(
                    dict(
                        bar_end=b.bar_end.isoformat(),
                        contract="RB2610",
                        old_sha256=__import__(
                            "app.reference_trading.contracts",
                            fromlist=["manifest_sha256"],
                        ).manifest_sha256(_fact(a, "RB2610")),
                        new_sha256=__import__(
                            "app.reference_trading.contracts",
                            fromlist=["manifest_sha256"],
                        ).manifest_sha256(_fact(b, "RB2610")),
                        fields=fields,
                    )
                )
        proof["conflicts"] = conflicts
        return proof

    recovery.verify_source = current_source
    second_now = clock[0] + timedelta(minutes=1)
    recovery.clock = lambda: second_now
    with factory() as db:
        assert old_delivery in verified_resolution_ids(db, stream_ids=[sid])
        originals = {
            x.batch_id: domain._row(x) for x in db.scalars(select(ReferenceBatch))
        }
    if tamper:
        with factory() as db, db.begin():
            db.get(ReferenceInboxDelivery, old_delivery).code = "TAMPER"
        with pytest.raises(RepositoryConflict, match="RETIREMENT_INVALID"):
            recovery.plan(
                [sid],
                recording_start=second_now + timedelta(hours=1),
                expires_at=second_now + timedelta(minutes=1),
                now=second_now,
            )
        return
    second = recovery.plan(
        [sid],
        recording_start=second_now + timedelta(hours=1),
        expires_at=second_now + timedelta(minutes=1),
        now=second_now,
    )
    assert [d["delivery_id"] for d in second["items"][0]["binding"]["deliveries"]] == [
        new_delivery
    ]
    recovery.apply(second, expected_plan_hash=second["plan_hash"], now=second_now)
    with factory() as db:
        resolved = verified_resolution_ids(db, stream_ids=[sid])
        assert set(resolved) == {old_delivery, new_delivery} and len(resolved) == 2
        assert all(
            domain._row(db.get(ReferenceBatch, k)) == v for k, v in originals.items()
        )
        assert db.get(ReferenceInboxDelivery, old_delivery).status == "PENDING"
        assert db.get(ReferenceInboxDelivery, new_delivery).status == "PENDING"
        assert db.get(ReferenceStream, sid).activation_generation == 3


@pytest.mark.parametrize("tamper", [False, True])
def test_two_real_retirements_keep_union_and_reject_prior_tamper(monkeypatch, tamper):
    factory, recovery, ids = conflict_setup()
    repeated_retirement(factory, recovery, ids, monkeypatch, tamper=tamper)
