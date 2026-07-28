from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.htdy_s6_10_stability import (
    HtDyS610Error,
    HtDyS610Ledger,
    HtDyS610Observer,
    build_daily_child,
    build_parent_packet,
    canonical_hash,
    verify_daily_child,
    verify_ledger,
    verify_approval_c_bundle,
    verify_parent_packet,
)
from app.services.htdy_s6_10_runtime_gate import HtDyS610RuntimeGate
from app.services.htdy_s6_10_faults import (
    HtDyS610FaultExecutor,
    verify_fault_receipts,
)
from app.services.htdy_s6_10_runtime_support import _verify_exact_events


SHA = "a" * 64
WINDOW = (
    date(2026, 8, 3),
    date(2026, 8, 4),
    date(2026, 8, 5),
    date(2026, 8, 6),
    date(2026, 8, 7),
)


def _bindings() -> dict[str, object]:
    return {
        "runtime_commit": "b" * 40,
        "runtime_tree": SHA,
        "runtime_tracked_clean": True,
        "source_commit": "c" * 40,
        "source_tree": SHA,
        "database_revision": "20260721_0025",
        "profile_sha256": SHA,
        "indicator_source_sha256": SHA,
        "policy_sha256": SHA,
        "s6_07_receipt_sha256": SHA,
        "s6_08_receipt_sha256": SHA,
        "s6_09_receipt_sha256": SHA,
        "backup_receipt_sha256": SHA,
        "restore_receipt_sha256": SHA,
        "restore_audit_receipt_sha256": SHA,
        "calendar_sha256": SHA,
        "launchd_sha256": SHA,
        "observer_launchd_sha256": SHA,
        "deployment_packet_sha256": SHA,
        "s6_07_rebind_packet_sha256": SHA,
        "s6_07_enable_packet_sha256": SHA,
        "fault_schedule_sha256": SHA,
        "approval_c_approved_signers_sha256": SHA,
        "feature_flags": {
            "live_runtime": True,
            "signal_events": False,
            "wechat_autosend": False,
            "after_market_automation": False,
        },
        "baseline_counts": {
            "signal_events": 4,
            "signal_notifications": 2,
            "review_notes": 0,
            "orders": 0,
            "trades": 0,
        },
        "baseline_hashes": {
            "profile_bindings": SHA,
            "canonical_assets": SHA,
            "forbidden_tables": SHA,
        },
        "baseline_max_ids": {
            "signal_events": 4,
            "signal_notifications": 2,
            "review_notes": 0,
            "orders": 0,
            "trades": 0,
        },
    }


def _parent() -> dict[str, object]:
    return build_parent_packet(
        trading_days=WINDOW,
        generated_at=datetime(2026, 7, 31, 8, tzinfo=UTC),
        bindings=_bindings(),
        calendar_rows=[
            {
                "trade_date": day.isoformat(),
                "is_trading_day": True,
                "night_session_date": (
                    WINDOW[index - 1] if index else date(2026, 7, 31)
                ).isoformat(),
            }
            for index, day in enumerate(WINDOW)
        ],
        fault_schedule=_fault_schedule(),
    )


def _fault_schedule() -> dict[str, list[dict[str, object]]]:
    def item(
        fault: str,
        day: int,
        hour: int,
        *,
        target_ip: str | None = None,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "fault": fault,
            "slot_start": (
                f"2026-08-{day:02d}T{hour:02d}:00:00+08:00"
            ),
            "slot_end": (
                f"2026-08-{day:02d}T{hour:02d}:10:00+08:00"
            ),
            "max_duration_seconds": 60,
        }
        if target_ip is not None:
            value["target_ip"] = target_ip
        return value

    return {
        "D1": [
            item("live_scheduler", 3, 10),
            item("api", 3, 10),
            item("web", 3, 14),
        ],
        "D2": [item("redis", 4, 10)],
        "D3": [item("postgres", 5, 10)],
        "D4": [
            item("rqdata", 6, 10, target_ip="203.0.113.8"),
            item("eod_scheduler", 6, 16),
        ],
        "D4_D5": [item("mac_reboot", 6, 18)],
    }


