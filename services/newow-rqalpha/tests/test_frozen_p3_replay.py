"""Opt-in reproduction of the real MDS/P2 input without Catalog or network."""

from hashlib import sha256
from pathlib import Path
import json
import os

import pytest


def test_full_fu2603_replay_retains_p2_timing_and_expected_money(monkeypatch):
    configured = os.getenv("GUIYI_P3_FROZEN_PACKET")
    if not configured:
        pytest.skip("GUIYI_P3_FROZEN_PACKET is required for the frozen real-data test")
    path = Path(configured)
    data = path.read_bytes()
    assert sha256(data).hexdigest() == path.stem
    repo = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(repo / "packages/quant-core"))
    monkeypatch.syspath_prepend(str(repo / "services/quant-api"))
    from replay import replay

    packet = json.loads(data)
    result = replay(packet, "a" * 64)
    assert len(packet["completed"]) == 14_232
    assert len(packet["market"]["minute_oi"]) == 225
    assert all(oi is not None for _, oi in packet["market"]["minute_oi"])
    summary = result["summary"]
    assert summary["fill_count"] == 8
    assert summary["closed_trade_count"] == 4
    assert summary["fees"] == "4.92300000"
    assert summary["final_equity"] == "9765.07700000"
    assert summary["terminal_status"] == "FLAT"
    assert any(
        row["signal_bar_end"] == "2026-01-05T11:30:00+08:00"
        and row["reason"] == "NO_SAME_SESSION_CANDIDATE"
        for row in summary["attempts"]
    )
    first, second = result["trades"][:2]
    assert (first["modeled_fill_at"], first["native_fill_event_at"], first["price"]) == (
        "2026-01-05T09:06:00+08:00", "2026-01-05T09:07:00+08:00", "2491.00000000",
    )
    assert (second["modeled_fill_at"], second["native_fill_event_at"], second["price"]) == (
        "2026-01-05T09:46:00+08:00", "2026-01-05T09:47:00+08:00", "2477.00000000",
    )
