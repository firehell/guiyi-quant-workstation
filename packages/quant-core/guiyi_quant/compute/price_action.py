"""Causal confirmation events. Chart adapters can render occurrence as retrospective."""

from collections import deque
from dataclasses import dataclass
from math import isfinite

from .contracts import FeatureMarker, FeaturePoint, Status
from .registry import FeatureRequest, IndicatorDefinition, Parameter, first_invalid, input_problem


_EXTREMES = ("high", "low")
_PRICES = ("high", "low", "close")
_PRIOR_BARS = 20
_RETEST_WINDOW = 10
_RESEARCH_USES = frozenset(("web", "research", "backtest"))


def _status_point(data, index, prefix, fields, *, warming=False, values=None):
    bar = data.bars[index]
    identity = (bar.bar_end, data.available_at[index])
    if index >= prefix:
        status, reason = input_problem(bar, fields) or (
            Status.UNKNOWN, "INPUT_PREFIX_INTERRUPTED",
        )
        return FeaturePoint(*identity, status, diagnostic=reason)
    if warming:
        return FeaturePoint(*identity, Status.WARMING, diagnostic="LOOKBACK_REQUIRED")
    return FeaturePoint(*identity, Status.READY, values or {})


def _marker(data, kind, occurrence, confirmation, price, classification=None):
    return FeatureMarker(
        kind=kind, occurred_at=data.bars[occurrence].bar_end,
        confirmed_at=data.bars[confirmation].confirmed_at, available_at=data.available_at[confirmation],
        price=float(price), classification=classification, confirmation_bar_end=data.bars[confirmation].bar_end,
    )


def _pivot(data, params):
    left, right = int(params["left"]), int(params["right"])
    prefix = first_invalid(data, _EXTREMES)
    highs, lows = (data.columns[name] for name in _EXTREMES)
    latest_high = latest_low = None
    markers, points = [], []
    for index in range(len(data.bars)):
        start, center = index - left - right, index - right
        point_markers = 0
        if start >= 0 and index < prefix:
            for kind, column, previous, compare, labels in (
                ("swing_high", highs, latest_high, max, ("HH", "LH")),
                ("swing_low", lows, latest_low, min, ("HL", "LL")),
            ):
                price = column[center]
                other = compare(compare(column[start:center]), compare(column[center + 1:index + 1]))
                if (kind == "swing_high" and price <= other) or (kind == "swing_low" and price >= other):
                    continue
                # An equal level has no directional classification.
                label = None
                if previous is not None and price != previous:
                    label = labels[0] if price > previous else labels[1]
                markers.append(_marker(data, kind, center, index, price, label))
                point_markers += 1
                if kind == "swing_high":
                    latest_high = price
                else:
                    latest_low = price
        points.append(_status_point(
            data, index, prefix, _EXTREMES, warming=start < 0, values={"event_count": point_markers},
        ))
    return tuple(points), tuple(markers)


def _events_on_points(result):
    # Group by confirming Bar, including when multiple Bars became available simultaneously.
    markers = iter(result.markers)
    marker = next(markers, None)
    for point in result.points:
        group = []
        while marker is not None and marker.available_at <= point.available_at:
            # confirmed_at is real confirmation and can be later than a Bar end.
            # Markers retain a separate effective Bar identity to prevent this grouping
            # from assigning a delayed event to an earlier point.
            if marker.confirmation_bar_end != point.bar_end:
                break
            group.append(marker)
            marker = next(markers, None)
        yield tuple(group)


def _support_resistance(data, params):
    pivot, atr = data.dependencies
    prefix = first_invalid(data, _EXTREMES)
    zones = {"support": deque(maxlen=8), "resistance": deque(maxlen=8)}
    points, markers = [], []
    for index, events in enumerate(_events_on_points(pivot)):
        atr_point = atr.points[index]
        values = {}
        warming = pivot.points[index].status is Status.WARMING or atr_point.status is Status.WARMING
        if index < prefix and atr_point.values is not None:
            tolerance = float(atr_point.values["value"]) * float(params["atr_width"])
            for event in events:
                kind = "resistance" if event.kind == "swing_high" else "support"
                candidates = zones[kind]
                nearest = min(candidates, default=None, key=lambda zone: abs(zone[0] - event.price))
                center, count = event.price, 1
                if nearest is not None and abs(nearest[0] - event.price) <= tolerance:
                    candidates.remove(nearest)
                    center = nearest[0] + (event.price - nearest[0]) / (nearest[1] + 1)
                    count += nearest[1]
                candidates.append((center, count))
                markers.append(FeatureMarker(
                    kind, event.occurred_at, event.confirmed_at, event.available_at, center,
                    confirmation_bar_end=event.confirmation_bar_end,
                ))
            close = data.bars[index].close
            if close is not None and isfinite(close):
                for kind, (lower, upper) in {
                    "support": ("support_lower", "support_upper"),
                    "resistance": ("resistance_lower", "resistance_upper"),
                }.items():
                    candidates = [
                        price for price, _ in zones[kind]
                        if (price <= close if kind == "support" else price >= close)
                    ]
                    if candidates:
                        center = min(candidates, key=lambda price: abs(price - close))
                        values[lower], values[upper] = center - tolerance, center + tolerance
        if index < prefix and atr_point.status in (Status.UNKNOWN, Status.INVALID):
            points.append(atr_point)
        else:
            points.append(_status_point(data, index, prefix, _EXTREMES, warming=warming, values=values))
    return tuple(points), tuple(markers)


