import argparse
import json
from datetime import date, datetime, time

from app.api.backtests import load_contract_spec
from app.backtest.engine import BacktestConfig, run_su_bing_backtest
from app.db.session import SessionLocal
from app.services.market_data_reader import MarketDataReader
from app.backtest.service import BacktestService
from app.vnpy_integration.errors import BacktestConfigurationError
from app.strategy.su_bing_ema21 import SuBingParams


def main() -> None:
    parser = argparse.ArgumentParser(prog="guiyi-data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check-bars")
    check_parser.add_argument("--symbol", required=True)
    check_parser.add_argument("--contract", required=True)
    check_parser.add_argument("--period", required=True)
    check_parser.add_argument("--start")
    check_parser.add_argument("--end")
    check_parser.add_argument("--provider")

    backtest_parser = subparsers.add_parser("run-su-bing-backtest")
    backtest_parser.add_argument("--symbol", required=True)
    backtest_parser.add_argument("--contract", required=True)
    backtest_parser.add_argument("--period", required=True)
    backtest_parser.add_argument("--start", required=True)
    backtest_parser.add_argument("--end", required=True)
    backtest_parser.add_argument("--profile-id")
    backtest_parser.add_argument("--initial-capital", type=float, default=100000.0)
    backtest_parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    backtest_parser.add_argument("--max-margin-usage-pct", type=float, default=0.35)
    backtest_parser.add_argument("--slippage-ticks", type=int, default=1)

    args = parser.parse_args()

    if args.command == "check-bars":
        with SessionLocal() as session:
            status = MarketDataReader(session).get_quality_status(
                symbol=args.symbol,
                contract=args.contract,
                period=args.period,
                start=_parse_cli_datetime(args.start, end_of_day=False) if args.start else datetime.min,
                end=_parse_cli_datetime(args.end, end_of_day=True) if args.end else datetime.max,
                provider=args.provider,
            )
            print(
                f"status={status['status']} "
                f"missing_bars={status['missing_bars']} "
                f"duplicated_bars={status['duplicated_bars']} "
                f"abnormal_price_count={status['abnormal_price_count']} "
                f"abnormal_volume_count={status['abnormal_volume_count']} "
                f"report_count={status['report_count']}"
            )
    elif args.command == "run-su-bing-backtest":
        with SessionLocal() as session:
            start = _parse_cli_datetime(args.start, end_of_day=False)
            end = _parse_cli_datetime(args.end, end_of_day=True)
            reader = MarketDataReader(session)
            try:
                lineage, asset = BacktestService(session).resolve_formal_asset(
                    instrument_symbol=args.symbol,
                    contract_code=args.contract,
                    period=args.period,
                    profile_id=args.profile_id,
                )
                BacktestService._validate_requested_window(asset, start=start, end=end)
            except BacktestConfigurationError as exc:
                raise SystemExit(str(exc)) from exc
            bars = reader.load_bars(
                symbol=args.symbol,
                contract=args.contract,
                period=args.period,
                start=start,
                end=end,
                provider=str(asset["provider"]),
                data_role="primary",
                passed_only=True,
                profile_id=lineage.profile_id,
            )
            if not bars:
                raise SystemExit("no bars found for backtest")
            report = run_su_bing_backtest(
                bars=bars,
                config=BacktestConfig(
                    initial_capital=args.initial_capital,
                    risk_per_trade_pct=args.risk_per_trade_pct,
                    max_margin_usage_pct=args.max_margin_usage_pct,
                    slippage_ticks=args.slippage_ticks,
                    strategy_params=SuBingParams(),
                ),
                contract_spec=load_contract_spec(session, args.symbol, args.contract),
            )
            payload = report.to_dict()
            payload["quality_status"] = {"status": "passed", "market_data_file_id": lineage.market_data_file_id}
            payload["profile_id"] = lineage.profile_id
            payload["market_data_file_id"] = lineage.market_data_file_id
            payload["binding_snapshot"] = asset
            print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_cli_datetime(value: str, end_of_day: bool) -> datetime:
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.max if end_of_day else time.min)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


if __name__ == "__main__":
    main()
