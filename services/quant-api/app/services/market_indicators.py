from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

from app.core.env import PROJECT_ROOT
from app.schemas.market import (
    CanonicalBarsResponse,
    CanonicalMacdRequest,
    CanonicalMarketIndicatorsResponse,
    CanonicalMarketMacdIndicatorResponse,
    MarketIndicatorPoint,
    MarketIndicatorSeries,
    MarketIndicatorsRequest,
    MarketIndicatorsWarmup,
)
from app.schemas.market import MarketMacdIndicatorPoint

MAX_DISPLAY_BAR_COUNT = 10000
SUPPORTED_EMA_CODES = {"ema10", "ema21", "ema60"}

WEB_MACD_LEGACY_V1_POLICY = "web_macd_legacy_v1"


class MarketAccessError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422, context: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, "context": self.context}




def get_canonical_market_macd_indicator(
    bars_response: CanonicalBarsResponse,
) -> CanonicalMarketMacdIndicatorResponse:
    payload = calculate_web_macd_payload(bars_response.bars)
    request = bars_response.request
    return CanonicalMarketMacdIndicatorResponse(
        **payload,
        coverage=bars_response.coverage,
        request=CanonicalMacdRequest(
            **request.model_dump(),
            expected_lineage_token=bars_response.lineage.lineage_token,
        ),
        lineage=bars_response.lineage,
        strict_research_ready=bars_response.strict_research_ready,
        message=bars_response.message,
        data_identity=bars_response.data_identity,
    )


def get_canonical_market_indicators(
    bars_response: CanonicalBarsResponse,
    *,
    indicator_codes: list[str],
    display_bar_count: int,
    display_start: datetime | None = None,
    display_end: datetime | None = None,
) -> CanonicalMarketIndicatorsResponse:
    """Calculate the unchanged public EMA formulas over verified V2 bars."""
    _ensure_quant_core_path()
    from guiyi_quant.indicators import ema_series, get_indicator

    requested_codes = _normalize_codes(indicator_codes)
    definitions = []
    for code in requested_codes:
        try:
            definition = get_indicator(code)
        except KeyError:
            continue
        if (
            definition.status == "validated"
            and definition.web_capable
            and definition.repainting_risk == "none"
            and definition.indicator_code in SUPPORTED_EMA_CODES
        ):
            definitions.append(definition)
    display_count = max(1, min(display_bar_count, MAX_DISPLAY_BAR_COUNT))
    source_bars = bars_response.bars
    bars = _display_bars(
        source_bars,
        display_start=display_start,
        display_end=display_end,
        display_count=display_count,
    )
    display_times = {_bar_time(bar) for bar in bars}
    closes = [bar["close"] for bar in source_bars]
    bar_ends = [_bar_time(bar).isoformat() for bar in source_bars]
    indicators: list[MarketIndicatorSeries] = []
    for definition in definitions:
        series = ema_series(
            closes,
            int(definition.default_parameters["period"]),
            bar_ends=bar_ends,
            seed_policy="sma_window",
            indicator_code=definition.indicator_code,
            round_digits=int(
                definition.default_parameters.get("round_digits", 6)
            ),
        )
        indicators.append(
            MarketIndicatorSeries(
                id=_indicator_id(definition.indicator_code),
                indicator_code=definition.indicator_code,
                display_name=definition.display_name,
                indicator_version=series.indicator_version,
                parameters=series.parameters,
                parameters_hash=series.parameters_hash,
                seed_policy=str(series.parameters["seed_policy"]),
                calculation_start=_bar_time(source_bars[0]) if source_bars else None,
                warmup_bars=int(series.calculation_basis["warmup_bars"]),
                confirmed_only=definition.closed_bar_only,
                data_version=None,
                calculation_source=definition.calculation_source,
                repainting_risk=series.repainting_risk,
                points=[
                    MarketIndicatorPoint(
                        time=_parse_bar_end(point.bar_end),
                        value=point.value,
                        ready=point.ready,
                        valid=point.valid,
                        reason=point.reason,
                    )
                    for point in series.points
                    if point.bar_end is not None
                    and _parse_bar_end(point.bar_end) in display_times
                ],
            )
        )
    request = bars_response.request
    resolved_contract = (
        request.contract_or_series
        or bars_response.coverage.actual_contract
        or bars_response.coverage.continuous_contract
        or f"{request.symbol}.MAIN"
    )
    return CanonicalMarketIndicatorsResponse(
        request=MarketIndicatorsRequest(
            symbol=request.symbol,
            contract=resolved_contract,
            period=request.frequency,
            indicator_codes=requested_codes,
            display_start=display_start or request.start,
            display_end=display_end or request.end,
            display_bar_count=display_count,
            provider="rqdata",
            data_role="primary",
            profile_id=None,
            access_mode="research",
            expected_market_data_file_id=None,
            expected_lineage_token=bars_response.lineage.lineage_token,
            quote_mode=False,
            allow_continuous=request.dataset_kind == "continuous",
            read_limit=len(source_bars),
        ),
        warmup=MarketIndicatorsWarmup(
            requested_display_bar_count=display_count,
            max_warmup_bars=max(
                (definition.warmup_bars for definition in definitions),
                default=0,
            ),
            read_limit=len(source_bars),
            source_bar_count=len(source_bars),
            display_bar_count=len(bars),
        ),
        indicators=indicators,
        lineage=bars_response.lineage,
        strict_research_ready=True,
        message=None if indicators else "当前请求没有可用的 validated Web EMA 指标",
        data_identity=bars_response.data_identity,
    )


def calculate_web_macd_payload(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate the frozen Web MACD formula without selecting a data source."""
    closes = [_macd_bar_close(bar) for bar in bars]
    bar_ends = [_macd_bar_time(bar) for bar in bars]
    from guiyi_quant.indicators import macd_series
    result = macd_series(
        closes,
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        bar_ends=bar_ends,
        round_digits=6,
    )
    histogram_points = _macd_indicator_points(result.histogram.points)
    return {
        "policy": WEB_MACD_LEGACY_V1_POLICY,
        "indicator_code": result.indicator_code,
        "indicator_version": result.indicator_version,
        "parameters": result.parameters,
        "basis": result.calculation_basis,
        "dif": _macd_indicator_points(result.dif.points, ready_mask=result.dea.points),
        "dea": _macd_indicator_points(result.dea.points),
        "histogram": histogram_points,
        "source_bar_count": len(bars),
        "ready_count": sum(
            1 for point in histogram_points if point.ready and point.valid and point.value is not None
        ),
    }


def _macd_bar_close(bar: dict[str, Any]) -> float | None:
    value = bar.get("close")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _macd_bar_time(bar: dict[str, Any]) -> str | None:
    value = bar.get("time") or bar.get("datetime")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _macd_indicator_points(points, *, ready_mask=None) -> list[MarketMacdIndicatorPoint]:
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
    normalized_start = _naive_utc(display_start)
    normalized_end = _naive_utc(display_end)
    if normalized_start is not None and time < normalized_start:
        return False
    if normalized_end is not None and time > normalized_end:
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


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


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
