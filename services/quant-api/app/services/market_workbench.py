from collections import defaultdict
from datetime import UTC, datetime
import logging
from pathlib import Path
import sys
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import Contract, MarketDataFile
from app.schemas.market import (
    MarketMacdIndicatorPoint,
    MarketBarsCoverage,
    MarketBarsQuality,
    MarketBarsRequest,
    MarketBarsResponse,
    MarketMacdIndicatorResponse,
    MarketCoverageContract,
    MarketCoverageInstrument,
    MarketCoverageItem,
    MarketCoveragePeriod,
    MarketCoverageSummary,
    MarketWorkbenchCoverage,
    MarketWorkbenchSelection,
)
from app.services.market_data_reader import MarketDataReader
from app.services.futures_contract_utils import continuous_contract_for, is_continuous_contract
from app.services.market_dominant_reader import DEFAULT_QUOTE_PERIOD, validate_quote_contract

QUANT_CORE_ROOT = Path(__file__).resolve().parents[4] / "packages" / "quant-core"
if QUANT_CORE_ROOT.exists() and str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

PERIOD_ORDER = {"1m": 0, "5m": 1, "15m": 2, "30m": 3, "60m": 4, "1d": 5, "1w": 6}
WEB_MACD_LEGACY_V1_POLICY = "web_macd_legacy_v1"
logger = logging.getLogger(__name__)


def get_workbench_coverage(
    session: Session,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    include_paths: bool = False,
    summary: bool = False,
) -> MarketWorkbenchCoverage | MarketCoverageSummary:
    started = time.perf_counter()
    reader = MarketDataReader(session)
    db_started = time.perf_counter()
    files = reader.get_coverage(symbol=symbol, contract=contract, period=period)
    db_ms = (time.perf_counter() - db_started) * 1000
    files = [item for item in files if item.instrument_symbol and item.contract_code and item.period]
    items = _aggregate_items(session, files, include_paths=include_paths)

    if summary and symbol and contract and period:
        result = _coverage_summary(symbol=symbol, contract=contract, period=period, items=items)
        _log_workbench_coverage(
            symbol=symbol,
            contract=contract,
            period=period,
            file_count=len(files),
            item_count=len(items),
            db_ms=db_ms,
            started=started,
            summary=True,
        )
        return result

    result = MarketWorkbenchCoverage(
        instruments=_group_instruments(items, include_paths=include_paths),
        items=items,
        default_selection=_default_selection(items),
    )
    _log_workbench_coverage(
        symbol=symbol,
        contract=contract,
        period=period,
        file_count=len(files),
        item_count=len(items),
        db_ms=db_ms,
        started=started,
        summary=False,
    )
    return result


def _coverage_summary(
    *,
    symbol: str,
    contract: str,
    period: str,
    items: list[MarketCoverageItem],
) -> MarketCoverageSummary:
    if not items:
        return MarketCoverageSummary(symbol=symbol, contract=contract, period=period, available=False)
    item = items[0]
    return MarketCoverageSummary(
        symbol=item.symbol,
        contract=item.contract,
        period=item.period,
        available=True,
        provider=item.provider,
        start_time=item.start_time,
        end_time=item.end_time,
        row_count=item.row_count,
        quality_status=item.quality_status,
    )


def _log_workbench_coverage(
    *,
    symbol: str | None,
    contract: str | None,
    period: str | None,
    file_count: int,
    item_count: int,
    db_ms: float,
    started: float,
    summary: bool,
) -> None:
    total_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "workbench_coverage symbol=%s contract=%s period=%s summary=%s files=%d items=%d db_ms=%.1f total_ms=%.1f",
        symbol,
        contract,
        period,
        summary,
        file_count,
        item_count,
        db_ms,
        total_ms,
    )
    if total_ms >= 5000:
        logger.warning(
            "slow workbench_coverage total_ms=%.1f symbol=%s contract=%s period=%s",
            total_ms,
            symbol,
            contract,
            period,
        )
    elif total_ms >= 1000:
        logger.info(
            "slow workbench_coverage total_ms=%.1f symbol=%s contract=%s period=%s",
            total_ms,
            symbol,
            contract,
            period,
        )


