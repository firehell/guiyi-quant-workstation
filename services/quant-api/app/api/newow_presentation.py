"""Pure Newow wire presentation, independent of HTTP composition and policies."""

from __future__ import annotations

from app.market_data.newow.read_timings import timed

from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from math import isfinite
from hashlib import sha256
import json
from collections.abc import Mapping
from guiyi_quant.newow.models import CupPivot, NewowCupHandleOverlay, NewowMainMarker
from app.market_data.newow.product_service import (
    NewowProductResult,
    PersistedReferenceSectionValue,
)
from app.market_data.newow.trend_detail_service import (
    NewowTrendDetailError,
    NewowTrendDetailResult,
)
from app.schemas.market_newow import (
    NewowBarOut,
    NewowCupHandleOut,
    NewowCupPivotOut,
    NewowInstrumentOut,
    NewowMarkerOut,
    NewowMetaOut,
    NewowRolloverSeamOut,
    NewowTrendBandOut,
    NewowTrendDetailResponse,
)
from app.schemas.market_newow_product import NewowProductResponse

_TREND_MARKERS = frozenset({"BUILD", "CLEAR"})
_ESCAPE_MARKERS = frozenset({"NEWOW_ESCAPE_D1", "NEWOW_ESCAPE_D2", "NEWOW_ESCAPE_D3"})
_CUP_MARKERS = frozenset(
    {
        "CUP_HANDLE_READY",
        "CUP_HANDLE_BREAKOUT",
        "CUP_HANDLE_WEAKENED",
        "CUP_HANDLE_INVALIDATED",
        "CUP_HANDLE_EXPIRED",
    }
)


def _status(value) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "status": value.status.value,
        "evidence_status": value.evidence_status.value,
        "reason_code": value.reason_code,
    }


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _auxiliary_data_value(component: str, value: object) -> object:
    payload = _json_value(value)
    if component == "zhaoyao_mirror" and isinstance(payload, dict):
        # Internal causal peak events are consumed by hints, not the retrospective subplot wire.
        payload.pop("confirmed_peak_events", None)
    return payload


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        return format(value, "f")
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise ValueError("NEWOW_DATA_IDENTITY_INVALID")


def _bar(item) -> dict[str, object]:
    bar = item.bar
    return {
        "bar_end": bar.bar_end,
        "trading_day": bar.trading_day,
        "open": _decimal(bar.open),
        "high": _decimal(bar.high),
        "low": _decimal(bar.low),
        "close": _decimal(bar.close),
        "volume": bar.volume,
        "open_interest": bar.open_interest,
        "physical_contract": bar.physical_contract,
        "segment_id": bar.segment_id,
        "calculation_segment_id": item.calculation_segment_id,
        "source_identity": bar.source_identity,
        "observation_eligible": bar.observation_eligible,
        "completed": True,
    }


def _trade(item, entry_sequence: int) -> dict[str, object]:
    payload = {
        field.name: (
            _decimal(value)
            if isinstance(value, Decimal)
            else value.value
            if isinstance(value, Enum)
            else list(value)
            if field.name in {"formula_versions", "hint_ids"}
            else value
        )
        for field in fields(item)
        if (value := getattr(item, field.name)) is not None
        or field.name
        in {
            "exit_signal_id",
            "exit_bar_end",
            "exit_trading_day",
            "exit_reference_price",
            "reference_return_pct",
            "mark_bar_end",
            "mark_reference_price",
            "mark_change_pct",
            "interrupted_at",
            "interruption_reason",
            "statistics_membership",
        }
    }
    if payload.get("input_quality_policy") == "newow_input_quality_v1":
        payload.pop("input_quality_policy")
    payload["entry_sequence"] = entry_sequence
    return payload


def _delivery(value, serializer) -> dict[str, object]:
    return {
        "delivery": value.delivery,
        "status": _status(value.status),
        "value": None if value.value is None else serializer(value.value),
    }


