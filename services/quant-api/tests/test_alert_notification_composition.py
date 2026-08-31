from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.alerts.composition import _SubingStrategyRuntimeReader
from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeProductSourceError,
)
from app.alerts.notification_composition import (
    build_notification_sender_from_env,
    notification_transport_status_from_env,
)
from app.alerts.notification_config import NOTIFICATION_CONFIG_ENV
from app.market_data.domain import CanonicalBar
from app.market_data.subing_strategy.current_service import (
    SubingStrategyCurrentSourceUnavailableError,
)
from app.market_data.subing_strategy.machine import SubingStrategySourceIdentity
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
)


MESSAGE_TOKEN = "0123456789abcdef0123456789abcdef"
SHORT_CODE = "fedcba9876543210fedcba9876543210"


class AcceptingClient:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def send(self, request: object) -> str:
        self.requests.append(request)
        return SHORT_CODE


def _write_config(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    path = parent / "notification.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transport": "pushplus",
                "transport_config": {
                    "message_token": MESSAGE_TOKEN,
                    "htdy_topic": "fixture-private-topic",
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_factory_builds_dispatcher_from_one_frozen_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = _write_config(tmp_path)
    monkeypatch.setenv(NOTIFICATION_CONFIG_ENV, str(path))
    client = AcceptingClient()

    accepted = build_notification_sender_from_env(client=client).send_canary("owner")

    assert accepted.reference == SHORT_CODE
    assert len(client.requests) == 1
    assert client.requests[0].topic is None


def test_structural_status_reads_config_without_constructing_client(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = _write_config(tmp_path)
    monkeypatch.setenv(NOTIFICATION_CONFIG_ENV, str(path))

    assert notification_transport_status_from_env() == {
        "transport": "pushplus",
        "configured": True,
        "audience_count": 2,
        "would_send": False,
    }


def test_structural_status_is_missing_or_invalid_without_private_details(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(NOTIFICATION_CONFIG_ENV, raising=False)
    assert notification_transport_status_from_env() == {
        "transport": "pushplus",
        "configured": False,
        "audience_count": 2,
        "would_send": False,
    }
    monkeypatch.setenv(NOTIFICATION_CONFIG_ENV, str(tmp_path / "private-value"))
    assert notification_transport_status_from_env()["configured"] is False


def _terminal() -> AuthoritativeSegmentTerminal:
    return AuthoritativeSegmentTerminal(
        symbol="jm",
        contract="JM2609",
        segment_start_trading_day=date(2026, 8, 3),
        terminal_bar=CanonicalBar(
            bar_end=datetime(2026, 8, 14, 7, tzinfo=UTC),
            trading_day=date(2026, 8, 14),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        ),
    )


def test_strategy_reader_construction_is_lazy_and_rollover_uses_current_restore() -> (
    None
):
    calls: list[object] = []
    restored = object()

    class Service:
        def restore_machine(self, *, symbol: str, now: datetime):
            calls.append((symbol, now))
            return restored

    reader = _SubingStrategyRuntimeReader(
        session_factory=lambda: nullcontext(object()),
        service_factory=lambda _session: calls.append("factory") or Service(),
        clock=lambda: datetime(2026, 8, 17, 1, tzinfo=UTC),
    )
    assert calls == []

    result = reader.restore_rollover(
        symbol="jm",
        trading_day=date(2026, 8, 17),
        previous_identity=SubingStrategySourceIdentity(
            symbol="jm",
            contract="JM2609",
            segment_start_trading_day=date(2026, 8, 3),
        ),
        terminal=_terminal(),
    )

    assert result is restored
    assert calls == [
        "factory",
        ("jm", datetime(2026, 8, 17, 1, tzinfo=UTC)),
    ]


def test_strategy_reader_wraps_known_product_source_failure_without_detail() -> None:
    class Service:
        def completed_live_after(self, **_kwargs):
            raise SubingStrategyCurrentSourceUnavailableError()

    reader = _SubingStrategyRuntimeReader(
        session_factory=lambda: nullcontext(object()),
        service_factory=lambda _session: Service(),
    )
    identity = SubingStrategySourceIdentity(
        symbol="jm",
        contract="JM2609",
        segment_start_trading_day=date(2026, 8, 3),
    )

    with pytest.raises(SubingStrategyRuntimeProductSourceError) as raised:
        reader.read_final_catch_up_bars(
            symbol="jm",
            source_identity=identity,
            after_1m=None,
            after_5m=None,
            after_15m=None,
            through=datetime(2026, 8, 17, 1, tzinfo=UTC),
        )

    assert str(raised.value) == ""


def test_strategy_reader_marks_only_final_catch_up_for_post_close_authority() -> None:
    captured: dict[str, object] = {}
    expected = object()

    class Service:
        def completed_live_after(self, **kwargs):
            captured.update(kwargs)
            return expected

    reader = _SubingStrategyRuntimeReader(
        session_factory=lambda: nullcontext(object()),
        service_factory=lambda _session: Service(),
    )
    identity = SubingStrategySourceIdentity(
        symbol="jm",
        contract="JM2609",
        segment_start_trading_day=date(2026, 8, 3),
    )

    assert reader.read_final_catch_up_bars(
        symbol="jm",
        source_identity=identity,
        after_1m=None,
        after_5m=None,
        after_15m=None,
        through=datetime(2026, 8, 17, 1, tzinfo=UTC),
    ) is expected
    assert captured["allow_post_close_frozen"] is True


def test_strategy_reader_resolves_live_continuation_at_event_time() -> None:
    captured: dict[str, object] = {}

    class Service:
        def resolve_live_continuation(self, **kwargs):
            captured.update(kwargs)
            return object()

    processing_clock = datetime(2026, 8, 17, 2, tzinfo=UTC)
    event_time = datetime(2026, 8, 14, 7, tzinfo=UTC)
    reader = _SubingStrategyRuntimeReader(
        session_factory=lambda: nullcontext(object()),
        service_factory=lambda _session: Service(),
        clock=lambda: processing_clock,
    )
    identity = SubingStrategySourceIdentity(
        symbol="jm",
        contract="JM2609",
        segment_start_trading_day=date(2026, 8, 3),
    )

    reader.resolve_live_continuation(
        symbol="jm",
        source_identity=identity,
        incoming_trading_day=date(2026, 8, 14),
        now=event_time,
    )

    assert captured["now"] == event_time


def test_strategy_reader_does_not_reclassify_unknown_programming_failure() -> None:
    failure = RuntimeError("programming failure")

    class Service:
        def completed_live_after(self, **_kwargs):
            raise failure

    reader = _SubingStrategyRuntimeReader(
        session_factory=lambda: nullcontext(object()),
        service_factory=lambda _session: Service(),
    )

    with pytest.raises(RuntimeError) as raised:
        reader.read_final_catch_up_bars(
            symbol="jm",
            source_identity=SubingStrategySourceIdentity(
                symbol="jm",
                contract="JM2609",
                segment_start_trading_day=date(2026, 8, 3),
            ),
            after_1m=None,
            after_5m=None,
            after_15m=None,
            through=datetime(2026, 8, 17, 1, tzinfo=UTC),
        )

    assert raised.value is failure