def _breakout(data, params):
    hhv, llv, atr, *optional_volume = data.dependencies
    prefix = first_invalid(data, _PRICES)
    points, markers = [], []
    for index in range(len(data.bars)):
        values = {}
        prior = () if index == 0 else tuple(series.points[index - 1] for series in (hhv, llv, atr))
        warming = not prior or any(point.status is Status.WARMING for point in prior)
        if index < prefix and prior and all(point.values is not None for point in prior):
            upper, lower, volatility = (float(point.values["value"]) for point in prior)
            buffer = volatility * float(params["atr_buffer"])
            upper += buffer
            lower -= buffer
            close = data.columns["close"][index]
            previous = data.columns["close"][index - 1]
            kind = "breakout" if previous <= upper < close else (
                "breakdown" if previous >= lower > close else None
            )
            if optional_volume:
                volume = optional_volume[0].points[index]
                if volume.values is None:
                    points.append(volume)
                    continue
                if float(volume.values["value"]) < float(params["min_volume_ratio"]):
                    kind = None
            values = {"upper": upper, "lower": lower}
            if kind:
                marks_at = upper if kind == "breakout" else lower
                markers.append(_marker(data, kind, index, index, marks_at))
        elif index < prefix and prior and not warming:
            invalid = next(point for point in prior if point.values is None)
            bar = data.bars[index]
            points.append(FeaturePoint(
                bar.bar_end, data.available_at[index], invalid.status, diagnostic=invalid.diagnostic,
            ))
            continue
        points.append(_status_point(data, index, prefix, _PRICES, warming=warming, values=values))
    return tuple(points), tuple(markers)


@dataclass(frozen=True, slots=True)
class RetestState:
    event: FeatureMarker
    deadline: int
    tolerance: float


def _retest(data, params):
    breakout, atr = data.dependencies
    prefix = first_invalid(data, _PRICES)
    points, markers = [], []
    state = None
    for index, events in enumerate(_events_on_points(breakout)):
        status = breakout.points[index]
        if index >= prefix or status.status is not Status.READY:
            points.append(status)
            state = None
            continue
        values = {}
        if state is not None:
            level = state.event.price
            up = state.event.kind == "breakout"
            high, low, close = (data.columns[name][index] for name in _PRICES)
            failed = close < level - state.tolerance if up else close > level + state.tolerance
            touched = low <= level + state.tolerance if up else high >= level - state.tolerance
            recovered = close >= level if up else close <= level
            kind = None
            if failed or index > state.deadline:
                kind = "retest_invalidated"
            elif touched and recovered:
                kind = "retest_confirmed"
            if kind:
                markers.append(_marker(data, kind, index, index, level, state.event.kind))
                state = None
            elif touched:
                values["state"] = "TESTING"
        if events:
            event = events[-1]
            volatility = atr.points[index].values
            if volatility is not None:
                tolerance = max(0, float(volatility["value"])) * float(params["atr_width"])
                state = RetestState(event, index + _RETEST_WINDOW, tolerance)
        if state is not None:
            values.setdefault("state", "WAITING")
            values["level"] = state.event.price
        points.append(_status_point(data, index, prefix, _PRICES, values=values))
    return tuple(points), tuple(markers)


_PIVOT = IndicatorDefinition(
    "swing_pivot", "pattern", "guiyi_swing_pivot_v1", "guiyi_price_action_v1",
    _EXTREMES, {"left": Parameter(2, 1, 50), "right": Parameter(2, 1, 50)},
    ("event_count",), _pivot, lambda params: int(params["left"]) + int(params["right"]),
    allowed_uses=_RESEARCH_USES, output_schema_version="aligned_pattern_v1",
)
PRICE_ACTION_DEFINITIONS = (
    _PIVOT,
    IndicatorDefinition(
        "support_resistance", "pattern", "guiyi_pivot_support_resistance_v1", "guiyi_price_action_v1",
        _EXTREMES, {"atr_width": Parameter(0.5, 0, 10, integral=False)},
        ("support_lower", "support_upper", "resistance_lower", "resistance_upper"),
        _support_resistance, lambda _: 14,
        dependencies=(FeatureRequest("swing_pivot"), FeatureRequest("atr")),
        allowed_uses=_RESEARCH_USES, output_schema_version="aligned_pattern_v1",
    ),
    IndicatorDefinition(
        "breakout", "pattern", "guiyi_prior_range_breakout_v1", "guiyi_price_action_v1",
        _PRICES, {
            "atr_buffer": Parameter(0.25, 0, 10, integral=False),
            "min_volume_ratio": Parameter(0, 0, 100, integral=False),
        },
        ("upper", "lower"), _breakout, lambda _: _PRIOR_BARS,
        dependencies=(FeatureRequest("hhv", {"period": _PRIOR_BARS}),
                      FeatureRequest("llv", {"period": _PRIOR_BARS}), FeatureRequest("atr")),
        optional_dependencies=(("min_volume_ratio", FeatureRequest("volume_ratio")),),
        allowed_uses=_RESEARCH_USES, output_schema_version="aligned_pattern_v1",
    ),
    IndicatorDefinition(
        "retest", "pattern", "guiyi_breakout_retest_v1", "guiyi_price_action_v1",
        _PRICES, {"atr_width": Parameter(0.5, 0, 10, integral=False)},
        ("state", "level"), _retest, lambda _: _PRIOR_BARS,
        dependencies=(FeatureRequest("breakout"), FeatureRequest("atr")),
        allowed_uses=_RESEARCH_USES, output_schema_version="aligned_pattern_v1",
    ),
)
