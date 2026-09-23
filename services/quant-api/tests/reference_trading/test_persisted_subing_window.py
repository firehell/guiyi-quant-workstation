"""The saved Subing reader must serve a normal long intraday history window."""

from datetime import UTC, date, datetime

import pytest

from app.reference_trading.persisted_subing import PersistedSubingReference


def test_saved_subing_15m_window_reads_more_than_two_thousand_indicator_points() -> None:
    # 160 trading days with 16 completed 15m bars per day is within a year.
    saved_points = [{"id": index} for index in range(2_560)]

    class SavedPointPages:
        def signals(self, _stream_id, *, since, through, cutoff, snapshot_token,
                    cursor, limit, point_kind):
            assert (since, through) == (date(2026, 1, 5), date(2026, 8, 14))
            assert cutoff == datetime(2026, 8, 14, 5, 0, 1, tzinfo=UTC)
            assert snapshot_token == "saved-snapshot"
            assert point_kind == "indicator"
            start = int(cursor) if cursor is not None else 0
            end = min(start + limit, len(saved_points))
            return {
                "items": saved_points[start:end],
                "next_cursor": str(end) if end < len(saved_points) else None,
            }

    points = PersistedSubingReference._all_points(
        SavedPointPages(), "saved-stream", kind="indicator",
        since=date(2026, 1, 5), through=date(2026, 8, 14),
        cutoff=datetime(2026, 8, 14, 5, 0, 1, tzinfo=UTC),
        snapshot="saved-snapshot",
    )
    assert len(points) == 2_560
    assert points[0]["id"] == 0
    assert points[-1]["id"] == 2_559


def test_saved_subing_stops_paginating_when_request_deadline_expires() -> None:
    reads = 0
    checks = 0

    class EndlessPages:
        def signals(self, *_args, **_kwargs):
            nonlocal reads
            reads += 1
            return {"items": [{"id": reads}], "next_cursor": str(reads)}

    def check_deadline() -> None:
        nonlocal checks
        checks += 1
        if checks == 3:
            raise RuntimeError("request deadline")

    with pytest.raises(RuntimeError, match="request deadline"):
        PersistedSubingReference._all_points(
            EndlessPages(), "saved-stream", kind="indicator",
            since=date(2026, 1, 5), through=date(2026, 8, 14),
            cutoff=datetime(2026, 8, 14, 5, 0, 1, tzinfo=UTC),
            snapshot="saved-snapshot", check_cancelled=check_deadline,
        )
    assert reads == 2
