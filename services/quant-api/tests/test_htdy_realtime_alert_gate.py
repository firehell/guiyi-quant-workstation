from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.htdy_realtime_alert_gate import (
    HtdyRealtimeAlertGateError,
    build_approval_packet,
    canonical_packet_hash,
    verify_approval_packet,
)


def _facts(tmp_path: Path) -> dict[str, object]:
    receipt = tmp_path / "s6-08-receipt.json"
    receipt.write_text(
        json.dumps({"gate": "LIVE_SIGNAL_EVENT_GATE_PASSED"}),
        encoding="utf-8",
    )
    return {
        "runtime_commit": "a" * 40,
        "database_revision": "20260725_0026",
        "indicator_source_sha256": "b" * 64,
        "s6_08_receipt_path": str(receipt),
        "s6_08_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
    }


def test_htdy_packet_binds_repainting_scope_and_s6_08_prerequisite(tmp_path: Path) -> None:
    packet = build_approval_packet(
        current_facts=_facts(tmp_path),
        enable_wechat=True,
    )

    assert packet["gate"] == "HTDY_ORIGINAL_REALTIME_ALERT_APPROVED"
    assert packet["prerequisite"]["gate"] == "LIVE_SIGNAL_EVENT_GATE_PASSED"
    assert packet["indicator"]["future_looking"] is True
    assert packet["indicator"]["repainting_risk"] == "known"
    assert packet["scope"]["product"] == "jm"
    assert packet["scope"]["period"] == "15m"
    assert packet["scope"]["formal_signal_event"] is False
    assert packet["scope"]["backtest"] is False
    assert packet["scope"]["order_or_trade"] is False
    assert packet["scope"]["wechat_autosend"] is True
    assert packet["runtime"]["database_revision"] == "20260725_0026"
    assert packet["packet_hash"] == canonical_packet_hash(packet)
    assert "webhook" not in json.dumps(packet).lower()


def test_htdy_packet_verifier_rejects_drift_and_missing_s6_08(tmp_path: Path) -> None:
    facts = _facts(tmp_path)
    packet = build_approval_packet(current_facts=facts, enable_wechat=False)
    approval_hash = str(packet["packet_hash"])

    verify_approval_packet(
        packet,
        approval_hash=approval_hash,
        current_facts=facts,
        alerts_enabled=True,
        wechat_enabled=False,
    )

    with pytest.raises(HtdyRealtimeAlertGateError, match="runtime_commit_changed"):
        verify_approval_packet(
            packet,
            approval_hash=approval_hash,
            current_facts={**facts, "runtime_commit": "c" * 40},
            alerts_enabled=True,
            wechat_enabled=False,
        )

    with pytest.raises(HtdyRealtimeAlertGateError, match="database_revision_changed"):
        verify_approval_packet(
            packet,
            approval_hash=approval_hash,
            current_facts={**facts, "database_revision": "20260721_0025"},
            alerts_enabled=True,
            wechat_enabled=False,
        )

    Path(str(facts["s6_08_receipt_path"])).write_text(
        json.dumps({"gate": "PENDING_ELIGIBLE_EVENT"}),
        encoding="utf-8",
    )
    with pytest.raises(HtdyRealtimeAlertGateError, match="s6_08_receipt_changed"):
        verify_approval_packet(
            packet,
            approval_hash=approval_hash,
            current_facts=facts,
            alerts_enabled=True,
            wechat_enabled=False,
        )


def test_htdy_packet_verifier_rejects_flag_scope_mismatch(tmp_path: Path) -> None:
    facts = _facts(tmp_path)
    packet = build_approval_packet(current_facts=facts, enable_wechat=False)

    with pytest.raises(HtdyRealtimeAlertGateError, match="wechat_scope_mismatch"):
        verify_approval_packet(
            packet,
            approval_hash=str(packet["packet_hash"]),
            current_facts=facts,
            alerts_enabled=True,
            wechat_enabled=True,
        )
