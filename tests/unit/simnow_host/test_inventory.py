"""Isolated native account reports, never account acceptance evidence."""

from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
from copy import deepcopy
import pytest
from guiyi_quant.simnow_execution.inventory import read_snapshot, project_readback
from guiyi_quant.simnow_execution import Contract

T = datetime(2026, 10, 27, 1, tzinfo=UTC)


def report():
    from guiyi_quant.simnow_execution.inventory import native_hash

    payload = {
        "funds": [
            dict(
                CurrencyID="CNY",
                TradingDay="20261027",
                Balance="100000",
                Available="100000",
                CurrMargin="0",
                FrozenMargin="0",
                FrozenCommission="0",
                Commission="0",
                Deposit="0",
                Withdraw="0",
                CloseProfit="0",
                PositionProfit="0",
            )
        ],
        "positions": [],
        "orders": [],
        "trades": [],
    }
    rounds = []
    for n in range(2):
        start = T + timedelta(seconds=n * 10)
        queries = {
            k: dict(
                complete=True,
                started_at=start.isoformat(),
                completed_at=(start + timedelta(seconds=1)).isoformat(),
                rows=deepcopy(v),
            )
            for k, v in payload.items()
        }
        rounds.append(
            dict(
                round=n + 1,
                started_at=start.isoformat(),
                completed_at=(start + timedelta(seconds=2)).isoformat(),
                queries=queries,
            )
        )
    return dict(
        schema="simnow_readonly_inventory_v1",
        environment="SIMNOW_FIRST",
        front="tcp://182.254.243.31:30001",
        source_scope="FIRST_ENVIRONMENT_READBACK",
        broker_id="9999",
        account_fingerprint="a" * 64,
        trading_day="20261027",
        status="READ_ONLY_COMPLETE",
        authentication_passed=True,
        login_passed=True,
        rounds=rounds,
        round_hashes=[native_hash(payload)] * 2,
    )


def test_complete_snapshot_projects_real_flat_balance_without_execution_authority():
    snapshot = read_snapshot(report())
    rb, inventory = project_readback(snapshot, (), None, None, T + timedelta(minutes=1))
    assert rb.snapshot.balance == D(100000) and rb.complete
    assert rb.snapshot.positions == () and inventory == ()
    assert rb.coverage == ()


def test_query_diagnostics_do_not_change_native_identity_or_override_incomplete_facts():
    value = report()
    original = read_snapshot(value)
    value["query_timeout_seconds"] = 45
    value["query_order"] = ["positions", "funds", "orders", "trades"]
    for record in value["rounds"]:
        record["queries"] = {
            kind: record["queries"][kind] for kind in value["query_order"]
        }
        for query in record["queries"].values():
            query["diagnostics"] = dict(
                response_count=1, terminal_response_seen=True, timed_out=False
            )
    assert read_snapshot(value) == original
    value["rounds"][0]["queries"]["funds"]["complete"] = False
    with pytest.raises(ValueError):
        read_snapshot(value)


@pytest.mark.parametrize(
    "problem",
    ["partial", "changed", "hash", "environment", "identity", "day", "future"],
)
def test_bad_readback_is_never_flat(problem):
    value = report()
    if problem == "partial":
        value["rounds"][1]["queries"]["positions"]["complete"] = False
    if problem == "changed":
        value["rounds"][1]["queries"]["funds"]["rows"][0]["Balance"] = "90000"
    if problem == "hash":
        value["round_hashes"][0] = "0" * 64
    if problem == "environment":
        value["environment"] = "SIMNOW_API_TEST"
    if problem == "identity":
        value["account_fingerprint"] = "bad"
    if problem == "day":
        value["rounds"][1]["queries"]["funds"]["rows"][0]["TradingDay"] = "20261026"
    if problem == "future":
        value["rounds"][1]["queries"]["funds"]["completed_at"] = (
            T + timedelta(days=1)
        ).isoformat()
    with pytest.raises(ValueError):
        read_snapshot(value)