def test_parent_packet_freezes_exact_s610_contract_and_rejects_drift() -> None:
    parent = _parent()
    assert parent["schema_version"] == 4
    assert parent["packet_type"] == "htdy_s6_10_five_day_parent"
    assert parent["max_event_count"] == 160
    assert parent["theoretical_observation_bar_limit"] == 142
    assert parent["notification_baseline"] == 2
    assert parent["packet_hash"] == canonical_hash(parent)
    verify_parent_packet(
        parent,
        approval_hash=str(parent["packet_hash"]),
        current_bindings=_bindings(),
        now=datetime(2026, 7, 31, 9, tzinfo=UTC),
    )

    drift = _bindings()
    drift["database_revision"] = "20260721_0024"
    with pytest.raises(HtDyS610Error, match="parent_bindings_drift"):
        verify_parent_packet(
            parent,
            approval_hash=str(parent["packet_hash"]),
            current_bindings=drift,
            now=datetime(2026, 7, 31, 9, tzinfo=UTC),
        )

    legacy = deepcopy(parent)
    legacy["schema_version"] = 3
    legacy["packet_hash"] = canonical_hash(legacy)
    with pytest.raises(HtDyS610Error, match="schema_version_invalid"):
        verify_parent_packet(
            legacy,
            approval_hash=str(legacy["packet_hash"]),
            current_bindings=_bindings(),
            now=datetime(2026, 7, 31, 9, tzinfo=UTC),
        )


def test_parent_rejects_started_window_and_invalid_calendar() -> None:
    with pytest.raises(HtDyS610Error, match="window_not_five_days"):
        build_parent_packet(
            trading_days=WINDOW[:4],
            generated_at=datetime(2026, 8, 2, tzinfo=UTC),
            bindings=_bindings(),
            calendar_rows=[],
            fault_schedule={},
        )
    with pytest.raises(HtDyS610Error, match="window_already_started"):
        build_parent_packet(
            trading_days=WINDOW,
            generated_at=datetime(2026, 8, 3, 13, 1, tzinfo=UTC),
            bindings=_bindings(),
            calendar_rows=[
                {
                    "trade_date": day.isoformat(),
                    "is_trading_day": True,
                    "night_session_date": (
                        WINDOW[index - 1]
                        if index
                        else date(2026, 7, 31)
                    ).isoformat(),
                }
                for index, day in enumerate(WINDOW)
            ],
            fault_schedule=_fault_schedule(),
        )


def test_daily_child_binds_mapping_beginning_state_and_previous_seal() -> None:
    parent = _parent()
    beginning = {
        "counts": _bindings()["baseline_counts"],
        "hashes": _bindings()["baseline_hashes"],
        "notification_count": 2,
    }
    child = build_daily_child(
        parent_packet=parent,
        parent_approval_hash=str(parent["packet_hash"]),
        trading_day=WINDOW[1],
        actual_contract="JM2609",
        mapping_sha256=SHA,
        session_geometry_sha256=SHA,
        source_facts_sha256=SHA,
        beginning_state=beginning,
        previous_daily_seal_sha256=SHA,
    )
    verify_daily_child(
        child,
        approval_hash=str(child["packet_hash"]),
        parent_packet=parent,
        current_actual_contract="JM2609",
        current_mapping_sha256=SHA,
        current_session_geometry_sha256=SHA,
        current_source_facts_sha256=SHA,
        current_beginning_state=beginning,
        current_previous_daily_seal_sha256=SHA,
    )
    with pytest.raises(HtDyS610Error, match="daily_child_drift"):
        verify_daily_child(
            child,
            approval_hash=str(child["packet_hash"]),
            parent_packet=parent,
            current_actual_contract="JM2701",
            current_mapping_sha256=SHA,
            current_session_geometry_sha256=SHA,
            current_source_facts_sha256=SHA,
            current_beginning_state=beginning,
            current_previous_daily_seal_sha256=SHA,
        )


