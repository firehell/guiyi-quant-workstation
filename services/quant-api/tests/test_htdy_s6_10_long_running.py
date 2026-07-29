from __future__ import annotations

from datetime import UTC, date, datetime, time
import json
from pathlib import Path

import pytest


SHA = "a" * 64


def _parent() -> dict[str, object]:
    parent = {
        "schema_version": 7,
        "task_id": "JM-LIVE-STABILITY-S6-10",
        "packet_type": "htdy_s6_10_remaining_trading_day_parent",
        "window_mode": "complete_trading_day",
        "complete_trading_day_claim_allowed": True,
        "trading_days": ["2026-07-30"],
        "night_session_date": "2026-07-29",
        "bindings": {
            "runtime_commit": "b" * 40,
            "runtime_tree": "c" * 64,
            "source_commit": "b" * 40,
            "source_tree": "c" * 64,
            "approval_c2_approved_signers_sha256": SHA,
        },
    }
    from app.services.htdy_s6_10_remaining_window import canonical_hash

    parent["packet_hash"] = canonical_hash(parent)
    return parent


def _sample(parent: dict[str, object]) -> dict[str, object]:
    from app.services.htdy_s6_10_remaining_window import (
        _jm_15m_bucket_ends,
        canonical_hash,
    )

    bucket_ends = [
        value.isoformat()
        for value in _jm_15m_bucket_ends(
            date(2026, 7, 29),
            date(2026, 7, 30),
        )
    ]

    sample = {
        "schema_version": 7,
        "sample_type": "htdy_s6_10_remaining_window_ledger",
        "parent_packet_hash": parent["packet_hash"],
        "trading_day": "2026-07-30",
        "expected_confirmed_15m_closes": 23,
        "evaluated_confirmed_15m_closes": 23,
        "partial_evaluations": 0,
        "partial_rejections": 0,
        "expected_bucket_ends": bucket_ends,
        "evaluated_bucket_ends": bucket_ends,
        "event_counts": {"signal_changed": 0},
        "notification_counts": {
            "failed": 0,
            "duplicate_dedupe_keys": 0,
            "attempts_over_limit": 0,
        },
        "health": {
            "runtime": True,
            "redis": True,
            "database": True,
            "after_market": True,
        },
        "eod_status": "passed",
        "eod_authorization_hash": SHA,
        "complete_trading_day_passed": True,
    }
    sample["sample_hash"] = canonical_hash(sample)
    return sample


def _approved_receipt(request: dict[str, object]) -> dict[str, object]:
    from app.services.htdy_s6_10_remaining_window import canonical_hash

    receipt = {
        "schema_version": 1,
        "approval": "Approval D",
        "decision": "approved",
        "approved_at": "2026-07-30T08:30:00+00:00",
        "request_hash": request["request_hash"],
        "parent_packet_hash": request["parent_packet_hash"],
        "runtime_commit": request["runtime_commit"],
        "runtime_tree": request["runtime_tree"],
        "no_code_promotion": True,
        "reuse_s6_07_eod": True,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    return receipt


def test_approval_d_request_binds_clean_full_day_and_same_code() -> None:
    from app.services.htdy_s6_10_long_running import build_approval_d_request

    parent = _parent()
    request = build_approval_d_request(
        parent_packet=parent,
        acceptance_sample=_sample(parent),
        generated_at=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
    )

    assert request["approval"] == "Approval D"
    assert request["runtime_commit"] == "b" * 40
    assert request["runtime_tree"] == "c" * 64
    assert request["no_code_promotion"] is True
    assert request["reuse_s6_07_eod"] is True
    assert request["approval_d_approved_signers_sha256"] == SHA
    assert request["eod_authorization_hash"] == SHA


def test_approval_d_request_rejects_tampered_acceptance_sample() -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        build_approval_d_request,
    )

    parent = _parent()
    sample = _sample(parent)
    sample["eod_status"] = "failed"

    with pytest.raises(
        HtDyS610LongRunningError, match="full_day_acceptance_invalid"
    ):
        build_approval_d_request(
            parent_packet=parent,
            acceptance_sample=sample,
            generated_at=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("sample_type", "wrong"),
        ("partial_rejections", 1),
        ("evaluated_bucket_ends", []),
    ),
)
def test_approval_d_request_recomputes_exact_full_day_acceptance(
    field: str,
    value: object,
) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        build_approval_d_request,
    )
    from app.services.htdy_s6_10_remaining_window import canonical_hash

    parent = _parent()
    sample = _sample(parent)
    sample[field] = value
    sample["sample_hash"] = canonical_hash(
        {
            key: item
            for key, item in sample.items()
            if key != "sample_hash"
        }
    )
    with pytest.raises(
        HtDyS610LongRunningError,
        match="full_day_acceptance_invalid",
    ):
        build_approval_d_request(
            parent_packet=parent,
            acceptance_sample=sample,
            generated_at=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
        )