@timed("projection")
def _product_response(
    result: NewowProductResult, *, reference_part: str | None = None,
    reference_mode: str | None = None, history_before: str | None = None,
) -> NewowProductResponse:
    meta = result.meta
    identity = meta.identity
    chart = _delivery(
        result.chart,
        lambda value: {
            "chart_from": value.actual_window.since,
            "chart_through": value.actual_window.through,
            "page_identity": value.page_identity,
            "price_unavailable_days": [
                {
                    "trading_day": day,
                    "physical_contract": contract,
                    "segment_id": segment_id,
                }
                for day, contract, segment_id in value.price_unavailable_days
            ],
            "bars": [_bar(item) for item in value.bars],
            "frames": [
                {
                    "bar_end": frame.bar.bar.bar_end,
                    "main_state": frame.main_state.value,
                    "main_values": {
                        key: _decimal(item) for key, item in frame.main_values
                    },
                    "status": _status(frame.availability),
                    "action_ids": [action.signal_id for action in frame.actions],
                    "hint_ids": [hint.hint_id for hint in frame.hints],
                }
                for frame in value.replay.frames
            ],
            "trend_channel": None
            if value.trend_channel is None
            else {
                "kind": value.trend_channel.kind,
                "period": value.trend_channel.period,
                "formula_version": value.trend_channel.formula_version,
                "points": [
                    {
                        "bar_end": point.bar_end,
                        "upper": _decimal(point.upper),
                        "lower": _decimal(point.lower),
                        "formula_version": point.formula_version,
                        "status": _status(point.availability),
                        "physical_contract": point.physical_contract,
                        "segment_id": point.segment_id,
                        "source_identity": point.source_identity,
                        "calculation_segment_id": point.calculation_segment_id,
                    }
                    for point in value.trend_channel.points
                ],
            },
            "price_reference": None
            if value.price_reference is None
            else {
                "surface": value.price_reference.surface,
                "frequency": value.price_reference.frequency.value,
                "as_of": value.price_reference.as_of,
                "anchor_bar_end": value.price_reference.anchor_bar_end,
                "physical_contract": value.price_reference.physical_contract,
                "segment_id": value.price_reference.segment_id,
                "calculation_segment_id": value.price_reference.calculation_segment_id,
                "input_sha256": value.price_reference.input_sha256,
                "formula_version": value.price_reference.formula_version,
                "adapter_version": value.price_reference.adapter_version,
                "target": {
                    "raw": _decimal(value.price_reference.target.raw),
                    "display": value.price_reference.target.display,
                    "status": _status(value.price_reference.target.status),
                },
                "absorb": {
                    "raw": _decimal(value.price_reference.absorb.raw),
                    "display": value.price_reference.absorb.display,
                    "status": _status(value.price_reference.absorb.status),
                },
            },
            "actions": [
                {
                    "signal_id": item.signal_id,
                    "kind": item.kind.value,
                    "bar_end": item.bar_end,
                    "trading_day": item.trading_day,
                    "reference_price": _decimal(item.reference_price),
                    "physical_contract": item.physical_contract,
                    "segment_id": item.segment_id,
                    "calculation_segment_id": item.calculation_segment_id,
                    "related_build_id": item.related_build_id,
                    "trade_eligibility": item.trade_eligibility.value,
                    "sequence": item.sequence,
                }
                for item in value.replay.actions
            ],
            "hints": [
                {
                    "hint_id": item.hint_id,
                    "kind": item.kind,
                    "bar_end": item.bar_end,
                    "known_at": item.known_at,
                    "anchor_price": _decimal(item.anchor_price),
                    "physical_contract": item.physical_contract,
                    "segment_id": item.segment_id,
                    "calculation_segment_id": item.calculation_segment_id,
                    "retrospective": False,
                    "quantity_effect": "none",
                    "sequence": item.sequence,
                }
                for item in value.replay.hints
            ],
            "diagnostics": list(value.diagnostics),
            "next_before": value.next_before,
            "next_older_window": value.next_older_window,
            "repainting": False,
            "formal_signal_eligible": True,
            "allowed_uses": ["product_chart", "reference_input"],
        },
    )
    reference = _delivery(
        result.reference,
        lambda value: (
            value.payload
            if isinstance(value, PersistedReferenceSectionValue)
            else {
                "performance_since": value.requested_window.since,
                "performance_through": value.requested_window.through,
                "actual_available_through": value.actual_available_through,
                "reference_cutoff": value.reference_cutoff,
                "reference_input_sha256": value.reference_input_sha256,
                **({
                    "record_since": value.requested_window.since,
                    "records_window_limited": False,
                    "result_identity_sha256": sha256(json.dumps([
                        _trade(item, dict(value.entry_sequences)[item.entry_signal_id])
                        for item in value.projection.trades
                    ], sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
                } if reference_part is not None else {}),
                "history_coverage": value.history_coverage,
                "theoretical": value.theoretical,
                "holding_curve": value.holding_curve,
                "page_performance": value.page_performance,
                "unavailable_days": list(value.unavailable_days),
                "coverage_intervals": [
                    {
                        "since": interval.since,
                        "through": interval.through,
                        "status": interval.status,
                        "physical_contract": interval.physical_contract,
                        "segment_id": interval.segment_id,
                        "calculation_segment_id": interval.calculation_segment_id,
                    }
                    for interval in value.coverage_intervals
                ],
                "summary": {
                    "membership_policy": value.summary.membership_policy,
                    "closed_count": value.summary.closed_count,
                    "win_count": value.summary.win_count,
                    "loss_count": value.summary.loss_count,
                    "flat_count": value.summary.flat_count,
                    "win_rate_pct": _decimal(value.summary.win_rate_pct),
                    "mean_return_pct": _decimal(value.summary.mean_return_pct),
                    "sum_return_percentage_points": _decimal(
                        value.summary.sum_return_percentage_points
                    ),
                    "open_count": value.summary.open_count,
                    "interrupted_count": value.summary.interrupted_count,
                    "rollover_interrupted_count": value.summary.rollover_interrupted_count,
                    "data_interrupted_count": value.summary.data_interrupted_count,
                    "initial_count": value.summary.initial_count,
                },
                "items": [
                    _trade(item, dict(value.entry_sequences)[item.entry_signal_id])
                    for item in value.items
                ],
                "curve_trades": sorted(
                    [
                        _trade(item, dict(value.entry_sequences)[item.entry_signal_id])
                        for item in value.summary.closed_trades
                    ],
                    key=lambda item: (
                        item["entry_bar_end"],
                        item["entry_sequence"],
                        item["reference_trade_id"],
                    ),
                    reverse=True,
                ),
                **(
                    {"fusion_comparison": value.fusion_comparison}
                    if value.fusion_comparison is not None
                    else {}
                ),
                "next_before": value.next_before,
                "executable": False,
                "auto_order": False,
                "allowed_uses": ["page_parity_reference", "research_display"],
            }
        ),
    )
    if reference_part is None and reference["value"] is not None:
        reference["value"] = {key: item for key, item in reference["value"].items()
                              if key not in {"record_since", "records_window_limited",
                                             "result_identity_sha256"}}
    if reference_part is not None and reference["value"] is not None:
        from .newow_reference_parts import project_reference_part
        reference["value"] = project_reference_part(
            reference["value"], reference_part, reference_mode,
            history_before=history_before, snapshot_token=result.meta.snapshot_token,
            as_of=result.meta.as_of.isoformat(),
            calculation_version=result.meta.reference_model_version,
        )
    auxiliary = _delivery(
        result.auxiliary,
        lambda value: {
            "component": value.name,
            **(
                {
                    "display_adapter_version": value.display_adapter_version,
                    "parameters": value.parameters,
                    "parameters_hash": value.parameters_hash,
                }
                if value.name == "macd"
                else {}
            ),
            "formula_version": value.formula_version,
            "segments": [
                {
                    "physical_contract": segment.physical_contract,
                    "segment_id": segment.segment_id,
                    "bar_ends": list(segment.bar_ends),
                    "status": _status(segment.status),
                    "data": _auxiliary_data_value(value.name, segment.value),
                }
                for segment in value.segments
            ],
            "repainting": value.repainting,
            "formal_signal_eligible": value.formal_signal_eligible,
            "page_parity": value.page_parity,
            "source_category": "guiyi_product_auxiliary_adapter",
            "allowed_uses": ["research_display"]
            if value.name == "macd"
            else ["retrospective_display"]
            if value.repainting
            else ["product_display"],
        },
    )
    explanation = _delivery(
        result.explanation,
        lambda value: {
            **(
                {"decision_v2": value.decision_v2}
                if value.decision_v2 is not None
                else {}
            ),
            "context": _context_value(value.context),
            "composite": _json_value(value.composite),
            "target_absorb": _json_value(value.target_absorb),
            "sources": [_json_value(source) for source in value.sources],
            "page_parity": False,
            "allowed_uses": ["research_explanation", "product_display"],
        },
    )
    comparator = _delivery(
        result.comparator,
        lambda value: {
            "result": _json_value(value),
            "executable": False,
            "page_parity": False,
            "synthetic_terminal_is_reference_exit": False,
            "allowed_uses": ["in_sample_comparison"],
        },
    )
    payload = {
        "meta": {
            "schema_version": meta.schema_version,
            "identity": {
                "product": identity.product,
                "strategy": identity.strategy.value,
                "frequency": identity.frequency.value,
                "series_kind": identity.series_kind,
                "profile_id": identity.profile_id,
                "formula_versions": list(identity.formula_versions),
            },
            "as_of": meta.as_of,
            "read_at": meta.read_at,
            "input_content_sha256": meta.input_content_sha256,
            "data_revision_identity": None,
            "snapshot_token": meta.snapshot_token,
            "reference_model_version": meta.reference_model_version,
            "futures_adaptation_version": meta.futures_adaptation_version,
        },
        "section": result.section.value,
        "chart": chart,
        "auxiliary": auxiliary,
        "reference": reference,
        "explanation": explanation,
        "comparator": comparator,
    }
    if identity.input_quality_policy.value != "newow_input_quality_v1":
        payload["meta"]["identity"]["input_quality_policy"] = (
            identity.input_quality_policy.value
        )
    return NewowProductResponse.model_validate(payload)


def _context_value(context) -> dict[str, object]:
    def slot(value) -> dict[str, object]:
        identity = value.identity
        return {
            "frequency": value.frequency.value,
            "as_of": value.as_of,
            "availability": _status(value.availability),
            "confirmation_status": _status(value.confirmation_status),
            "identity": None
            if identity is None
            else {
                "product": identity.product,
                "strategy": identity.strategy.value,
                "frequency": identity.frequency.value,
                "series_kind": identity.series_kind,
                "profile_id": identity.profile_id,
                "formula_versions": list(identity.formula_versions),
            },
            "bar_end": value.bar_end,
            "source_identity": value.source_identity,
            "physical_contract": value.physical_contract,
            "segment_id": value.segment_id,
            "formula_versions": list(value.formula_versions),
            "main_state": None if value.frame is None else value.frame.main_state.value,
        }

    return {
        "as_of": context.as_of,
        "weekly": slot(context.weekly),
        "daily": slot(context.daily),
        "hourly": slot(context.hourly),
        "missing_frequencies": [value.value for value in context.missing_frequencies],
        "recompute_mode": context.recompute_mode,
        "historical_database_knowledge_reconstructed": context.historical_database_knowledge_reconstructed,
    }


def _response(result: NewowTrendDetailResult) -> NewowTrendDetailResponse:
    markers = tuple(_marker(marker) for marker in result.markers)
    return NewowTrendDetailResponse(
        meta=NewowMetaOut(
            strategy_code="newow_trend_v1",
            profile_id=result.instrument.profile_id,
            frequency=result.instrument.frequency,
            series_kind=result.instrument.series_kind,
            calculation_identity=result.calculation_identity,
            data_revision_identity=result.data_revision_identity,
            request_identity=result.request_identity,
        ),
        instrument=NewowInstrumentOut(
            product=result.instrument.product,
            display_name=result.instrument.display_name,
            last_visible_physical_contract=result.instrument.last_visible_physical_contract,
        ),
        bars=[
            NewowBarOut(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                open_interest=bar.open_interest,
                physical_contract=bar.physical_contract,
                segment_id=bar.segment_id,
                source_identity=bar.source_identity,
            )
            for bar in result.bars
        ],
        bar_policy="completed_only",
        trend_band=[
            NewowTrendBandOut(
                bar_end=frame.bar.bar_end,
                b_value=frame.trend_band.b_value,
                c_value=frame.trend_band.c_value,
                state=frame.trend_band.state.value,
                state_before=(
                    frame.trend_band.state_before.value
                    if frame.trend_band.state_before is not None
                    else None
                ),
                transition=(
                    frame.trend_band.transition.value
                    if frame.trend_band.transition is not None
                    else None
                ),
            )
            for frame in result.frames
        ],
        trend_markers=[item for item in markers if item.marker_type in _TREND_MARKERS],
        escape_markers=[
            item for item in markers if item.marker_type in _ESCAPE_MARKERS
        ],
        cup_markers=[item for item in markers if item.marker_type in _CUP_MARKERS],
        cup_handles=[_cup_handle(item) for item in result.cup_handles],
        rollover_seams=[
            NewowRolloverSeamOut(
                trading_day=item.trading_day,
                previous_contract=item.previous_contract,
                next_contract=item.next_contract,
                previous_bar_end=item.previous_bar_end,
                next_bar_end=item.next_bar_end,
                previous_segment_id=item.previous_segment_id,
                next_segment_id=item.next_segment_id,
            )
            for item in result.rollover_seams
        ],
        legend={
            "BUILD": "trend build",
            "CLEAR": "trend clear",
            "D1": "escape D1",
            "D2": "escape D2",
            "D3": "escape D3",
        },
        formula_descriptions={
            "trend_band": result.instrument.formula_versions[0],
            "escape": result.instrument.formula_versions[1],
            "cup_handle": result.instrument.formula_versions[2],
        },
        warnings=list(result.warnings),
    )


def _marker(marker: NewowMainMarker) -> NewowMarkerOut:
    return NewowMarkerOut(
        marker_id=marker.marker_id,
        marker_type=marker.marker_type.value,
        bar_end=marker.bar_end,
        price=marker.price,
        label=marker.label,
        color_token=marker.color_token,
        priority=marker.priority,
        related_marker_ids=tuple(marker.related_marker_ids),
        trigger_facts=_safe_mapping(marker.trigger_facts),
        formula_version=marker.formula_version,
    )


def _pivot(pivot: CupPivot) -> NewowCupPivotOut:
    return NewowCupPivotOut(
        pivot_at=pivot.pivot_at,
        confirmed_at=pivot.confirmed_at,
        price=pivot.price,
    )


def _cup_handle(value: NewowCupHandleOverlay) -> NewowCupHandleOut:
    return NewowCupHandleOut(
        candidate_id=value.candidate_id,
        direction=value.direction.value,
        state=value.state.value,
        left_rim=_pivot(value.left_rim),
        bottom=_pivot(value.bottom),
        right_rim=_pivot(value.right_rim),
        handle_start_at=value.handle_start_at,
        handle_extreme=_pivot(value.handle_extreme) if value.handle_extreme else None,
        pivot_price=value.pivot_price,
        pivot_frozen_at=value.pivot_frozen_at,
        confirmed_at=value.confirmed_at,
        first_seen_at=value.first_seen_at,
        state_changed_at=value.state_changed_at,
        score=value.score,
        score_breakdown=_safe_float_mapping(value.score_breakdown),
        hard_failures=_safe_strings(value.hard_failures),
        diagnostics=_safe_strings(value.diagnostics),
        volume_facts=_safe_float_mapping(value.volume_facts),
        formula_version=value.formula_version,
    )


def _safe_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {key: _safe_value(value) for key, value in values.items() if _safe_key(key)}


def _safe_key(value: object) -> bool:
    if not isinstance(value, str):
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    return True


def _safe_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if isfinite(value):
            return value
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    if isinstance(value, Decimal):
        if value.is_finite():
            return format(value, "f")
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")


def _safe_float_mapping(values: Mapping[str, float]) -> dict[str, float]:
    mapped: dict[str, float] = {}
    for key, value in values.items():
        _safe_key(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        mapped[key] = float(value)
    return mapped


def _safe_strings(values: tuple[str, ...]) -> list[str]:
    if any(not isinstance(value, str) for value in values):
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    return list(values)