def test_ledger_is_create_only_hash_chained_and_tamper_evident(
    tmp_path: Path,
) -> None:
    ledger = HtDyS610Ledger(
        root=tmp_path,
        parent_packet_hash=SHA,
    )
    first = ledger.append_sample(
        trading_day=WINDOW[0],
        sampled_at=datetime(2026, 8, 3, 13, 2, tzinfo=UTC),
        payload={"heartbeat": "ok", "notification_count": 2},
    )
    second = ledger.append_sample(
        trading_day=WINDOW[0],
        sampled_at=datetime(2026, 8, 3, 13, 3, tzinfo=UTC),
        payload={"heartbeat": "ok", "notification_count": 2},
    )
    assert first["sequence"] == 1
    assert second["previous_sample_sha256"] == first["sample_hash"]
    seal = ledger.seal_day(
        trading_day=WINDOW[0],
        status="failed",
        summary={"sample_count": 2},
    )
    assert seal["last_sample_sha256"] == second["sample_hash"]
    verify_ledger(tmp_path, parent_packet_hash=SHA)

    sample_path = sorted((tmp_path / "daily" / WINDOW[0].isoformat() / "samples").iterdir())[0]
    mutated = json.loads(sample_path.read_text(encoding="utf-8"))
    mutated["payload"]["heartbeat"] = "forged"
    sample_path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(HtDyS610Error, match="ledger_sample_hash_invalid"):
        verify_ledger(tmp_path, parent_packet_hash=SHA)


def test_ledger_rejects_missing_sample_and_chains_daily_seals(
    tmp_path: Path,
) -> None:
    ledger = HtDyS610Ledger(root=tmp_path, parent_packet_hash=SHA)
    first = ledger.append_sample(
        trading_day=WINDOW[0],
        sampled_at=datetime(2026, 8, 3, 1, tzinfo=UTC),
        payload={"status": "ok"},
    )
    seal = ledger.seal_day(
        trading_day=WINDOW[0],
        status="failed",
        summary={"sample_count": 1},
    )
    second_day = ledger.append_sample(
        trading_day=WINDOW[1],
        sampled_at=datetime(2026, 8, 4, 1, tzinfo=UTC),
        payload={"status": "ok"},
    )
    assert first["previous_daily_seal_sha256"] is None
    assert second_day["previous_daily_seal_sha256"] == seal["seal_hash"]
    sample_path = next(
        (tmp_path / "daily" / WINDOW[0].isoformat() / "samples").glob("*.json")
    )
    mutated = json.loads(sample_path.read_text(encoding="utf-8"))
    mutated["payload"]["status"] = "forged"
    sample_path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(HtDyS610Error, match="ledger_sample_hash_invalid"):
        ledger.append_sample(
            trading_day=WINDOW[1],
            sampled_at=datetime(2026, 8, 4, 1, 2, tzinfo=UTC),
            payload={"status": "ok"},
        )


def test_passed_daily_seal_requires_full_jm_session_coverage(
    tmp_path: Path,
) -> None:
    ledger = HtDyS610Ledger(root=tmp_path, parent_packet_hash=SHA)
    shanghai = ZoneInfo("Asia/Shanghai")
    windows = (
        (
            datetime.combine(date(2026, 7, 31), time(21), shanghai),
            datetime.combine(date(2026, 7, 31), time(23), shanghai),
        ),
        (
            datetime.combine(WINDOW[0], time(9), shanghai),
            datetime.combine(WINDOW[0], time(10, 15), shanghai),
        ),
        (
            datetime.combine(WINDOW[0], time(10, 30), shanghai),
            datetime.combine(WINDOW[0], time(11, 30), shanghai),
        ),
        (
            datetime.combine(WINDOW[0], time(13, 30), shanghai),
            datetime.combine(WINDOW[0], time(15), shanghai),
        ),
    )
    for start, end in windows:
        cursor = start
        while cursor <= end:
            ledger.append_sample(
                trading_day=WINDOW[0],
                sampled_at=cursor,
                payload={"status": "ok"},
            )
            cursor += timedelta(seconds=60)
    ledger.seal_day(
        trading_day=WINDOW[0],
        status="passed",
        summary={"coverage": "complete"},
        sealed_at=datetime.combine(
            WINDOW[0],
            time(15, 1),
            shanghai,
        ),
    )
    verify_ledger(
        tmp_path,
        parent_packet_hash=SHA,
        expected_trading_days=(WINDOW[0],),
        require_passed_seals=True,
    )