def _write_signed_receipt(
    tmp_path: Path, request: dict[str, object]
) -> tuple[Path, Path, Path, str]:
    receipt = _approved_receipt(request)
    receipt_path = tmp_path / "approval-d.json"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True), encoding="utf-8"
    )
    signature_path = tmp_path / "approval-d.sig"
    signature_path.write_text("signature", encoding="utf-8")
    signers_path = tmp_path / "approved_signers"
    signers_path.write_text("guiyi-owner key", encoding="utf-8")
    return (
        receipt_path,
        signature_path,
        signers_path,
        str(receipt["receipt_hash"]),
    )


def test_long_running_daily_child_requires_signed_approval_prior_eod_and_same_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        build_approval_d_request,
        build_long_running_daily_child,
    )

    parent = _parent()
    request = build_approval_d_request(
        parent_packet=parent,
        acceptance_sample=_sample(parent),
        generated_at=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
    )
    receipt_path, signature_path, signers_path, receipt_hash = (
        _write_signed_receipt(tmp_path, request)
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._file_sha256",
        lambda _path: SHA,
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._verify_approved_signers_trust_root",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._verify_ssh_signature",
        lambda *_args: True,
    )
    child = build_long_running_daily_child(
        approval_d_request=request,
        approval_d_receipt_path=receipt_path,
        approval_d_signature_path=signature_path,
        approved_signers_path=signers_path,
        approval_d_hash=receipt_hash,
        trading_day=date(2026, 7, 31),
        actual_contract="JM2609",
        mapping_sha256=SHA,
        session_geometry_sha256=SHA,
        source_facts_sha256=SHA,
        current_runtime_commit="b" * 40,
        current_runtime_tree="c" * 64,
        prior_eod={
            "trading_day": "2026-07-30",
            "status": "passed",
            "authorization_hash": SHA,
        },
        previous_trading_day=date(2026, 7, 30),
        expected_bucket_ends=[
            datetime(2026, 7, 31, 1, index, tzinfo=UTC).isoformat()
            for index in range(23)
        ],
    )

    assert child["global_wechat_autosend"] is False
    assert child["max_wecom_notifications"] == 23
    assert child["auto_order"] is False
    assert child["reuse_s6_07_eod"] is True

    with pytest.raises(HtDyS610LongRunningError, match="prior_eod_not_passed"):
        build_long_running_daily_child(
            approval_d_request=request,
            approval_d_receipt_path=receipt_path,
            approval_d_signature_path=signature_path,
            approved_signers_path=signers_path,
            approval_d_hash=receipt_hash,
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            mapping_sha256=SHA,
            session_geometry_sha256=SHA,
            source_facts_sha256=SHA,
            current_runtime_commit="b" * 40,
            current_runtime_tree="c" * 64,
            prior_eod={"trading_day": "2026-07-31", "status": "failed"},
            previous_trading_day=date(2026, 7, 31),
            expected_bucket_ends=[
                datetime(2026, 8, 3, 1, index, tzinfo=UTC).isoformat()
                for index in range(23)
            ],
        )


def test_long_running_daily_child_rejects_unsigned_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        build_approval_d_request,
        build_long_running_daily_child,
    )

    parent = _parent()
    request = build_approval_d_request(
        parent_packet=parent,
        acceptance_sample=_sample(parent),
        generated_at=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
    )
    receipt_path, signature_path, signers_path, receipt_hash = (
        _write_signed_receipt(tmp_path, request)
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._file_sha256",
        lambda _path: SHA,
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._verify_approved_signers_trust_root",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._verify_ssh_signature",
        lambda *_args: False,
    )

    with pytest.raises(
        HtDyS610LongRunningError, match="approval_d_receipt_invalid"
    ):
        build_long_running_daily_child(
            approval_d_request=request,
            approval_d_receipt_path=receipt_path,
            approval_d_signature_path=signature_path,
            approved_signers_path=signers_path,
            approval_d_hash=receipt_hash,
            trading_day=date(2026, 7, 31),
            actual_contract="JM2609",
            mapping_sha256=SHA,
            session_geometry_sha256=SHA,
            source_facts_sha256=SHA,
            current_runtime_commit="b" * 40,
            current_runtime_tree="c" * 64,
            prior_eod={
                "trading_day": "2026-07-30",
                "status": "passed",
                "authorization_hash": SHA,
            },
            previous_trading_day=date(2026, 7, 30),
            expected_bucket_ends=[
                datetime(2026, 7, 31, 1, index, tzinfo=UTC).isoformat()
                for index in range(23)
            ],
        )


