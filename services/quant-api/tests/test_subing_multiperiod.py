from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.alerts.evaluators import SubingThsEvaluator
from app.alerts.models import AlertEvent, AlertRule, SubingSignalAlignment
from app.alerts.registry import SUBING_THS_RULE
from app.alerts.service import AlertEventCreate, AlertService
from app.alerts.subing_alignment import build_subing_alignment
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import (
    CurrentContractReplayWindow,
    MarketReadWindow,
    MarketReadWindowError,
)

FREQUENCIES = ("5m", "15m", "30m", "60m", "1d", "1w")
NOW = datetime(2026, 10, 8, 7, tzinfo=UTC)


def bars(length=50, *, equal=False):
    return tuple(
        CanonicalBar(
            bar_end=NOW - timedelta(minutes=15 * (length - 1 - i)),
            trading_day=date(2026, 10, 8),
            open=Decimal(100 if equal else 100 + i),
            high=Decimal(101 if equal else 101 + i),
            low=Decimal(99 if equal else 99 + i),
            close=Decimal(100 if equal else 100 + i),
            volume=Decimal(100),
            turnover=None,
            open_interest=None,
        )
        for i in range(length)
    )


def window(frequency="15m"):
    source = bars()
    return MarketReadWindow(
        "jm",
        "actual_dominant",
        frequency,
        date(2026, 10, 8),
        "JM2701",
        NOW,
        source,
        ("JM2701",) * len(source),
    )


class Reader:
    def __init__(self, *, missing=None, equal=None, future=None):
        self.missing = missing
        self.equal = equal
        self.future = future

    def subing_direction_window(self, decision, frequency):
        if frequency.value == self.missing:
            raise MarketReadWindowError("MARKET_READ_WINDOW_INCOMPLETE")
        source = bars(equal=frequency.value == self.equal)
        cutoff = NOW if frequency.value != self.future else NOW + timedelta(minutes=1)
        if frequency.value == self.future:
            source = source[:-1] + (replace(source[-1], bar_end=cutoff),)
        return CurrentContractReplayWindow(
            "jm", frequency.value, decision.trading_day, "JM2701", cutoff, None, source
        )

    def current_contract_replay_window(self, decision, *, after):
        source = tuple(b for b in decision.bars if after is None or b.bar_end > after)
        return CurrentContractReplayWindow(
            decision.symbol,
            decision.frequency,
            decision.trading_day,
            decision.contract,
            decision.cutoff,
            after,
            source,
        )


def test_six_period_registry_is_silent():
    assert SUBING_THS_RULE.input_frequencies == FREQUENCIES
    assert SUBING_THS_RULE.notification_enabled is False


def test_same_symbol_same_cutoff_different_periods_have_independent_states():
    evaluator = SubingThsEvaluator()
    for frequency in FREQUENCIES:
        evaluator.evaluate_candidates(Reader(), window(frequency))
    assert len(evaluator._cursors) == 6


@pytest.mark.parametrize(
    ("reader", "expected"),
    [
        (Reader(), "PASS"),
        (Reader(equal="60m"), "FAIL"),
        (Reader(missing="1w"), "UNKNOWN"),
        (Reader(future="30m"), "UNKNOWN"),
    ],
)
def test_alignment_uses_ema_positions_and_rejects_missing_equal_and_future(
    reader, expected
):
    result = build_subing_alignment(
        reader, window(), direction="buy", observed_at=NOW + timedelta(seconds=9)
    )
    assert result["status"] == expected
    assert len(result["periods"]) == 6
    assert result["as_of"] == NOW.isoformat()
    assert result["observed_at"] == (NOW + timedelta(seconds=9)).isoformat()
    if expected == "PASS":
        assert all(p["direction"] == "LONG" for p in result["periods"])
        assert all(
            isinstance(p["ema21"], str) and p["input_snapshot_hash"]
            for p in result["periods"]
        )


def test_sell_fails_even_without_other_cross_signals_when_ema_positions_are_long():
    assert (
        build_subing_alignment(Reader(), window(), direction="sell", observed_at=NOW)[
            "status"
        ]
        == "FAIL"
    )


def test_event_and_alignment_commit_once_duplicate_does_not_replace_snapshot():
    engine = create_engine("sqlite://")
    for table in (
        AlertRule.__table__,
        AlertEvent.__table__,
        SubingSignalAlignment.__table__,
    ):
        table.create(engine)
    with Session(engine) as session:
        rule = AlertRule(
            rule_code=SUBING_THS_RULE.rule_code,
            enabled=True,
            scope_product_frequencies={"jm": list(FREQUENCIES)},
        )
        session.add(rule)
        session.commit()
        service = AlertService(session, operational_products=("jm",))
        from app.schemas.alerts import SubingAlignmentOut

        snapshot = SubingAlignmentOut.model_validate(
            build_subing_alignment(Reader(), window(), direction="buy", observed_at=NOW)
        ).model_dump(mode="json")
        request = AlertEventCreate(
            rule.id,
            "jm",
            "JM2701",
            date(2026, 10, 8),
            "15m",
            NOW,
            ("buy",),
            NOW,
            None,
            subing_alignment=snapshot,
        )
        created = service.create_event(request)
        assert created is not None
        stored = session.get(SubingSignalAlignment, created.id)
        assert stored.snapshot == snapshot
        changed = build_subing_alignment(
            Reader(missing="1w"),
            window(),
            direction="buy",
            observed_at=NOW + timedelta(seconds=20),
        )
        assert service.create_event(replace(request, subing_alignment=changed)) is None
        assert (
            session.scalar(select(func.count()).select_from(SubingSignalAlignment)) == 1
        )
        session.expire_all()
        assert session.get(SubingSignalAlignment, created.id).snapshot == snapshot