def test_approval_c_bundle_rechecks_every_bound_artifact(
    tmp_path: Path,
) -> None:
    parent = _parent()
    artifact_paths: dict[str, str] = {}
    packet_keys = (
        "deployment_packet",
        "s6_07_rebind_packet",
        "s6_07_enable_packet",
    )
    for key in packet_keys:
        path = tmp_path / f"{key}.json"
        payload = {"packet_hash": SHA}
        path.write_text(json.dumps(payload), encoding="utf-8")
        artifact_paths[key] = str(path)
    for key in ("observer_launchd", "fault_schedule_json"):
        path = tmp_path / key
        path.write_text("frozen\n", encoding="utf-8")
        artifact_paths[key] = str(path)
    signers = tmp_path / "approved_signers"
    signers.write_text("guiyi-owner ssh-ed25519 test\n", encoding="utf-8")
    artifact_paths["approval_c_approved_signers"] = str(signers)
    parent["bindings"]["artifact_paths"] = artifact_paths
    import hashlib

    parent["bindings"]["approval_c_approved_signers_sha256"] = hashlib.sha256(
        signers.read_bytes()
    ).hexdigest()
    parent["packet_hash"] = canonical_hash(parent)
    parent_path = tmp_path / "service_parent_packet.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    bundle = {
        "schema_version": 1,
        "task_id": "JM-LIVE-STABILITY-S6-10",
        "parent_packet_path": str(parent_path),
        "parent_packet_hash": parent["packet_hash"],
        "approval_challenge": "challenge",
    }
    for key in packet_keys:
        path = Path(artifact_paths[key])
        bundle[key] = {
            "path": str(path),
            "packet_hash": SHA,
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    for bundle_key, path_key in (
        ("observer_launchd", "observer_launchd"),
        ("fault_schedule", "fault_schedule_json"),
    ):
        path = Path(artifact_paths[path_key])
        bundle[bundle_key] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    bundle["bundle_hash"] = canonical_hash(bundle)
    bundle_path = tmp_path / "approval_c_bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "status": "approved",
        "task_id": "JM-LIVE-STABILITY-S6-10",
        "bundle_hash": bundle["bundle_hash"],
        "parent_packet_hash": parent["packet_hash"],
        "approval_challenge": "challenge",
        "approved_at": "2026-07-31T09:00:00+08:00",
        "authorizations": {
            "deployment": True,
            "s6_07_rebind_and_enable": True,
            "calendar_window": True,
            "five_day_runtime": True,
            "fault_matrix": True,
        },
    }
    receipt_path = tmp_path / "approval_c_receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    signature_path = tmp_path / "approval_c_receipt.sig"
    signature_path.write_text("signature", encoding="utf-8")
    verify_approval_c_bundle(
        bundle_path,
        approval_c_hash=str(bundle["bundle_hash"]),
        parent_packet=parent,
        parent_packet_path=parent_path,
        approval_receipt_path=receipt_path,
        approval_signature_path=signature_path,
        approved_signers_path=signers,
        signature_verifier=lambda *_args: True,
        trust_root_verifier=lambda _path: True,
    )
    with pytest.raises(HtDyS610Error, match="approval_c_signature_invalid"):
        verify_approval_c_bundle(
            bundle_path,
            approval_c_hash=str(bundle["bundle_hash"]),
            parent_packet=parent,
            parent_packet_path=parent_path,
            approval_receipt_path=receipt_path,
            approval_signature_path=signature_path,
            approved_signers_path=signers,
            signature_verifier=lambda *_args: False,
            trust_root_verifier=lambda _path: True,
        )
    Path(artifact_paths["s6_07_enable_packet"]).write_text(
        '{"packet_hash":"' + "b" * 64 + '"}',
        encoding="utf-8",
    )
    with pytest.raises(HtDyS610Error, match="approval_c_artifact_drift"):
        verify_approval_c_bundle(
            bundle_path,
            approval_c_hash=str(bundle["bundle_hash"]),
            parent_packet=parent,
            parent_packet_path=parent_path,
            approval_receipt_path=receipt_path,
            approval_signature_path=signature_path,
            approved_signers_path=signers,
            signature_verifier=lambda *_args: True,
            trust_root_verifier=lambda _path: True,
        )