def test_daily_child_rejects_non_adjacent_or_wrong_eod_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        build_approval_d_request,
        build_long_running_daily_child,
    )

    parent = _parent()
    request = build_approval_d_request(
        parent_packet=parent,
        acceptance_sample=_sample(parent),
        generated_at=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
    )
    receipt_path, signature_path, signers_path, receipt_hash = (
        _write_signed_receipt(tmp_path, request)
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._file_sha256",
        lambda _path: SHA,
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._verify_approved_signers_trust_root",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running._verify_ssh_signature",
        lambda *_args: True,
    )
    kwargs = {
        "approval_d_request": request,
        "approval_d_receipt_path": receipt_path,
        "approval_d_signature_path": signature_path,
        "approved_signers_path": signers_path,
        "approval_d_hash": receipt_hash,
        "trading_day": date(2026, 8, 3),
        "actual_contract": "JM2609",
        "mapping_sha256": SHA,
        "session_geometry_sha256": SHA,
        "source_facts_sha256": SHA,
        "current_runtime_commit": "b" * 40,
        "current_runtime_tree": "c" * 64,
        "expected_bucket_ends": [
            datetime(2026, 8, 3, 1, index, tzinfo=UTC).isoformat()
            for index in range(23)
        ],
    }

    with pytest.raises(
        HtDyS610LongRunningError, match="prior_eod_not_passed"
    ):
        build_long_running_daily_child(
            **kwargs,
            previous_trading_day=date(2026, 7, 31),
            prior_eod={
                "trading_day": "2026-07-30",
                "status": "passed",
                "authorization_hash": SHA,
            },
        )
    with pytest.raises(
        HtDyS610LongRunningError, match="prior_eod_not_passed"
    ):
        build_long_running_daily_child(
            **kwargs,
            previous_trading_day=date(2026, 7, 31),
            prior_eod={
                "trading_day": "2026-07-31",
                "status": "passed",
                "authorization_hash": "f" * 64,
            },
        )


def test_runtime_gate_publishes_and_consumes_exact_daily_child() -> None:
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        HtDyS610LongRunningRuntimeGate,
    )

    published: list[dict[str, object]] = []
    handler = object()
    gate = HtDyS610LongRunningRuntimeGate(
        approval_d_request={"request_hash": SHA},
        approval_d_hash="d" * 64,
        approval_verifier=lambda: None,
        daily_facts_collector=lambda _session, _now, _allow_create: {
            "trading_day": date(2026, 8, 3),
            "previous_trading_day": date(2026, 7, 31),
            "actual_contract": "JM2609",
            "mapping_sha256": SHA,
            "mapping_receipt": {
                "receipt_type": "htdy_s6_10_daily_mapping",
                "receipt_hash": "f" * 64,
            },
            "session_geometry_sha256": SHA,
            "source_facts_sha256": SHA,
            "runtime_commit": "b" * 40,
            "runtime_tree": "c" * 64,
            "prior_eod": {
                "trading_day": "2026-07-31",
                "status": "passed",
                "authorization_hash": SHA,
            },
            "expected_bucket_ends": [
                datetime(2026, 8, 3, 1, index, tzinfo=UTC).isoformat()
                for index in range(23)
            ],
            "window_end": datetime(2026, 8, 3, 8, tzinfo=UTC).isoformat(),
        },
        child_builder=lambda **facts: {
            "packet_hash": "e" * 64,
            "trading_day": facts["trading_day"].isoformat(),
            "expected_bucket_ends": facts["expected_bucket_ends"],
            "window_end": facts["window_end"],
        },
        mapping_receipt_publisher=lambda receipt, **_kwargs: receipt,
        child_publisher=lambda child, **_kwargs: (
            published.append(child) or child
        ),
        handler_factory=lambda _session, *, allowed_bucket_ends: (
            handler
            if len(allowed_bucket_ends) == 23
            else pytest.fail("23 closes required")
        ),
        now=lambda: datetime(2026, 8, 3, 1, tzinfo=UTC),
    )

    assert gate(object(), phase="verify")["gate_status"] == "verified"
    result = gate(object(), phase="pre_write")
    gate(
        object(),
        phase="post_write",
        result={"signal_events": {"changed": 0}},
    )
    gate(object(), phase="after_commit")
    repeated = gate(object(), phase="daily_metadata")

    assert result["signal_event_handler"] is handler
    assert result["authorization_hash"] == "e" * 64
    assert repeated["authorization_hash"] == "e" * 64
    assert len(published) == 2