def get_market_bars(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    start: datetime | None,
    end: datetime | None,
    provider: str | None,
    data_role: str | None,
    limit: int,
    quote_mode: bool = False,
    allow_continuous: bool = False,
    tail: bool = True,
) -> MarketBarsResponse:
    if quote_mode and not allow_continuous:
        validate_quote_contract(contract)
    coverage = _coverage_for_request(session, symbol=symbol, contract=contract, period=period, provider=provider, data_role=data_role)
    start_time = start or coverage.start_time if coverage else start
    end_time = end or coverage.end_time if coverage else end
    query_start = _naive(start_time or datetime.min)
    query_end = _naive(end_time or datetime.max)
    bars = MarketDataReader(session).load_bars(
        symbol=symbol,
        contract=contract,
        period=period,
        start=query_start,
        end=query_end,
        provider=provider,
        data_role=data_role,
        limit=limit,
        tail=tail,
    )
    quality = MarketDataReader(session).get_quality_status(
        symbol=symbol,
        contract=contract,
        period=period,
        start=query_start,
        end=query_end,
        provider=provider,
        data_role=data_role,
    )
    message = None if bars else "当前选择没有可展示的 K 线"
    if bars and quality.get("status") == "warning":
        reasons = quality.get("warning_reasons") or []
        cross_conflicts = quality.get("cross_file_conflicts", 0)
        if cross_conflicts > 0 and cross_conflicts not in reasons:
            reasons = list(reasons) + [f"cross_file_conflicts={cross_conflicts}"]
        reason_text = f"（{', '.join(reasons)}）" if reasons else ""
        message = f"数据质量 warning{reason_text}，仅供观察，不可用于严格研究/回测/信号"
    elif bars and quality.get("cross_file_conflicts", 0) > 0:
        cross_conflicts = quality.get("cross_file_conflicts", 0)
        message = f"检测到 {cross_conflicts} 个跨文件数据冲突，请检查数据源"
    return MarketBarsResponse(
        bars=bars,
        quality=MarketBarsQuality(**quality),
        coverage=coverage,
        request=MarketBarsRequest(
            symbol=symbol,
            contract=contract,
            period=period,
            start=start_time,
            end=end_time,
            provider=provider,
            data_role=data_role,
            limit=limit,
            tail=tail,
        ),
        message=message,
    )


def get_market_macd_indicator(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    start: datetime | None,
    end: datetime | None,
    provider: str | None,
    data_role: str | None,
    limit: int,
    quote_mode: bool = False,
    allow_continuous: bool = False,
    tail: bool = True,
) -> MarketMacdIndicatorResponse:
    bars_response = get_market_bars(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        start=start,
        end=end,
        provider=provider,
        data_role=data_role,
        limit=limit,
        quote_mode=quote_mode,
        allow_continuous=allow_continuous,
        tail=tail,
    )
    bars = bars_response.bars
    closes = [_bar_close(bar) for bar in bars]
    bar_ends = [_bar_time(bar) for bar in bars]
    result = _macd_series()(
        closes,
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        bar_ends=bar_ends,
        round_digits=6,
    )
    histogram_points = _market_indicator_points(result.histogram.points)
    return MarketMacdIndicatorResponse(
        policy=WEB_MACD_LEGACY_V1_POLICY,
        indicator_code=result.indicator_code,
        indicator_version=result.indicator_version,
        parameters=result.parameters,
        basis=result.calculation_basis,
        dif=_market_indicator_points(result.dif.points, ready_mask=result.dea.points),
        dea=_market_indicator_points(result.dea.points),
        histogram=histogram_points,
        source_bar_count=len(bars),
        ready_count=sum(1 for point in histogram_points if point.ready and point.valid and point.value is not None),
        coverage=bars_response.coverage,
        request=bars_response.request,
        message=bars_response.message,
    )


def _macd_series():
    from guiyi_quant.indicators import macd_series

    return macd_series