def changed(value, kind, rows):
    from guiyi_quant.simnow_execution.inventory import native_hash

    for r in value["rounds"]:
        r["queries"][kind]["rows"] = deepcopy(rows)
    payload = {k: v["rows"] for k, v in value["rounds"][0]["queries"].items()}
    value["round_hashes"] = [native_hash(payload)] * 2
    return value


@pytest.mark.parametrize(
    "exchange,date,today,expected",
    [
        ("SHFE", "1", 1, (1, 0)),
        ("SHFE", "2", 0, (0, 1)),
        ("DCE", "1", 0, (0, 1)),
        ("DCE", "1", 1, (1, 0)),
    ],
)
def test_native_today_yesterday_positions(exchange, date, today, expected):
    native = "rb2701" if exchange == "SHFE" else "rb2701"
    b = Contract("RB2701", native, exchange, "contract", T, T + timedelta(days=1))
    row = dict(
        TradingDay="20261027",
        ExchangeID=exchange,
        InstrumentID=native,
        PosiDirection="2",
        HedgeFlag="1",
        PositionDate=date,
        Position=1,
        TodayPosition=today,
        YdPosition=1 - today,
        LongFrozen=0,
        ShortFrozen=0,
    )
    value = changed(report(), "positions", [row])
    funds = value["rounds"][0]["queries"]["funds"]["rows"][0]
    snapshot = read_snapshot(
        changed(value, "funds", [{**funds, "CurrMargin": "1000", "Available": "99000"}])
    )
    rb, inventory = project_readback(
        snapshot, (b,), None, None, T + timedelta(minutes=1)
    )
    assert rb.snapshot.positions[0].quantity == 1
    assert (inventory[0].today, inventory[0].yesterday) == expected


@pytest.mark.parametrize("issue", ["hedge", "oversize", "unknown"])
def test_native_position_cannot_be_net_flat(issue):
    b = Contract("RB2701", "rb2701", "SHFE", "contract", T, T + timedelta(days=1))
    row = dict(
        TradingDay="20261027",
        ExchangeID="SHFE",
        InstrumentID="rb2701",
        PosiDirection="2",
        HedgeFlag="1",
        PositionDate="1",
        Position=1,
        TodayPosition=1,
        LongFrozen=0,
        ShortFrozen=0,
    )
    rows = [row]
    if issue == "hedge":
        rows.append({**row, "PosiDirection": "3"})
    elif issue == "oversize":
        row["Position"] = row["TodayPosition"] = 2
    else:
        row["InstrumentID"] = "rb2705"
    snapshot = read_snapshot(changed(report(), "positions", rows))
    with pytest.raises(ValueError):
        project_readback(snapshot, (b,), None, None, T + timedelta(minutes=1))


def test_native_equity_cashflow_is_distinct_from_reference_returns():
    from guiyi_quant.simnow_execution.finance import performance

    base = read_snapshot(report())
    data = report()
    funds = data["rounds"][0]["queries"]["funds"]["rows"][0]
    funds = {
        **funds,
        "Balance": "105500",
        "Available": "104000",
        "Deposit": "5000",
        "Commission": "12.3",
        "PositionProfit": "512.3",
    }
    current = read_snapshot(changed(data, "funds", [funds]))
    result = performance(base, current)
    assert result.net_profit == D("500") and result.net_cashflow == D("5000")
    assert result.return_ratio == D(".005") and result.commission == D("12.3")


@pytest.mark.parametrize("field", ["CurrMargin", "FrozenMargin", "FrozenCommission"])
def test_unexplained_native_occupancy_is_not_just_counted_as_usable(field):
    value = report()
    funds = value["rounds"][0]["queries"]["funds"]["rows"][0]
    snapshot = read_snapshot(changed(value, "funds", [{**funds, field: "10"}]))
    with pytest.raises(ValueError):
        project_readback(snapshot, (), None, None, T + timedelta(minutes=1))