def test_runtime_gate_requires_receipt_and_child_before_event_transaction() -> None:
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        HtDyS610LongRunningRuntimeGate,
    )

    calls: list[object] = []
    receipt = {
        "receipt_type": "htdy_s6_10_daily_mapping",
        "receipt_hash": "f" * 64,
    }

    def collect(_session, _now, allow_mapping_create):
        calls.append(("collect", allow_mapping_create))
        return {
            "trading_day": date(2026, 8, 3),
            "previous_trading_day": date(2026, 7, 31),
            "actual_contract": "JM2609",
            "mapping_sha256": SHA,
            "mapping_receipt": receipt,
            "session_geometry_sha256": SHA,
            "source_facts_sha256": SHA,
            "runtime_commit": "b" * 40,
            "runtime_tree": "c" * 64,
            "prior_eod": {
                "trading_day": "2026-07-31",
                "status": "passed",
                "authorization_hash": SHA,
            },
            "expected_bucket_ends": [
                datetime(2026, 8, 3, 1, index, tzinfo=UTC).isoformat()
                for index in range(23)
            ],
            "window_end": datetime(
                2026, 8, 3, 8, tzinfo=UTC
            ).isoformat(),
        }

    gate = HtDyS610LongRunningRuntimeGate(
        approval_d_request={"request_hash": SHA},
        approval_d_hash="d" * 64,
        approval_verifier=lambda: None,
        daily_facts_collector=collect,
        child_builder=lambda **facts: {
            "packet_hash": "e" * 64,
            "trading_day": facts["trading_day"].isoformat(),
            "expected_bucket_ends": facts["expected_bucket_ends"],
            "window_end": facts["window_end"],
        },
        mapping_receipt_publisher=lambda value, *, trading_day, create: (
            calls.append(("receipt", trading_day, create)) or value
        ),
        child_publisher=lambda value, *, create: (
            calls.append(("child", create)) or value
        ),
        handler_factory=lambda _session, **_kwargs: object(),
        now=lambda: datetime(2026, 8, 3, 1, tzinfo=UTC),
    )

    gate(object(), phase="pre_write")
    assert calls == [
        ("collect", True),
        ("receipt", date(2026, 8, 3), False),
        ("child", True),
    ]

    gate(
        object(),
        phase="post_write",
        result={"signal_events": {"changed": 0}},
    )
    assert calls == [
        ("collect", True),
        ("receipt", date(2026, 8, 3), False),
        ("child", True),
    ]

    gate(object(), phase="after_commit")
    assert calls == [
        ("collect", True),
        ("receipt", date(2026, 8, 3), False),
        ("child", True),
    ]

    gate(object(), phase="daily_metadata")
    assert calls[-3:] == [
        ("collect", False),
        ("receipt", date(2026, 8, 3), False),
        ("child", False),
    ]


def test_runtime_gate_commits_preopen_mapping_without_daily_child() -> None:
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        HtDyS610LongRunningRuntimeGate,
    )

    calls: list[object] = []
    receipt = {
        "receipt_type": "htdy_s6_10_daily_mapping",
        "receipt_hash": "f" * 64,
    }
    gate = HtDyS610LongRunningRuntimeGate(
        approval_d_request={"request_hash": SHA},
        approval_d_hash="d" * 64,
        approval_verifier=lambda: None,
        daily_facts_collector=lambda _session, _now, _allow_create: {
            "gate_status": "mapping_prepared",
            "trading_day": date(2026, 8, 3),
            "actual_contract": "JM2609",
            "mapping_sha256": SHA,
            "mapping_receipt": receipt,
        },
        child_builder=lambda **_facts: pytest.fail(
            "preopen mapping must not build a child"
        ),
        mapping_receipt_publisher=lambda value, **kwargs: (
            calls.append(("receipt", kwargs)) or value
        ),
        child_publisher=lambda _value, **_kwargs: pytest.fail(
            "preopen mapping must not publish a child"
        ),
        handler_factory=lambda _session, **_kwargs: pytest.fail(
            "preopen mapping must not build a handler"
        ),
    )

    metadata = gate(object(), phase="pre_write")
    assert metadata == {
        "gate_schema": "s6_10_approval_d_daily_child_v1",
        "approval_d_hash": "d" * 64,
        "gate_status": "waiting",
        "mapping_prepared": True,
        "target_trading_day": "2026-08-03",
        "after_commit_required": True,
    }
    assert calls == []

    committed = gate(object(), phase="after_commit")
    assert committed["gate_status"] == "waiting"
    assert committed["mapping_prepared"] is True
    assert calls == [
        (
            "receipt",
            {"trading_day": date(2026, 8, 3), "create": True},
        )
    ]


