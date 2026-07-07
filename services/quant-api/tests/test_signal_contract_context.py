from datetime import datetime, timedelta

from app.signal.contract_context import build_signal_contract_context


def test_main_contract_is_continuous_context_not_actual_contract() -> None:
    signal_time = datetime(2026, 7, 7, 9, 15)

    context = build_signal_contract_context(
        symbol="jm",
        contract="jm.MAIN",
        period="15m",
        signal_time=signal_time,
        current_price=1008.5,
        features={"data_provider": "rqdata", "signal_price": 1008.5},
        quality_status={"status": "passed"},
        research_contract=True,
    )

    assert context.product == "jm"
    assert context.continuous_contract == "jm.MAIN"
    assert context.actual_contract is None
    assert context.bar_start == signal_time - timedelta(minutes=15)
    assert context.bar_end == signal_time
    assert context.trigger_price == 1008.5
    assert context.provider == "rqdata"
    assert context.source == "historical_standard_parquet"
    assert context.data_role == "primary"


def test_real_contract_can_be_projected_as_actual_contract() -> None:
    signal_time = datetime(2026, 7, 7, 10, 5)

    context = build_signal_contract_context(
        symbol="jm",
        contract="JM2609",
        period="5m",
        signal_time=signal_time,
        current_price=1010.0,
        features={"provider": "rqdata", "source": "live_db"},
        quality_status={"status": "passed"},
        research_contract=False,
    )

    assert context.product == "jm"
    assert context.continuous_contract is None
    assert context.actual_contract == "JM2609"
    assert context.bar_start == signal_time - timedelta(minutes=5)
    assert context.bar_end == signal_time
    assert context.trigger_price == 1010.0
    assert context.provider == "rqdata"
    assert context.source == "live_db"