def test_observer_sample_is_read_only_and_enforces_forbidden_baselines() -> None:
    calls: list[str] = []

    def collect() -> dict[str, object]:
        calls.append("collect")
        return {
            "runtime": {"heartbeat": "ok"},
            "mapping": {"actual_contract": "JM2609"},
            "live": {"minute_count": 10, "snapshot_sha256": SHA},
            "htdy": {
                "candidate_count": 1,
                "created": 0,
                "unchanged": 1,
                "changed": 0,
                "blocked": 0,
            },
            "eod": {"status": "pending"},
            "counts": {
                "signal_events": 4,
                "signal_notifications": 2,
                "review_notes": 0,
                "orders": 0,
                "trades": 0,
            },
            "hashes": {
                "profile_bindings": SHA,
                "canonical_assets": SHA,
                "forbidden_tables": SHA,
            },
            "new_events": [],
        }

    observer = HtDyS610Observer(
        collector=collect,
        baseline_counts=_bindings()["baseline_counts"],
        baseline_hashes=_bindings()["baseline_hashes"],
        max_event_count=160,
    )
    sample = observer.sample()
    assert sample["status"] == "ok"
    assert sample["readonly"] is True
    assert calls == ["collect"]

    def notification_drift() -> dict[str, object]:
        result = deepcopy(collect())
        result["counts"]["signal_notifications"] = 3
        return result

    observer = HtDyS610Observer(
        collector=notification_drift,
        baseline_counts=_bindings()["baseline_counts"],
        baseline_hashes=_bindings()["baseline_hashes"],
        max_event_count=160,
    )
    with pytest.raises(HtDyS610Error, match="notification_count_drift"):
        observer.sample()

    def non_exact_event() -> dict[str, object]:
        result = deepcopy(collect())
        result["counts"]["signal_events"] = 5
        result["new_events"] = [
            {
                "id": 5,
                "event_type": "signal_created",
                "source_mode": "live_confirmed",
                "strategy_name": "other",
                "strategy_version": "v1",
                "product": "jm",
                "period": "15m",
            }
        ]
        return result

    observer = HtDyS610Observer(
        collector=non_exact_event,
        baseline_counts=_bindings()["baseline_counts"],
        baseline_hashes=_bindings()["baseline_hashes"],
        max_event_count=160,
    )
    with pytest.raises(HtDyS610Error, match="non_exact_event_forbidden"):
        observer.sample()


def test_runtime_gate_allows_multiple_days_but_never_notification_or_change(
    tmp_path: Path,
) -> None:
    parent = _parent()
    packet_path = tmp_path / "service_parent_packet.json"
    packet_path.write_text(json.dumps(parent), encoding="utf-8")
    state = {
        "trading_day": WINDOW[0],
        "actual_contract": "JM2609",
        "mapping_sha256": SHA,
        "session_geometry_sha256": SHA,
        "source_facts_sha256": SHA,
        "beginning_state": {
            "counts": _bindings()["baseline_counts"],
            "hashes": _bindings()["baseline_hashes"],
            "notification_count": 2,
        },
        "counts": _bindings()["baseline_counts"],
        "hashes": _bindings()["baseline_hashes"],
        "new_events": [],
        "event_ids": [],
    }
    gate = HtDyS610RuntimeGate(
        parent_packet_path=packet_path,
        approval_hash=str(parent["packet_hash"]),
        current_bindings=lambda _session: _bindings(),
        current_daily_state=lambda _session, _day: state,
        handler_factory=lambda _session: "handler",
        trading_day_resolver=lambda _session, _now, _packet: WINDOW[0],
        now=lambda: datetime(2026, 8, 3, 2, tzinfo=UTC),
    )
    assert gate(None, phase="verify")["gate_status"] == "verified"
    pre = gate(None, phase="pre_write")
    assert pre["signal_event_handler"] == "handler"
    assert pre["target_trading_day"] == WINDOW[0].isoformat()
    post = gate(
        None,
        phase="post_write",
        result={
            "signal_events": {
                "created": 0,
                "unchanged": 1,
                "changed": 0,
                "blocked": 0,
            }
        },
    )
    assert post["gate_status"] == "authorized"

    with pytest.raises(HtDyS610Error, match="signal_changed_forbidden"):
        gate(
            None,
            phase="post_write",
            result={
                "signal_events": {
                    "created": 0,
                    "unchanged": 0,
                    "changed": 1,
                    "blocked": 0,
                }
            },
        )


def test_runtime_gate_waits_without_handler_before_first_night_session(
    tmp_path: Path,
) -> None:
    parent = _parent()
    packet_path = tmp_path / "service_parent_packet.json"
    packet_path.write_text(json.dumps(parent), encoding="utf-8")
    gate = HtDyS610RuntimeGate(
        parent_packet_path=packet_path,
        approval_hash=str(parent["packet_hash"]),
        current_bindings=lambda _session: _bindings(),
        current_daily_state=lambda _session, _day: pytest.fail(
            "daily state must not be collected before the window"
        ),
        handler_factory=lambda _session: pytest.fail(
            "handler must not be created before the window"
        ),
        trading_day_resolver=lambda _session, _now, _packet: pytest.fail(
            "trading day must not be resolved before the window"
        ),
        now=lambda: datetime(2026, 7, 31, 12, tzinfo=UTC),
    )

    pre = gate(None, phase="pre_write")

    assert pre["gate_status"] == "waiting"
    assert pre["authorization_hash"] == parent["packet_hash"]
    assert pre["target_trading_day"] is None
    assert "signal_event_handler" not in pre