@pytest.mark.parametrize("mutation", ["direction", "status"])
def test_storage_rejects_inconsistent_alignment(mutation):
    from app.alerts.service import AlertConsistencyError

    engine = create_engine("sqlite://")
    for table in (
        AlertRule.__table__,
        AlertEvent.__table__,
        SubingSignalAlignment.__table__,
    ):
        table.create(engine)
    with Session(engine) as session:
        rule = AlertRule(
            rule_code=SUBING_THS_RULE.rule_code,
            enabled=True,
            scope_product_frequencies={"jm": list(FREQUENCIES)},
        )
        session.add(rule)
        session.commit()
        snapshot = build_subing_alignment(
            Reader(), window(), direction="buy", observed_at=NOW
        )
        if mutation == "direction":
            snapshot["periods"][0]["direction"] = "SHORT"
        else:
            snapshot["status"] = "FAIL"
        request = AlertEventCreate(
            rule.id,
            "jm",
            "JM2701",
            date(2026, 10, 8),
            "15m",
            NOW,
            ("buy",),
            NOW,
            None,
            subing_alignment=snapshot,
        )
        with pytest.raises(AlertConsistencyError):
            AlertService(session, operational_products=("jm",)).create_event(request)
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0


def test_snapshot_insert_failure_rolls_back_original_event():
    from app.alerts.service import AlertEventPersistenceError

    engine = create_engine("sqlite://")
    for table in (
        AlertRule.__table__,
        AlertEvent.__table__,
        SubingSignalAlignment.__table__,
    ):
        table.create(engine)
    with Session(engine) as session:
        rule = AlertRule(
            rule_code=SUBING_THS_RULE.rule_code,
            enabled=True,
            scope_product_frequencies={"jm": list(FREQUENCIES)},
        )
        session.add(rule)
        session.commit()
        session.execute(
            __import__("sqlalchemy").text(
                "CREATE TRIGGER refuse_snapshot BEFORE INSERT ON subing_signal_alignments BEGIN SELECT RAISE(FAIL, 'test refusal'); END"
            )
        )
        session.commit()
        snapshot = build_subing_alignment(
            Reader(), window(), direction="buy", observed_at=NOW
        )
        request = AlertEventCreate(
            rule.id,
            "jm",
            "JM2701",
            date(2026, 10, 8),
            "15m",
            NOW,
            ("buy",),
            NOW,
            None,
            subing_alignment=snapshot,
        )
        with pytest.raises(AlertEventPersistenceError):
            AlertService(session, operational_products=("jm",)).create_event(request)
        assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
        assert (
            session.scalar(select(func.count()).select_from(SubingSignalAlignment)) == 0
        )


def test_history_filter_is_before_pagination_and_cursor_binds_status():
    from app.alerts.history import AlertHistoryQuery, AlertHistoryCursorError, read_alert_history
    engine = create_engine('sqlite://')
    for table in (AlertRule.__table__, AlertEvent.__table__, SubingSignalAlignment.__table__):
        table.create(engine)
    with Session(engine) as session:
        rule = AlertRule(rule_code=SUBING_THS_RULE.rule_code, enabled=True, scope_product_frequencies={'jm': list(FREQUENCIES)})
        session.add(rule)
        session.commit()
        ids = []
        for index, reader in enumerate((Reader(), Reader(equal='60m'), Reader(), Reader(missing='1w'))):
            end = NOW + timedelta(seconds=index)
            snapshot = build_subing_alignment(reader, window(), direction='buy', observed_at=end)
            snapshot['as_of'] = end.isoformat()
            created = AlertService(session, operational_products=('jm',)).create_event(AlertEventCreate(rule.id, 'jm', 'JM2701', NOW.date(), '15m', end, ('buy',), end, None, subing_alignment=snapshot))
            if snapshot['status'] == 'PASS':
                ids.append(created.id)
        query = AlertHistoryQuery(NOW.date(), NOW.date(), 'jm', rule.rule_code, 1, None, '15m', 'PASS')
        first = read_alert_history(session, query)
        assert [item.id for item in first.items] == ids[-1:]
        assert first.next_before is not None
        second = read_alert_history(session, replace(query, before=first.next_before))
        assert [item.id for item in second.items] == ids[:1]
        assert second.next_before is None
        with pytest.raises(AlertHistoryCursorError):
            read_alert_history(session, replace(query, before=first.next_before, alignment_status='FAIL'))


def test_malformed_decimal_is_a_typed_validation_failure():
    from pydantic import ValidationError
    from app.schemas.alerts import SubingAlignmentOut
    snapshot = build_subing_alignment(Reader(), window(), direction='buy', observed_at=NOW)
    snapshot['periods'][0]['close'] = 'not-a-number'
    with pytest.raises(ValidationError):
        SubingAlignmentOut.model_validate(snapshot)