def _bar_close(bar: dict[str, Any]) -> float | None:
    value = bar.get("close")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _bar_time(bar: dict[str, Any]) -> str | None:
    value = bar.get("time") or bar.get("datetime")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _market_indicator_points(points, *, ready_mask=None) -> list[MarketMacdIndicatorPoint]:
    response_points: list[MarketMacdIndicatorPoint] = []
    for index, point in enumerate(points):
        mask = ready_mask[index] if ready_mask is not None else None
        if mask is not None and point.valid and not (mask.ready and mask.valid and mask.value is not None):
            response_points.append(
                MarketMacdIndicatorPoint(
                    time=point.bar_end,
                    value=None,
                    ready=False,
                    valid=True,
                    reason=mask.reason or "warming_up",
                )
            )
            continue
        response_points.append(
            MarketMacdIndicatorPoint(
                time=point.bar_end,
                value=point.value,
                ready=point.ready,
                valid=point.valid,
                reason=point.reason,
            )
        )
    return response_points


def _aggregate_items(session: Session, files: list[MarketDataFile], *, include_paths: bool = False) -> list[MarketCoverageItem]:
    contracts = {
        item.contract_code: item
        for item in session.scalars(select(Contract).where(Contract.contract_code.in_({file.contract_code for file in files})))
    }
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for file in files:
        key = (file.instrument_symbol or "", file.contract_code or "", file.period or "", file.provider, file.data_type)
        record = grouped.setdefault(
            key,
            {
                "symbol": file.instrument_symbol or "",
                "contract": file.contract_code or "",
                "period": file.period or "",
                "provider": file.provider,
                "data_type": file.data_type,
                "start_time": file.start_time,
                "end_time": file.end_time,
                "row_count": 0,
                "statuses": [],
                "data_versions": [],
                "data_roles": [],
                "file_paths": [],
            },
        )
        record["start_time"] = min(record["start_time"], file.start_time)
        record["end_time"] = max(record["end_time"], file.end_time)
        record["row_count"] += file.row_count or 0
        record["statuses"].append(file.quality_status)
        record["data_versions"].append(file.data_version)
        record["data_roles"].append(file.data_role)
        record["file_paths"].append(file.file_path)

    items: list[MarketCoverageItem] = []
    for record in grouped.values():
        contract = contracts.get(record["contract"])
        view = _contract_view_metadata(record["symbol"], record["contract"])
        items.append(
            MarketCoverageItem(
                symbol=record["symbol"],
                contract=record["contract"],
                period=record["period"],
                provider=record["provider"],
                data_type=record["data_type"],
                view_role=view["view_role"],
                continuous_contract=view["continuous_contract"],
                actual_contract=view["actual_contract"],
                exchange=contract.exchange_code if contract else None,
                name=contract.name if contract else None,
                start_time=record["start_time"],
                end_time=record["end_time"],
                latest_bar_time=record["end_time"],
                row_count=record["row_count"],
                quality_status=_aggregate_status(record["statuses"]),
                data_version=_join_distinct(record["data_versions"]),
                data_role=_join_distinct(record["data_roles"]),
                file_path=_join_distinct(record["file_paths"]) if include_paths else None,
            )
        )
    return sorted(items, key=lambda item: (item.symbol, item.contract, _period_rank(item.period), item.start_time))