def test_daily_child_publication_is_create_only_and_recoverable(
    tmp_path: Path,
) -> None:
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        publish_daily_child_create_only,
    )
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        canonical_hash,
    )

    child = {
        "trading_day": "2026-08-03",
        "expected_bucket_ends": ["2026-08-03T01:15:00+00:00"] * 23,
        "window_end": "2026-08-03T07:00:00+00:00",
    }
    child["packet_hash"] = canonical_hash(child)
    root = tmp_path / "children"
    root.mkdir()

    assert publish_daily_child_create_only(child, root=root) == child
    assert publish_daily_child_create_only(child, root=root) == child

    with pytest.raises(
        HtDyS610LongRunningError,
        match="daily_child_publication_conflict",
    ):
        conflict = {**child, "window_end": "2026-08-03T08:00:00+00:00"}
        conflict["packet_hash"] = canonical_hash(conflict)
        publish_daily_child_create_only(conflict, root=root)


def test_daily_mapping_receipt_publication_is_create_only_and_read_only(
    tmp_path: Path,
) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        canonical_hash,
    )
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        publish_daily_mapping_receipt_create_only,
    )

    receipt = {
        "schema_version": 1,
        "receipt_type": "htdy_s6_10_daily_mapping",
        "trading_day": "2026-08-03",
        "approval_d_hash": "d" * 64,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    root = tmp_path / "daily"
    root.mkdir()

    with pytest.raises(
        HtDyS610LongRunningError,
        match="daily_mapping_receipt_missing",
    ):
        publish_daily_mapping_receipt_create_only(
            receipt,
            root=root,
            trading_day=date(2026, 8, 3),
            create=False,
        )
    assert list(root.iterdir()) == []

    assert publish_daily_mapping_receipt_create_only(
        receipt,
        root=root,
        trading_day=date(2026, 8, 3),
        create=True,
    ) == receipt
    assert publish_daily_mapping_receipt_create_only(
        receipt,
        root=root,
        trading_day=date(2026, 8, 3),
        create=False,
    ) == receipt

    conflict = dict(receipt)
    conflict["approval_d_hash"] = "e" * 64
    conflict["receipt_hash"] = canonical_hash(
        {
            key: value
            for key, value in conflict.items()
            if key != "receipt_hash"
        }
    )
    with pytest.raises(
        HtDyS610LongRunningError,
        match="daily_mapping_receipt_publication_conflict",
    ):
        publish_daily_mapping_receipt_create_only(
            conflict,
            root=root,
            trading_day=date(2026, 8, 3),
            create=False,
        )


def test_daily_facts_are_derived_from_clock_mapping_eod_source_and_runtime() -> None:
    from types import SimpleNamespace

    from app.services.htdy_s6_10_long_running_runtime_gate import (
        collect_long_running_daily_facts,
    )

    target = date(2026, 8, 3)
    previous = date(2026, 7, 31)
    windows = [
        SimpleNamespace(
            name="night",
            start=datetime.combine(previous, time(21)),
            end=datetime.combine(previous, time(23)),
        ),
        SimpleNamespace(
            name="day-1",
            start=datetime.combine(target, time(9)),
            end=datetime.combine(target, time(10, 15)),
        ),
        SimpleNamespace(
            name="day-2",
            start=datetime.combine(target, time(10, 30)),
            end=datetime.combine(target, time(11, 30)),
        ),
        SimpleNamespace(
            name="day-3",
            start=datetime.combine(target, time(13, 30)),
            end=datetime.combine(target, time(15)),
        ),
    ]

    class Clock:
        def decision(self, **_kwargs):
            return SimpleNamespace(
                should_poll=True,
                trading_day=target,
            )

        def windows_for_trading_day(self, *_args, **_kwargs):
            return windows

        def _previous_trading_day(self, *_args):
            return previous

    facts = collect_long_running_daily_facts(
        object(),
        datetime(2026, 8, 3, 1, tzinfo=UTC),
        eod_authorization_hash=SHA,
        runtime_root=Path("/runtime"),
        clock_factory=lambda _session: Clock(),
        mapping_collector=lambda _session, _day, _allow_create: {
            "actual_contract": "JM2609",
            "mapping_sha256": "b" * 64,
            "mapping_receipt": {
                "receipt_type": "htdy_s6_10_daily_mapping",
                "receipt_hash": "f" * 64,
            },
        },
        checkpoint_collector=lambda _session: {
            "trading_day": previous.isoformat(),
            "status": "passed",
            "authorization_hash": SHA,
        },
        source_facts_collector=lambda _session, _contract, _root: (
            "c" * 64
        ),
        runtime_identity_collector=lambda _root: (
            "d" * 40,
            "e" * 64,
        ),
    )

    assert facts["trading_day"] == target
    assert facts["previous_trading_day"] == previous
    assert facts["actual_contract"] == "JM2609"
    assert facts["mapping_receipt"]["receipt_hash"] == "f" * 64
    assert len(facts["expected_bucket_ends"]) == 23
    assert facts["window_end"] == "2026-08-03T15:00:00+08:00"


def test_daily_facts_wait_outside_confirmed_dce_session() -> None:
    from types import SimpleNamespace

    from app.services.htdy_s6_10_long_running_runtime_gate import (
        collect_long_running_daily_facts,
    )

    class Clock:
        def decision(self, **_kwargs):
            return SimpleNamespace(should_poll=False, trading_day=None)

    assert collect_long_running_daily_facts(
        object(),
        datetime(2026, 8, 2, 1, tzinfo=UTC),
        eod_authorization_hash=SHA,
        runtime_root=Path("/runtime"),
        clock_factory=lambda _session: Clock(),
    ) == {"gate_status": "waiting"}


def test_daily_facts_prepares_mapping_in_bounded_preopen_window() -> None:
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from app.services.htdy_s6_10_long_running_runtime_gate import (
        collect_long_running_daily_facts,
    )

    target = date(2026, 7, 30)
    previous = date(2026, 7, 29)
    next_open = datetime(2026, 7, 29, 21)

    class Clock:
        def decision(self, **_kwargs):
            return SimpleNamespace(
                should_poll=False,
                trading_day=None,
                next_open_at=next_open,
            )

        def _previous_trading_day(self, *_args):
            return previous

    calls: list[date] = []
    facts = collect_long_running_daily_facts(
        object(),
        datetime(
            2026,
            7,
            29,
            18,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        eod_authorization_hash=SHA,
        runtime_root=Path("/runtime"),
        clock_factory=lambda _session: Clock(),
        mapping_collector=lambda _session, day, allow_create: (
            calls.append((day, allow_create))
            or {
                "actual_contract": "JM2609",
                "mapping_sha256": "b" * 64,
                "mapping_receipt": {
                    "receipt_type": "htdy_s6_10_daily_mapping",
                    "receipt_hash": "f" * 64,
                },
            }
        ),
        checkpoint_collector=lambda _session: {
            "trading_day": previous.isoformat(),
            "status": "passed",
            "authorization_hash": SHA,
        },
        prepare_preopen_mapping=True,
        next_open_trading_day_resolver=lambda _clock, _open: target,
        preopen_first_session_validator=lambda *_args: True,
    )

    assert calls == [(target, True)]
    assert facts == {
        "gate_status": "mapping_prepared",
        "trading_day": target,
        "actual_contract": "JM2609",
        "mapping_sha256": "b" * 64,
        "mapping_receipt": {
            "receipt_type": "htdy_s6_10_daily_mapping",
            "receipt_hash": "f" * 64,
        },
    }


def test_daily_facts_does_not_prepare_during_intraday_break() -> None:
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from app.services.htdy_s6_10_long_running_runtime_gate import (
        collect_long_running_daily_facts,
    )

    target = date(2026, 7, 30)

    class Clock:
        def decision(self, **_kwargs):
            return SimpleNamespace(
                should_poll=False,
                trading_day=None,
                next_open_at=datetime(2026, 7, 30, 10, 30),
            )

    assert collect_long_running_daily_facts(
        object(),
        datetime(
            2026,
            7,
            30,
            10,
            20,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        eod_authorization_hash=SHA,
        runtime_root=Path("/runtime"),
        clock_factory=lambda _session: Clock(),
        mapping_collector=lambda *_args: pytest.fail(
            "intraday break must not materialize mapping"
        ),
        prepare_preopen_mapping=True,
        next_open_trading_day_resolver=lambda _clock, _open: target,
        preopen_first_session_validator=lambda *_args: False,
    ) == {"gate_status": "waiting"}


def test_daily_facts_active_session_never_creates_missing_mapping() -> None:
    from types import SimpleNamespace

    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
    )
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        collect_long_running_daily_facts,
    )

    target = date(2026, 7, 30)

    class Clock:
        def decision(self, **_kwargs):
            return SimpleNamespace(
                should_poll=True,
                trading_day=target,
            )

        def _previous_trading_day(self, *_args):
            return date(2026, 7, 29)

    calls: list[bool] = []

    def missing(_session, _day, allow_create):
        calls.append(allow_create)
        raise HtDyS610LongRunningError(
            "daily_mapping_receipt_missing"
        )

    with pytest.raises(
        HtDyS610LongRunningError,
        match="daily_mapping_receipt_missing",
    ):
        collect_long_running_daily_facts(
            object(),
            datetime(2026, 7, 29, 13, tzinfo=UTC),
            eod_authorization_hash=SHA,
            runtime_root=Path("/runtime"),
            clock_factory=lambda _session: Clock(),
            mapping_collector=missing,
            prepare_preopen_mapping=True,
        )

    assert calls == [False]


def test_next_open_resolver_maps_friday_night_to_monday_trading_day() -> None:
    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.data_center import TradingCalendar, TradingSession
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        _trading_day_for_next_open,
    )
    from app.services.trading_session_clock import TradingSessionClock

    monday = date(2026, 8, 3)
    friday_open = datetime(2026, 7, 31, 21)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        start = date(2026, 7, 30)
        for offset in range(7):
            day = start + timedelta(days=offset)
            session.add(
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=day,
                    is_trading_day=day.weekday() < 5,
                    has_night_session=day.weekday() < 5,
                    provider="fixture",
                )
            )
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="night",
                start_time=time(21),
                end_time=time(23),
                crosses_midnight=False,
                is_active=True,
                provider="fixture",
            )
        )
        session.commit()
        clock = TradingSessionClock(session)
        monday_windows = clock.windows_for_trading_day(
            monday,
            product="jm",
            exchange="DCE",
        )
        resolved = _trading_day_for_next_open(clock, friday_open)

    assert monday_windows[0].start == friday_open
    assert resolved == monday


