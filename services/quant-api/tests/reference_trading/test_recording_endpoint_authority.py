from datetime import UTC, datetime, timedelta, date
from types import SimpleNamespace

import pytest

from app.reference_trading.health import read_completed_recording_endpoints

AT = datetime(2026, 10, 8, 15, 10, tzinfo=UTC)
PUBLISHED = AT.replace(hour=7, minute=0)
COMPLETED = AT.replace(minute=0)


def setup(monkeypatch, endpoint):
    import app.reference_trading.health as health
    import app.market_data.composition as composition
    import app.redis_connections as connections

    def canonical(session, keys, at):
        return {
            key: {
                "expected_through": PUBLISHED.isoformat(),
                "expected_source": "canonical_completed",
                "endpoint_status": "READY",
                "endpoint_reason": None,
            }
            for key in keys
        }

    def derive(identity, now):
        assert now == AT
        if isinstance(endpoint, Exception):
            raise endpoint
        return endpoint, date(2026, 10, 9), "RB2611"

    redis = SimpleNamespace(closed=False)

    def close():
        redis.closed = True

    redis.close = close
    monkeypatch.setattr(health, "read_completed_canonical_endpoints", canonical)
    monkeypatch.setattr(connections, "get_redis_connection", lambda: redis)
    monkeypatch.setattr(
        composition,
        "build_market_read_service",
        lambda session, redis: SimpleNamespace(
            newow_completed_observation_endpoint=derive
        ),
    )
    return redis


def test_session_due_missing_saved_bar_cannot_fallback_to_canonical(monkeypatch):
    redis = setup(monkeypatch, COMPLETED)
    values = read_completed_recording_endpoints(None, (("rb", "60m"), ("rb", "1d")), AT)
    assert values[("rb", "60m")]["expected_through"] == COMPLETED.isoformat()
    assert values[("rb", "60m")]["expected_source"] == "completed_live"
    assert values[("rb", "1d")]["expected_through"] == PUBLISHED.isoformat()
    assert redis.closed


@pytest.mark.parametrize("endpoint", [None, PUBLISHED - timedelta(hours=1)])
def test_known_session_no_new_completed_hour_retains_published_authority(
    monkeypatch, endpoint
):
    setup(monkeypatch, endpoint)
    result = read_completed_recording_endpoints(None, (("rb", "60m"),), AT)[
        ("rb", "60m")
    ]
    assert result["expected_source"] == "canonical_completed"
    assert result["expected_through"] == PUBLISHED.isoformat()
    assert result["endpoint_status"] == "READY"


@pytest.mark.parametrize(
    "endpoint", [ValueError("missing session"), AT + timedelta(hours=1)]
)
def test_unproved_or_future_session_cannot_hide_behind_published_tail(
    monkeypatch, endpoint
):
    redis = setup(monkeypatch, endpoint)
    result = read_completed_recording_endpoints(None, (("rb", "60m"),), AT)[
        ("rb", "60m")
    ]
    assert result["expected_through"] is None
    assert result["endpoint_status"] == "UNKNOWN"
    assert redis.closed
