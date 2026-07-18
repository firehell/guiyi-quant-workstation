from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.schemas.market import (
    MarketIndicatorPoint,
    MarketIndicatorSeries,
    MarketIndicatorsRequest,
    MarketIndicatorsResponse,
    MarketIndicatorsWarmup,
)
from app.services.market_dominant_reader import validate_quote_contract
from app.services.market_workbench import MarketAccessError, get_market_bars

MAX_DISPLAY_BAR_COUNT = 10000
SUPPORTED_EMA_CODES = {"ema10", "ema21", "ema60"}


def get_market_indicators(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    indicator_codes: list[str],
    display_start: datetime | None,
    display_end: datetime | None,
    display_bar_count: int,
    provider: str | None,
    data_role: str | None,
    profile_id: str | None = None,
    access_mode: str = "browser",
    expected_market_data_file_id: int | None = None,
    expected_lineage_token: str | None = None,
    quote_mode: bool = False,
    allow_continuous: bool = False,
) -> MarketIndicatorsResponse:
    _ensure_quant_core_path()
    from guiyi_quant.indicators import ema_series, get_indicator

    if quote_mode and not allow_continuous:
        validate_quote_contract(contract)

    requested_codes = _normalize_codes(indicator_codes)
    definitions = []
    for code in requested_codes:
        try:
            definition = get_indicator(code)
        except KeyError:
            continue
        if (
            definition.status != "validated"
            or not definition.web_capable
            or definition.repainting_risk != "none"
            or definition.indicator_code not in SUPPORTED_EMA_CODES
        ):
            continue
        definitions.append(definition)

    display_count = max(1, min(display_bar_count, MAX_DISPLAY_BAR_COUNT))
    max_warmup = max((definition.warmup_bars for definition in definitions), default=0)
    if access_mode == "research" and (expected_market_data_file_id is None or expected_lineage_token is None):
        raise MarketAccessError(
            "MARKET_LINEAGE_CHANGED",
            "research indicators require the bars lineage snapshot",
            status_code=409,
            context={"profile_id": profile_id, "symbol": symbol, "contract": contract, "period": period},
        )
    bars_response = get_market_bars(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        start=None,
        end=display_end,
        provider=provider,
        data_role=data_role,
        limit=MAX_DISPLAY_BAR_COUNT,
        tail=True,
        profile_id=profile_id,
        access_mode=access_mode,
        expected_market_data_file_id=expected_market_data_file_id,
        expected_lineage_token=expected_lineage_token,
        quote_mode=quote_mode,
        allow_continuous=allow_continuous,
    )
    bars = bars_response.bars
    display_bars = _display_bars(bars, display_start=display_start, display_end=display_end, display_count=display_count)
    display_times = {_bar_time(_bar) for _bar in display_bars}
    calculation_start = _bar_time(bars[0]) if bars else None
    data_version = _joined_data_versions(bars)
    read_limit = len(bars)

    indicators: list[MarketIndicatorSeries] = []
    closes = [_bar["close"] for _bar in bars]
    bar_ends = [_bar_time(_bar).isoformat() for _bar in bars]

    for definition in definitions:
        period_param = int(definition.default_parameters["period"])
        series = ema_series(
            closes,
            period_param,
            bar_ends=bar_ends,
            seed_policy="sma_window",
            indicator_code=definition.indicator_code,
            round_digits=int(definition.default_parameters.get("round_digits", 6)),
        )
        points = [
            MarketIndicatorPoint(
                time=_parse_bar_end(point.bar_end),
                value=point.value,
                ready=point.ready,
                valid=point.valid,
                reason=point.reason,
            )
            for point in series.points
            if point.bar_end is not None and _parse_bar_end(point.bar_end) in display_times
        ]
        indicators.append(
            MarketIndicatorSeries(
                id=_indicator_id(definition.indicator_code),
                indicator_code=definition.indicator_code,
                display_name=definition.display_name,
                indicator_version=series.indicator_version,
                parameters=series.parameters,
                parameters_hash=series.parameters_hash,
                seed_policy=str(series.parameters.get("seed_policy", definition.default_parameters.get("seed_policy", ""))),
                calculation_start=calculation_start,
                warmup_bars=int(series.calculation_basis.get("warmup_bars", definition.warmup_bars)),
                confirmed_only=definition.closed_bar_only,
                data_version=data_version,
                calculation_source=definition.calculation_source,
                repainting_risk=series.repainting_risk,
                points=points,
            )
        )

    return MarketIndicatorsResponse(
        request=MarketIndicatorsRequest(
            symbol=symbol,
            contract=contract,
            period=period,
            indicator_codes=requested_codes,
            display_start=display_start,
            display_end=display_end,
            display_bar_count=display_count,
            provider=provider,
            data_role=data_role,
            profile_id=profile_id,
            access_mode=access_mode,
            expected_market_data_file_id=expected_market_data_file_id,
            expected_lineage_token=expected_lineage_token,
            quote_mode=quote_mode,
            allow_continuous=allow_continuous,
            read_limit=read_limit,
        ),
        warmup=MarketIndicatorsWarmup(
            requested_display_bar_count=display_count,
            max_warmup_bars=max_warmup,
            read_limit=read_limit,
            source_bar_count=len(bars),
            display_bar_count=len(display_bars),
        ),
        indicators=indicators,
        lineage=bars_response.lineage,
        strict_research_ready=bars_response.strict_research_ready,
        message=None if indicators else "当前请求没有可用的 validated Web EMA 指标",
    )


def _normalize_codes(codes: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_code in codes:
        for item in str(raw_code).split(","):
            code = item.strip()
            if code and code not in normalized:
                normalized.append(code)
    return normalized


def _is_in_display_window(bar: dict[str, Any], display_start: datetime | None, display_end: datetime | None) -> bool:
    time = _bar_time(bar)
    if display_start is not None and time < display_start:
        return False
    if display_end is not None and time > display_end:
        return False
    return True


def _display_bars(
    bars: list[dict[str, Any]],
    *,
    display_start: datetime | None,
    display_end: datetime | None,
    display_count: int,
) -> list[dict[str, Any]]:
    window = [_bar for _bar in bars if _is_in_display_window(_bar, display_start, display_end)]
    if len(window) <= display_count:
        return window
    return window[-display_count:]


def _joined_data_versions(bars: list[dict[str, Any]]) -> str | None:
    versions = []
    for bar in bars:
        version = bar.get("data_version")
        if version and version not in versions:
            versions.append(str(version))
    return ",".join(versions) if versions else None


def _bar_time(bar: dict[str, Any]) -> datetime:
    value = bar.get("datetime") or bar.get("time")
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _parse_bar_end(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _indicator_id(indicator_code: str) -> str:
    if indicator_code.startswith("ema"):
        return f"ema_{indicator_code[3:]}"
    return indicator_code


def _ensure_quant_core_path() -> None:
    path = str(Path(PROJECT_ROOT) / "packages" / "quant-core")
    if path not in sys.path:
        sys.path.insert(0, path)