def _group_instruments(items: list[MarketCoverageItem], *, include_paths: bool = False) -> list[MarketCoverageInstrument]:
    by_symbol: dict[str, list[MarketCoverageItem]] = defaultdict(list)
    for item in items:
        by_symbol[item.symbol].append(item)

    instruments: list[MarketCoverageInstrument] = []
    for symbol, symbol_items in sorted(by_symbol.items()):
        contract_groups: dict[str, list[MarketCoverageItem]] = defaultdict(list)
        for item in symbol_items:
            contract_groups[item.contract].append(item)
        contracts = [
            MarketCoverageContract(
                contract=contract,
                name=contract_items[0].name,
                exchange=contract_items[0].exchange,
                provider=contract_items[0].provider,
                status=None,
                view_role=contract_items[0].view_role,
                continuous_contract=contract_items[0].continuous_contract,
                actual_contract=contract_items[0].actual_contract,
                periods=[
                    MarketCoveragePeriod(
                        period=item.period,
                        provider=item.provider,
                        data_type=item.data_type,
                        source_mode=item.source_mode,
                        view_role=item.view_role,
                        continuous_contract=item.continuous_contract,
                        actual_contract=item.actual_contract,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        latest_bar_time=item.latest_bar_time,
                        row_count=item.row_count,
                        quality_status=item.quality_status,
                        data_version=item.data_version,
                        data_role=item.data_role,
                        file_path=item.file_path if include_paths else None,
                    )
                    for item in sorted(contract_items, key=lambda value: _period_rank(value.period))
                ],
            )
            for contract, contract_items in sorted(contract_groups.items())
        ]
        instruments.append(
            MarketCoverageInstrument(
                symbol=symbol,
                name=symbol_items[0].name,
                exchange=symbol_items[0].exchange,
                sector=None,
                contracts=contracts,
            )
        )
    return instruments


def _default_selection(items: list[MarketCoverageItem]) -> MarketWorkbenchSelection | None:
    if not items:
        return None
    actual_items = [item for item in items if not is_continuous_contract(item.contract)]
    preferred = next(
        (
            item
            for item in actual_items
            if item.symbol == "jm" and item.period == DEFAULT_QUOTE_PERIOD and item.quality_status == "passed"
        ),
        None,
    )
    fallback_actual = next((item for item in actual_items if item.period == DEFAULT_QUOTE_PERIOD), None)
    fallback_period = next((item for item in actual_items if item.period == "5m"), None)
    selected = preferred or fallback_actual or fallback_period or (actual_items[0] if actual_items else None)
    if selected is None:
        selected = next((item for item in items if item.symbol == "rb" and item.contract == "rb.MAIN" and item.period == "5m"), None)
    selected = selected or next((item for item in items if item.period == "5m"), None) or items[0]
    return MarketWorkbenchSelection(
        symbol=selected.symbol,
        contract=selected.contract,
        period=selected.period,
        provider=selected.provider,
        start=selected.start_time,
        end=selected.end_time,
    )


def _coverage_for_request(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    provider: str | None,
    data_role: str | None,
) -> MarketBarsCoverage | None:
    files = MarketDataReader(session).get_coverage(symbol=symbol, contract=contract, period=period, data_role=data_role)
    if provider is not None:
        files = [file for file in files if file.provider == provider]
    items = _aggregate_items(session, files, include_paths=True)
    if not items:
        return None
    item = items[0]
    return MarketBarsCoverage(
        symbol=item.symbol,
        contract=item.contract,
        period=item.period,
        provider=item.provider,
        data_type=item.data_type,
        view_role=item.view_role,
        continuous_contract=item.continuous_contract,
        actual_contract=item.actual_contract,
        start_time=item.start_time,
        end_time=item.end_time,
        latest_bar_time=item.latest_bar_time,
        row_count=item.row_count,
        quality_status=item.quality_status,
        data_version=item.data_version,
        data_role=item.data_role,
        file_path=item.file_path,
    )


def _aggregate_status(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    if "unchecked" in statuses:
        return "unchecked"
    return "passed" if statuses else "unchecked"


def _period_rank(period: str) -> int:
    return PERIOD_ORDER.get(period, 99)


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _contract_view_metadata(symbol: str, contract: str) -> dict[str, str | None]:
    continuous_contract = continuous_contract_for(symbol) if symbol else None
    if is_continuous_contract(contract):
        return {
            "view_role": "continuous",
            "continuous_contract": contract,
            "actual_contract": None,
        }
    return {
        "view_role": "actual_contract",
        "continuous_contract": continuous_contract,
        "actual_contract": contract,
    }


def _join_distinct(values: list[str | None]) -> str | None:
    normalized = sorted({value for value in values if value})
    if not normalized:
        return None
    return ", ".join(normalized)
