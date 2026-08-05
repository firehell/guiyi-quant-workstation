"""Runtime safety smoke after Gate decoupling (no live side effects)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_runtime_scheduler_module_imports() -> None:
    pytest.importorskip("app")
    from app import runtime_scheduler

    assert hasattr(runtime_scheduler, "_build_signal_gate")


def test_build_signal_gate_rejects_missing_and_superseded(tmp_path: Path) -> None:
    pytest.importorskip("app")
    from app.runtime_scheduler import _build_signal_gate

    with pytest.raises(ValueError, match="approval_packet_required"):
        _build_signal_gate(approval_packet=None, approval_hash="a" * 64, environ={})

    packet = tmp_path / "bad.json"
    packet.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "packet_type": "htdy_s6_10_five_day_parent",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="superseded_runtime_gate_disabled"):
        _build_signal_gate(
            approval_packet=packet,
            approval_hash="a" * 64,
            environ={},
        )


def test_scheduler_source_no_longer_imports_s610_gate_builders() -> None:
    text = (
        REPO / "services/quant-api/app/runtime_scheduler.py"
    ).read_text(encoding="utf-8")
    assert "htdy_s6_10_runtime_gate" not in text
    assert "htdy_s6_10_one_day_runtime_gate" not in text
    assert "htdy_s6_10_remaining_window_runtime_gate" not in text
    assert "htdy_s6_10_long_running_runtime_gate" not in text
    assert "superseded_runtime_gate_disabled" in text