def test_mapping_facts_accept_same_contract_version_supersession() -> None:
    """Break caught: treating two valid versions as conflicting mappings."""

    from types import SimpleNamespace

    from app.services.htdy_s6_10_long_running import canonical_hash
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        _collect_mapping_facts,
    )

    rows = [
        SimpleNamespace(
            id=10,
            instrument_symbol="jm",
            trade_date=date(2026, 7, 29),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="rqdata_structured_v1",
            created_at=datetime(2026, 7, 29, 5, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=20,
            instrument_symbol="jm",
            trade_date=date(2026, 7, 29),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="s607_reference_v1",
            created_at=datetime(2026, 7, 29, 9, tzinfo=UTC),
        ),
    ]

    class Session:
        def scalars(self, _query):
            return rows

    assert _collect_mapping_facts(
        Session(),
        date(2026, 7, 29),
    ) == {
        "actual_contract": "JM2609",
        "mapping_sha256": canonical_hash(
            {
                "trade_date": "2026-07-29",
                "contract_code": "JM2609",
                "normalized_contract_code": "JM2609",
                "rank": 1,
                "rule": "volume_open_interest",
                "provider": "rqdata",
                "data_version": "s607_reference_v1",
            }
        ),
    }


def test_mapping_facts_normalize_selected_actual_contract() -> None:
    """Break caught: long child diverging from snapshot contract normalization."""

    from types import SimpleNamespace

    from app.services.htdy_s6_10_long_running_runtime_gate import (
        _collect_mapping_facts,
    )

    row = SimpleNamespace(
        id=10,
        instrument_symbol="jm",
        trade_date=date(2026, 7, 29),
        rank=1,
        contract_code=" jm2609 ",
        rule="volume_open_interest",
        provider="rqdata",
        data_version="v1",
        created_at=datetime(2026, 7, 29, 5, tzinfo=UTC),
    )

    class Session:
        def scalars(self, _query):
            return [row]

    assert _collect_mapping_facts(
        Session(),
        date(2026, 7, 29),
    )["actual_contract"] == "JM2609"


def test_prepare_approval_d_cli_publishes_create_only_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import jm_htdy_s6_10_one_day_gate as cli

    parent = _parent()
    sample = _sample(parent)
    parent_path = tmp_path / "parent.json"
    sample_path = tmp_path / "acceptance.json"
    output_path = tmp_path / "approval-d-request.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "jm_htdy_s6_10_one_day_gate.py",
            "prepare-approval-d",
            "--parent",
            str(parent_path),
            "--acceptance-sample",
            str(sample_path),
            "--output",
            str(output_path),
        ],
    )

    assert cli.main() == 0
    request = json.loads(output_path.read_text(encoding="utf-8"))
    assert request["request_type"] == (
        "htdy_s6_10_approval_d_no_code_promotion"
    )
    assert request["eod_authorization_hash"] == SHA


