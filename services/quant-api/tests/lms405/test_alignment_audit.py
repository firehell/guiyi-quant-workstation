import importlib.util
from contextlib import contextmanager
from datetime import datetime, date, UTC
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "alignment_audit",
    Path(__file__).resolve().parents[4] / "scripts/research/lms405_alignment_audit.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def bar(when, low, high):
    return SimpleNamespace(
        bar_end=datetime.fromisoformat(when).astimezone(UTC),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high),
    )


def test_day_extrema_excludes_night_and_other_dates():
    bars = [
        bar("2026-09-18T21:01:00+08:00", "1", "9999"),
        bar("2026-09-21T09:01:00+08:00", "1487", "1533.5"),
        bar("2026-09-21T15:01:00+08:00", "1", "9999"),
    ]
    result = MODULE.daytime_extrema(bars, date(2026, 9, 21))
    assert result == {"bar_count": 1, "high": "1533.5", "low": "1487"}
    match = MODULE.compare_extrema(result, Decimal("1487"), Decimal("1533.5"))
    assert match["low_price_delta"] == "0"
    assert match["bar_ohlc_parity"] == "UNKNOWN"
    assert match["signal_eligible"] is False


def test_empty_samples_do_not_match():
    observed = MODULE.daytime_extrema([], date(2026, 9, 21))
    assert (
        MODULE.compare_extrema(observed, Decimal("1"), Decimal("2"))["low_price_delta"]
        is None
    )


@contextmanager
def session():
    yield object()


@contextmanager
def failed_exit(*args, **kwargs):
    yield
    raise RuntimeError("transaction exit failed")


class Missing(Exception):
    code = "DATASET_OR_PARTITION_MISSING"


def run(transaction, reader):
    return MODULE.audit_request(
        session,
        transaction,
        lambda s: s,
        reader,
        "jm",
        "JM2701",
        "1m",
        date(2026, 9, 21),
        date(2026, 10, 9),
        Missing,
    )


def test_transaction_exit_failure_discards_success_evidence():
    result = run(
        failed_exit,
        lambda *args: SimpleNamespace(bars=[], request_identity={}, coverage=None),
    )
    assert result["status"] == "BLOCKED"
    assert "bar_count" not in result
    assert "E51" not in result


def test_missing_data_preserves_typed_gap():
    def missing(*args):
        raise Missing()

    result = run(failed_exit, missing)
    assert result["reason"] == "DATASET_OR_PARTITION_MISSING"
    assert result["signal_eligible"] is False


@contextmanager
def passed_transaction(*args, **kwargs):
    yield


def test_trade_day_query_uses_author_date_without_equating_extrema_to_k_parity():
    calls = []

    def reader(*args):
        calls.append(args[-2:])
        bars = [
            bar("2026-09-18T21:01:00+08:00", "1487", "1510"),
            bar("2026-09-21T09:01:00+08:00", "1503.5", "1533.5"),
        ]
        return SimpleNamespace(bars=bars, request_identity={}, coverage=None)

    result = run(passed_transaction, reader)
    assert calls[-1] == (date(2026, 9, 21), date(2026, 9, 21))
    assert result["E51"]["low_price_delta"] == "16.5"
    assert result["E51_trading_day"]["low_price_delta"] == "0"
    assert result["E51_trading_day"]["bar_ohlc_parity"] == "UNKNOWN"
    assert result["author_period_verified"] is False