def test_runtime_scheduler_routes_schema_v4_without_accepting_schema_v3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import runtime_scheduler
    from app.services import htdy_s6_10_runtime_gate

    parent = _parent()
    packet_path = tmp_path / "parent.json"
    packet_path.write_text(json.dumps(parent), encoding="utf-8")
    sentinel = object()
    monkeypatch.setattr(
        htdy_s6_10_runtime_gate,
        "build_runtime_gate",
        lambda **_kwargs: sentinel,
    )
    assert (
        runtime_scheduler._build_signal_gate(
            approval_packet=packet_path,
            approval_hash=str(parent["packet_hash"]),
            environ={},
        )
        is sentinel
    )

    legacy = deepcopy(parent)
    legacy["schema_version"] = 3
    legacy["packet_type"] = "htdy_s6_08_bounded_parent"
    legacy["packet_hash"] = canonical_hash(legacy)
    packet_path.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(HtDyS610Error, match="legacy_packet_not_s610"):
        runtime_scheduler._build_signal_gate(
            approval_packet=packet_path,
            approval_hash=str(legacy["packet_hash"]),
            environ={"GUIYI_HTDY_S610_REQUIRED": "true"},
        )


def test_fault_executor_restores_dependency_in_finally(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []

    class Adapter:
        def boot_uuid(self) -> str:
            return "boot-a"

        def start_watchdog(
            self,
            *,
            fault: str,
            duration_seconds: int,
            target_ip: str | None,
            evidence_root: Path,
            parent_packet_hash: str,
        ) -> dict[str, object]:
            del duration_seconds, target_ip, evidence_root, parent_packet_hash
            calls.append(("watchdog", fault))
            return {"status": "armed"}

        def safety_facts(self) -> dict[str, object]:
            return {
                "notification_worker_loaded": False,
                "signal_notifications": 2,
                "wechat_attempt_total": 1,
            }

        def stop(self, fault: str) -> None:
            calls.append(("stop", fault))

        def start(self, fault: str) -> None:
            calls.append(("start", fault))

        def kickstart(self, fault: str) -> None:
            calls.append(("kickstart", fault))

        def block_ip(self, target_ip: str) -> None:
            calls.append(("block", target_ip))

        def unblock_ip(self, target_ip: str) -> None:
            calls.append(("unblock", target_ip))

        def healthy(self, fault: str) -> bool:
            calls.append(("healthy", fault))
            return True

        def reboot(self) -> None:
            calls.append(("reboot", "mac"))

    executor = HtDyS610FaultExecutor(
        adapter=Adapter(),
        sleeper=lambda _seconds: (_ for _ in ()).throw(
            RuntimeError("probe interruption")
        ),
        evidence_root=tmp_path,
        parent_packet_hash=SHA,
    )
    with pytest.raises(RuntimeError, match="probe interruption"):
        executor.execute(
            fault="redis",
            duration_seconds=30,
            target_ip=None,
        )
    assert calls == [
        ("watchdog", "redis"),
        ("stop", "redis"),
        ("start", "redis"),
        ("healthy", "redis"),
    ]


def test_fault_executor_records_recovered_fault_create_only(
    tmp_path: Path,
) -> None:
    class Adapter:
        def boot_uuid(self) -> str:
            return "boot-a"

        def start_watchdog(self, **_kwargs: object) -> dict[str, object]:
            return {"status": "armed"}

        def safety_facts(self) -> dict[str, object]:
            return {
                "notification_worker_loaded": False,
                "signal_notifications": 2,
                "wechat_attempt_total": 1,
            }

        def stop(self, _fault: str) -> None:
            return None

        def start(self, _fault: str) -> None:
            return None

        def kickstart(self, _fault: str) -> None:
            return None

        def block_ip(self, _target_ip: str) -> None:
            return None

        def unblock_ip(self, _target_ip: str) -> None:
            return None

        def healthy(self, _fault: str) -> bool:
            return True

        def reboot(self) -> None:
            return None

    executor = HtDyS610FaultExecutor(
        adapter=Adapter(),
        sleeper=lambda _seconds: None,
        evidence_root=tmp_path,
        parent_packet_hash=SHA,
    )
    receipt = executor.execute(
        fault="postgres",
        duration_seconds=60,
        target_ip=None,
    )
    assert receipt["status"] == "recovered"
    assert receipt["fault"] == "postgres"
    assert len(list((tmp_path / "faults").glob("postgres-*.json"))) == 1


def test_final_fault_verifier_requires_exact_matrix(
    tmp_path: Path,
) -> None:
    faults = {
        "live_scheduler",
        "api",
        "web",
        "redis",
        "postgres",
        "rqdata",
        "eod_scheduler",
        "mac_reboot",
    }
    root = tmp_path / "faults"
    root.mkdir()
    for fault in faults:
        payload = {
            "status": "recovered",
            "fault": fault,
            "parent_packet_hash": SHA,
            "safety_before": {
                "notification_worker_loaded": False,
                "signal_notifications": 2,
                "wechat_attempt_total": 1,
            },
            "safety_after": {
                "notification_worker_loaded": False,
                "signal_notifications": 2,
                "wechat_attempt_total": 1,
            },
                "watchdog": (
                    {
                        "status": "armed",
                        "pid": 1,
                        "ack_path": str(
                            root / f"{fault}-watchdog-1.armed.json"
                        ),
                    }
                    if fault in {"redis", "postgres", "rqdata"}
                    else {"status": "reboot_two_phase"}
                    if fault == "mac_reboot"
                    else {"status": "not_required"}
                ),
            }
        if fault in {"redis", "postgres", "rqdata"}:
            ack = root / f"{fault}-watchdog-1.armed.json"
            ack.write_text(
                json.dumps(
                    {
                        "status": "armed",
                        "fault": fault,
                        "parent_packet_hash": SHA,
                        "pid": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            import hashlib

            cleanup = {
                "status": "cleanup_completed",
                "fault": fault,
                "parent_packet_hash": SHA,
                "pid": 1,
                "ack_sha256": hashlib.sha256(ack.read_bytes()).hexdigest(),
            }
            cleanup["receipt_hash"] = canonical_hash(cleanup)
            (root / f"{fault}-watchdog-1.receipt.json").write_text(
                json.dumps(cleanup),
                encoding="utf-8",
            )
        payload["receipt_hash"] = canonical_hash(payload)
        (root / f"{fault}-{payload['receipt_hash'][:12]}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
    assert verify_fault_receipts(tmp_path, parent_packet_hash=SHA) == faults
    next(
        path
        for path in root.glob("redis-*.json")
        if "-watchdog-" not in path.name
    ).unlink()
    with pytest.raises(HtDyS610Error, match="fault_receipt_matrix_incomplete"):
        verify_fault_receipts(tmp_path, parent_packet_hash=SHA)


def test_runtime_binding_normalization_accepts_only_exact_new_events() -> None:
    exact = SimpleNamespace(
        event_type="signal_created",
        source_mode="live_realtime_repainting",
        strategy_name="htdy_original_realtime_first_seen",
        strategy_version="v1.0",
        product="jm",
        period="15m",
        direction="long",
        actual_contract="JM2609",
        dominant_mapping_date=WINDOW[0],
        payload={
            "formal_lineage": {
                "schema_version": "signal_review_lineage_v2",
                "indicator": {
                    "indicator_code": "huotian_dayou_original_v0",
                    "indicator_version": "original-v0",
                    "signal_policy": "htdy_original_xma_15m_first_seen_v1",
                    "future_looking": True,
                    "repainting_accepted": True,
                    "first_seen_no_retraction": True,
                    "historical_backtest_allowed": False,
                },
                "live_detection_snapshot": {
                    "source_sha256": SHA,
                    "policy_sha256": SHA,
                },
            }
        },
    )
    _verify_exact_events([exact])
    with pytest.raises(HtDyS610Error, match="non_exact_event_forbidden"):
        _verify_exact_events(
            [SimpleNamespace(**{**vars(exact), "period": "5m"})]
        )
    with pytest.raises(HtDyS610Error, match="signal_event_limit_exceeded"):
        _verify_exact_events([exact] * 161)