def test_runtime_gate_builder_verifies_exact_no_code_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        build_approval_d_request,
    )
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        build_runtime_gate,
    )

    parent = _parent()
    request = build_approval_d_request(
        parent_packet=parent,
        acceptance_sample=_sample(parent),
        generated_at=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    paths = {}
    for name in ("receipt", "signature", "signers"):
        path = tmp_path / name
        path.write_text("{}\n", encoding="utf-8")
        paths[name] = path
    child_root = tmp_path / "children"
    runtime_root = tmp_path / "runtime"
    child_root.mkdir()
    runtime_root.mkdir()
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running_runtime_gate.verify_signed_approval_d_receipt",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running_runtime_gate._collect_runtime_identity",
        lambda _root: ("b" * 40, "c" * 64),
    )
    environ = {
        "GUIYI_HTDY_S610_APPROVAL_D_RECEIPT": str(paths["receipt"]),
        "GUIYI_HTDY_S610_APPROVAL_D_SIGNATURE": str(
            paths["signature"]
        ),
        "GUIYI_HTDY_S610_APPROVED_SIGNERS": str(paths["signers"]),
        "GUIYI_HTDY_S610_DAILY_CHILD_ROOT": str(child_root),
        "GUIYI_PROJECT_ROOT": str(runtime_root),
        "GUIYI_WECHAT_AUTOSEND_ENABLED": "false",
    }

    gate = build_runtime_gate(
        approval_packet_path=request_path,
        approval_hash="d" * 64,
        environ=environ,
    )
    assert gate(object(), phase="verify")["gate_status"] == "verified"

    monkeypatch.setattr(
        "app.services.htdy_s6_10_long_running_runtime_gate._collect_runtime_identity",
        lambda _root: ("e" * 40, "c" * 64),
    )
    with pytest.raises(
        HtDyS610LongRunningError,
        match="no_code_binding_drift",
    ):
        gate(object(), phase="verify")

    with pytest.raises(
        HtDyS610LongRunningError,
        match="global_wechat_autosend_must_remain_disabled",
    ):
        build_runtime_gate(
            approval_packet_path=request_path,
            approval_hash="d" * 64,
            environ={
                **environ,
                "GUIYI_WECHAT_AUTOSEND_ENABLED": "true",
            },
        )


