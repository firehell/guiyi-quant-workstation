"""Checkpoint watermarks include every persisted monotonic boundary."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.checkpoint import checkpoint_watermark


@pytest.mark.parametrize("latest", range(4))
def test_watermark_never_regresses_any_boundary(latest):
    start = datetime(2026, 10, 15, tzinfo=UTC)
    values = [start] * 4
    values[latest] += timedelta(minutes=1)
    assert checkpoint_watermark(
        SimpleNamespace(computed_through=values[0]),
        SimpleNamespace(bar_end=values[1]),
        SimpleNamespace(
            computed_through=values[2], last_event_key=(values[3], "event")
        ),
    ) == start + timedelta(minutes=1)


def test_initial_watermark_uses_bar_when_other_boundaries_absent():
    end = datetime(2026, 10, 15, tzinfo=UTC)
    assert (
        checkpoint_watermark(
            SimpleNamespace(computed_through=None),
            SimpleNamespace(bar_end=end),
            SimpleNamespace(computed_through=None, last_event_key=None),
        )
        == end
    )
