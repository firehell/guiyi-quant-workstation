from datetime import UTC, datetime

from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.services.review_center import _review_extra_from_trade


def test_review_extra_records_warning_quality_caveat() -> None:
    report = BacktestReportModel(
        task_id=1,
        task_no="BTB-test",
        report_no="RPT-test",
        template_name="default",
        strategy_code="jm_v1b",
        strategy_version="v1b.0",
        symbol="bb",
        contract="bb.MAIN",
        period="1d",
        status="completed",
        summary={"quality_status": {"status": "warning"}},
    )
    report.quality_status = {"status": "warning"}
    trade = BacktestTradeModel(
        report_id=1,
        trade_no="TRD-000001",
        symbol="bb",
        contract="bb.MAIN",
        direction="long",
        open_time=datetime(2024, 1, 1, 9, 10, tzinfo=UTC),
        open_price=100,
        close_time=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        close_price=105,
        volume=1,
        turnover=2050,
        commission=2,
        slippage=1,
        gross_pnl=50,
        net_pnl=47,
        return_pct=0.02,
        holding_bars=10,
        entry_reason="test",
        exit_reason="test",
        raw_payload={},
    )

    extra = _review_extra_from_trade(trade, report)

    assert extra["data_quality_status"] == "warning"
    assert "data_quality_caveat" in extra


def test_review_extra_records_passed_quality_without_caveat() -> None:
    report = BacktestReportModel(
        task_id=1,
        task_no="BTB-test",
        report_no="RPT-test",
        template_name="default",
        strategy_code="jm_v1b",
        strategy_version="v1b.0",
        symbol="jm",
        contract="jm.MAIN",
        period="15m",
        status="completed",
        summary={"quality_status": {"status": "passed"}},
    )
    report.quality_status = {"status": "passed"}
    trade = BacktestTradeModel(
        report_id=1,
        trade_no="TRD-000002",
        symbol="jm",
        contract="jm.MAIN",
        direction="long",
        open_time=datetime(2024, 1, 1, 9, 10, tzinfo=UTC),
        open_price=100,
        close_time=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        close_price=105,
        volume=1,
        turnover=2050,
        commission=2,
        slippage=1,
        gross_pnl=50,
        net_pnl=47,
        return_pct=0.02,
        holding_bars=10,
        entry_reason="test",
        exit_reason="test",
        raw_payload={},
    )

    extra = _review_extra_from_trade(trade, report)

    assert extra["data_quality_status"] == "passed"
    assert "data_quality_caveat" not in extra