def test_dispatcher_calls_long_running_gate_with_approval_packet_path() -> None:
    from scripts.jm_htdy_s6_10_one_day_dispatch import _build_gate

    observed: dict[str, object] = {}

    def builder(**kwargs):
        observed.update(kwargs)
        return object()

    packet = Path("/approval-d-request.json")
    _build_gate(
        builder=builder,
        is_long_running=True,
        packet_path=packet,
        approval_hash=SHA,
        environ={},
    )

    assert observed["approval_packet_path"] == packet
    assert "parent_packet_path" not in observed


def test_source_binding_payload_binds_1m_15m_provider_and_quality(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
        canonical_hash,
    )
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        _source_binding_payload,
    )

    profile = SimpleNamespace(
        profile_id="live_observation_v1",
        provider="rqdata",
        quality_policy="active_entry",
        contract_roles=["dominant_main", "actual_contract"],
        periods=["1m", "15m"],
        is_active=True,
    )

    def rows(
        *,
        provider_15m: str = "rqdata",
        quality_15m: str = "passed",
        role_15m: str = "actual_contract",
    ):
        result = []
        for index, period in enumerate(("1m", "15m"), start=1):
            file_path = tmp_path / f"{period}.parquet"
            file_path.write_bytes(f"source-{period}".encode())
            import hashlib

            checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
            binding = SimpleNamespace(
                id=index,
                binding_status="active",
                contract_role=(
                    role_15m if period == "15m" else "actual_contract"
                ),
                instrument_symbol="jm",
                contract_code="JM2609",
                period=period,
                data_version=f"v-{period}",
            )
            market_file = SimpleNamespace(
                id=index + 10,
                instrument_symbol="jm",
                contract_code="JM2609",
                period=period,
                provider=(
                    provider_15m if period == "15m" else "rqdata"
                ),
                data_type="bars",
                data_version=f"v-{period}",
                checksum=checksum,
                file_path=str(file_path),
                start_time=datetime(2026, 1, 1, tzinfo=UTC),
                end_time=datetime(2026, 8, 3, tzinfo=UTC),
                row_count=100,
                data_role="primary",
                quality_status=(
                    quality_15m if period == "15m" else "passed"
                ),
            )
            result.append((binding, market_file))
        return result

    rqdata_payload = _source_binding_payload(
        rows(),
        actual_contract="JM2609",
        profile=profile,
        project_root=tmp_path,
    )
    assert rqdata_payload[1]["provider"] == "rqdata"
    assert len(canonical_hash({"bindings": rqdata_payload})) == 64

    with pytest.raises(
        HtDyS610LongRunningError,
        match="active_source_binding_invalid",
    ):
        _source_binding_payload(
            rows(quality_15m="failed"),
            actual_contract="JM2609",
            profile=profile,
            project_root=tmp_path,
        )
    with pytest.raises(
        HtDyS610LongRunningError,
        match="active_source_binding_invalid",
    ):
        _source_binding_payload(
            rows(role_15m="dominant_main"),
            actual_contract="JM2609",
            profile=profile,
            project_root=tmp_path,
        )
    with pytest.raises(
        HtDyS610LongRunningError,
        match="active_source_binding_invalid",
    ):
        _source_binding_payload(
            rows(provider_15m="local_parquet"),
            actual_contract="JM2609",
            profile=profile,
            project_root=tmp_path,
        )
