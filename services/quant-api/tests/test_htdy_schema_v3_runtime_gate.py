from __future__ import annotations

from datetime import UTC, date, datetime
import json

import pytest

from app.services.htdy_s6_08_schema_v3 import build_parent_authorization


COUNTS = {
    "strategy_signals": 10,
    "signal_events": 20,
    "signal_notifications": 0,
    "signal_scan_tasks": 0,
    "orders": 0,
    "trades": 0,
    "review_notes": 2,
    "backtest_tasks": 3,
    "profile_bindings": 4,
    "canonical_assets": 5,
}
HASHES = {
    "backtest_state_sha256": "a" * 64,
    "profile_bindings_sha256": "b" * 64,
    "canonical_assets_sha256": "c" * 64,
    "forbidden_tables_sha256": "d" * 64,
}
SOURCE_FACTS = {
    "profile_sha256": "1" * 64,
    "source_sha256": "2" * 64,
    "policy_sha256": "3" * 64,
    "runtime_heartbeat_sha256": "4" * 64,
    "autosend_enabled": False,
}


def _bindings(tmp_path):
    return {
        "deployment_packet_sha256": "1" * 64,
        "s6_07_rebind_packet_sha256": "2" * 64,
        "s6_07_final_receipt": {
            "path": str(tmp_path / "completion_receipt.json"),
            "sha256": "3" * 64,
        },
        "service_bundle_sha256": "4" * 64,
        "runtime": {
            "root": str(tmp_path / "runtime"),
            "commit": "5" * 40,
            "tree_sha256": "6" * 64,
            "tracked_clean": True,
        },
        "database_revision": "20260721_0025",
        "actual_contract_resolver_sha256": "7" * 64,
        "profile": {
            "profile_id": "live_observation_v1",
            "market_data_file_id": 7,
            "data_version": "jm-live-v1",
            "checksum": "8" * 64,
        },
        "source_sha256": "9" * 64,
        "policy_sha256": "a" * 64,
        "writer_sha256": "b" * 64,
        "web": {
            "source_sha256": "c" * 64,
            "bundle_sha256": "d" * 64,
        },
        "feature_flags": {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        },
        "baseline": {"counts": COUNTS, "hashes": HASHES},
        "output": {
            "root": str(tmp_path),
            "device": tmp_path.stat().st_dev,
            "mount": str(tmp_path),
        },
        "launchd": {
            "label": "com.guiyi.quant-runtime-scheduler",
            "plist_sha256": "e" * 64,
        },
        "no_migration": True,
    }


def _state(*, events=None, counts=None):
    return {
        "trading_day": date(2026, 7, 27),
        "actual_contract": "JM2609",
        "mapping_sha256": "f" * 64,
        "source_facts": SOURCE_FACTS,
        "counts": counts or COUNTS,
        "hashes": HASHES,
        "events": list(events or []),
    }


def _event():
    return {
        "id": 31,
        "event_key": "signal_created:htdy:one",
        "event_type": "signal_created",
        "source_mode": "live_realtime_repainting",
        "strategy_name": "htdy_original_realtime_first_seen",
        "strategy_version": "v1.0",
        "product": "jm",
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-27",
        "period": "15m",
        "direction": "long",
        "payload": {
            "formal_lineage": {
                "schema_version": "signal_review_lineage_v2",
                "live_detection_snapshot": {
                    "observation_key": "observation-key-1",
                },
                "indicator": {
                    "indicator_code": "huotian_dayou_original_v0",
                    "indicator_version": "original-v0",
                    "signal_policy": "htdy_original_xma_15m_first_seen_v1",
                    "future_looking": True,
                    "repainting_accepted": True,
                    "first_seen_no_retraction": True,
                    "historical_backtest_allowed": False,
                    "live_confirmed_required": False,
                    "partial_allowed": True,
                    "confirmed_allowed": True,
                    "notification_ready": False,
                    "auto_order": False,
                },
            }
        },
    }


def test_runtime_gate_creates_daily_child_and_consumes_after_one_probe(
    tmp_path,
) -> None:
    from app.services.htdy_s6_08_runtime_gate import HtDySchemaV3RuntimeGate

    bindings = _bindings(tmp_path)
    parent = build_parent_authorization(
        trading_days=[date(2026, 7, 27)],
        bindings=bindings,
    )
    parent_path = tmp_path / "service_parent_packet.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    after_counts = {
        **COUNTS,
        "strategy_signals": 11,
        "signal_events": 21,
    }
    states = [
        _state(),
        _state(events=[_event()], counts=after_counts),
    ]
    gate = HtDySchemaV3RuntimeGate(
        parent_packet_path=parent_path,
        approval_hash=parent["packet_hash"],
        current_bindings=lambda session: bindings,
        current_daily_state=lambda session, trading_day: states.pop(0),
        handler_factory=lambda session: "handler",
        now=lambda: datetime(2026, 7, 27, 1, 5, tzinfo=UTC),
    )

    assert gate(object(), phase="pre_write")["signal_event_handler"] == "handler"
    assert (
        tmp_path / "daily" / "2026-07-27" / "child_packet.json"
    ).is_file()
    gate(
        object(),
        phase="post_write",
        result={
            "trading_day": "2026-07-27",
            "signal_events": {
                "created": 1,
                "changed": 0,
                "unchanged": 0,
                "blocked": 0,
                "event_ids": [31],
            },
        },
    )
    gate(object(), phase="after_commit")

    states.extend(
        [
            _state(events=[_event()], counts=after_counts),
            _state(events=[_event()], counts=after_counts),
        ]
    )
    assert gate(object(), phase="pre_write")["gate_mode"] == "idempotency_probe"
    gate(
        object(),
        phase="post_write",
        result={
            "trading_day": "2026-07-27",
            "signal_events": {
                "created": 0,
                "changed": 0,
                "unchanged": 1,
                "blocked": 0,
                "event_ids": [31],
            },
        },
    )
    gate(object(), phase="after_commit")

    with pytest.raises(RuntimeError, match="authorization_consumed"):
        gate(object(), phase="pre_write")


def test_runtime_gate_rejects_schema_v2_before_collecting_facts(
    tmp_path,
) -> None:
    from app.services.htdy_s6_08_runtime_gate import HtDySchemaV3RuntimeGate

    packet = tmp_path / "service_parent_packet.json"
    packet.write_text(
        json.dumps({"schema_version": 2, "packet_hash": "a" * 64}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="schema_version_invalid"):
        HtDySchemaV3RuntimeGate(
            parent_packet_path=packet,
            approval_hash="a" * 64,
            current_bindings=lambda session: (_ for _ in ()).throw(
                AssertionError("must not collect")
            ),
            current_daily_state=lambda session, trading_day: {},
            handler_factory=lambda session: object(),
        )
