"""Offline checks distinguish source-time and query-delay causes without changing gates."""

from datetime import timedelta
import json
import pytest
from test_native_portfolio import Market, T, portfolio
from guiyi_quant.simnow_execution.input_evidence import input_check_view


def test_success_retains_sources_and_expiry_then_becomes_stale(tmp_path):
    native = portfolio(tmp_path)
    native.observe_next(("JM",), Market(), T, "20261027", {})
    check = native.input_checks["JM"]
    assert check["status"] == "VERIFIED_AT_CHECK"
    assert check["contract"] == "JM2701"
    assert set(check["sources"]) == {
        "instrument",
        "margin",
        "commission",
        "book",
        "session",
    }
    assert all(check["sources"].values())
    assert set(check["source_times"]) == set(check["sources"])
    assert check["source_age_seconds"] == 0
    assert check["valid_until"] == (T + timedelta(seconds=3)).isoformat()
    assert input_check_view(native.input_checks, T, connected=True)["JM"]["fresh"]
    assert not input_check_view(
        native.input_checks, T + timedelta(seconds=3), connected=True
    )["JM"]["fresh"]
    assert not input_check_view(native.input_checks, T, connected=False)["JM"]["fresh"]


@pytest.mark.parametrize(
    "offset,reason", [(-9, "SOURCE_OLD_BEFORE_QUERY"), (1, "SOURCE_TIME_IN_FUTURE")]
)
def test_stale_failure_classifies_signed_age_and_discards_prior_success(
    tmp_path, offset, reason
):
    native = portfolio(tmp_path)
    native.observe_next(("JM",), Market(), T, "20261027", {})
    gateway = native.gateway
    original = gateway.query

    def query(kind, *args, **kwargs):
        rows = original(kind, *args, **kwargs)
        if kind == "book":
            event = T + timedelta(seconds=offset)
            rows[0].update(
                ActionDay=event.strftime("%Y%m%d"),
                UpdateTime=event.astimezone(
                    __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
                ).strftime("%H:%M:%S"),
            )
        return rows

    gateway.query = query
    issues = {}
    native.observe_next(("JM",), Market(), T, "20261027", issues)
    check = native.input_checks["JM"]
    assert check["status"] == "FAILED"
    assert check["code"] == "NATIVE_BOOK_STALE"
    assert check["timing_classification"] == reason
    assert not input_check_view(native.input_checks, T, connected=True)["JM"]["fresh"]
    assert "sources" not in check
    assert issues == {"JM": "EXECUTION_INPUT_UNPROVEN"}


def test_book_query_delay_that_crosses_age_limit_is_visible(tmp_path):
    native = portfolio(tmp_path)
    clock = [T + timedelta(seconds=7)]
    native.now = lambda: clock[0]
    original = native.gateway.query

    def query(kind, *args, **kwargs):
        result = original(kind, *args, **kwargs)
        if kind == "book":
            clock[0] += timedelta(seconds=2)
        return result

    native.gateway.query = query
    native.observe_next(("JM",), Market(), clock[0], "20261027", {})
    check = native.input_checks["JM"]
    assert check["source_age_seconds"] == 9
    assert check["timing_classification"] == "QUERY_CROSSED_SOURCE_AGE_LIMIT"
    assert check["book_query_seconds"] == 2


def test_night_action_day_can_differ_from_trading_day_without_rewriting(tmp_path):
    from guiyi_quant.simnow_execution.facts import quote_from_native
    from guiyi_quant.simnow_execution.model import Contract
    from test_native_portfolio import book
    from datetime import datetime, UTC

    at = datetime(2026, 10, 26, 13, tzinfo=UTC)
    binding = Contract(
        "JM2701", "jm2701", "DCE", "instrument", at, at + timedelta(minutes=5)
    )
    row = dict(
        book("JM"), ActionDay="20261026", TradingDay="20261027", UpdateTime="21:00:00"
    )
    diagnostics = {}
    q = quote_from_native(binding, row, "20261027", at, diagnostic=diagnostics)
    assert q.valid_until == at + timedelta(seconds=3)
    assert diagnostics["source_age_seconds"] == 0
    assert row["ActionDay"] == "20261026"


def test_unknown_failure_never_publishes_secret_or_old_success(tmp_path):
    native = portfolio(tmp_path)
    native.observe_next(("JM",), Market(), T, "20261027", {})
    native.gateway.query = lambda *args, **kwargs: (_ for _ in ()).throw(
        ValueError("secret-password tcp://private-host")
    )
    native.observe_next(("JM",), Market(), T + timedelta(seconds=1), "20261027", {})
    assert native.input_checks["JM"]["status"] == "FAILED"
    assert "secret" not in json.dumps(native.input_checks)
    assert "private-host" not in json.dumps(native.input_checks)


def test_persisted_check_has_no_fresh_boolean_and_reader_recomputes_after_ttl(tmp_path):
    from guiyi_quant.simnow_execution.input_evidence import (
        input_check_records,
        read_input_checks,
    )

    native = portfolio(tmp_path)
    native.observe_next(("JM",), Market(), T, "20261027", {})
    path = tmp_path / "continuous.json"
    payload = dict(
        mode="observe",
        connection="LOGGED_IN",
        at=T.isoformat(),
        products=["JM", "RB"],
        input_checks=input_check_records(native.input_checks, products=("JM", "RB")),
    )
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    assert "fresh" not in payload["input_checks"]["JM"]
    assert read_input_checks(path, T)["checks"]["JM"]["fresh"]
    assert not read_input_checks(path, T + timedelta(seconds=3))["checks"]["JM"][
        "fresh"
    ]
    assert read_input_checks(path, T)["checks"]["RB"]["status"] == "NOT_CHECKED"
    assert not read_input_checks(path, T)["checks"]["RB"]["fresh"]
    assert not read_input_checks(path, T - timedelta(seconds=1))["checks"]["JM"][
        "fresh"
    ]


def test_native_query_timing_sanitizer_retains_only_valid_timestamps_and_numbers():
    from guiyi_quant.simnow_execution.native_portfolio import safe_native_queries

    result = safe_native_queries(
        [
            dict(
                kind="book",
                elapsed_seconds=2.1,
                book_total_elapsed_seconds=3.2,
                book_target_received_at=T.isoformat(),
                book_request_sent_at="secret-password",
                book_terminal_received_at=None,
                raw="secret-password",
                book_returned_at="2026-10-27T01:00:00",
            )
        ]
    )
    assert result == [
        dict(
            kind="book",
            elapsed_seconds=2.1,
            book_total_elapsed_seconds=3.2,
            book_target_received_at=T.isoformat(),
        )
    ]
