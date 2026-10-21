"""Decimal, completed-bar features isolated by the complete physical owner."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext
from types import MappingProxyType
from typing import Mapping, Sequence

from .contracts import Bar, Feature

Owner = tuple[str, str, str]
_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                           capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])


@dataclass(frozen=True, slots=True)
class PreparedFeatures:
    _groups: Mapping[tuple[str, Owner], tuple[Feature, ...]]
    _streams: Mapping[tuple[str, str], tuple[Feature, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        streams = defaultdict(list)
        for (frequency, owner), features in self._groups.items():
            streams[(frequency, owner[0])].extend(features)
        object.__setattr__(self, '_streams', MappingProxyType({
            key: tuple(sorted(rows, key=lambda f: (f.bar.bar_end, f.bar.owner)))
            for key, rows in streams.items()}))

    def series(self, frequency: str, physical_contract: str) -> tuple[Feature, ...]:
        """Return all owner-isolated features in deterministic event order."""
        return self._streams.get((frequency, physical_contract), ())

    def at(self, frequency: str, physical_contract: str, at: datetime, *,
           strict: bool = True, owner: Owner | None = None) -> Feature | None:
        """Select an already completed and confirmed snapshot, never infer its owner."""
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("FUTURES_FEATURE_TIME_INVALID")
        if owner is not None:
            if owner[0] != physical_contract:
                return None
            features = self._groups.get((frequency, owner), ())
            search = bisect_left if strict else bisect_right
            index = search(features, at, key=lambda f: f.bar.confirmed_at) - 1
            return features[index] if index >= 0 else None
        candidates = []
        for (freq, group_owner), features in self._groups.items():
            if freq != frequency or group_owner[0] != physical_contract:
                continue
            if owner is not None and group_owner != owner:
                continue
            search = bisect_left if strict else bisect_right
            index = search(features, at, key=lambda f: f.bar.confirmed_at) - 1
            if index >= 0:
                candidates.append(features[index])
        if len(candidates) > 1:
            raise ValueError("FUTURES_OWNER_AMBIGUOUS")
        return candidates[0] if candidates else None


def _features(bars: Sequence[Bar]) -> tuple[Feature, ...]:
    typical: list[Decimal] = []
    trs: list[Decimal] = []
    slows: list[Decimal | None] = []
    ma45s: list[Decimal | None] = []
    result = []
    for i, bar in enumerate(bars):
        typical.append((bar.high + bar.low + bar.close) / 3)
        previous = bars[i - 1].close if i else None
        if previous is not None:
            trs.append(max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous)))
        fast = sum(typical[-7:]) / 7 if i >= 6 else None
        slow = sum(typical[-10:]) / 10 if i >= 9 else None
        ma35 = sum(typical[-35:]) / 35 if i >= 34 else None
        ma45 = sum(typical[-45:]) / 45 if i >= 44 else None
        atr = sum(trs[-20:]) / 20 if len(trs) >= 20 else None
        slow_prev3 = slows[i - 3] if i >= 3 else None
        ma45_prev3 = ma45s[i - 3] if i >= 3 else None
        regime = None
        if atr is not None and atr > 0 and fast is not None and slow is not None and slow_prev3 is not None:
            regime = 0
            threshold = atr / 10
            if bar.close > slow and fast - slow >= threshold and slow - slow_prev3 >= threshold:
                regime = 1
            elif bar.close < slow and slow - fast >= threshold and slow_prev3 - slow >= threshold:
                regime = -1
        result.append(Feature(
            bar=bar, fast=fast, slow=slow, slow_prev3=slow_prev3, atr=atr,
            upper=max(b.high for b in bars[i - 10:i]) if i >= 10 else None,
            lower=min(b.low for b in bars[i - 10:i]) if i >= 10 else None,
            high3=max(b.high for b in bars[i - 3:i]) if i >= 3 else None,
            low3=min(b.low for b in bars[i - 3:i]) if i >= 3 else None,
            high11=max(b.high for b in bars[i - 11:i]) if i >= 11 else None,
            low11=min(b.low for b in bars[i - 11:i]) if i >= 11 else None,
            ma35=ma35, ma45=ma45, ma45_prev3=ma45_prev3, regime=regime,
            previous_close=previous, previous_slow=slows[-1] if slows else None))
        slows.append(slow)
        ma45s.append(ma45)
    return tuple(result)


def _prepare_features(bars_by_frequency: Mapping[str, Sequence[Bar]]) -> PreparedFeatures:
    """Prepare causal prefixes without combining owners, segments, or frequencies."""
    groups: dict[tuple[str, Owner], list[Bar]] = defaultdict(list)
    for frequency, bars in bars_by_frequency.items():
        for bar in bars:
            if bar.frequency != frequency:
                raise ValueError("FUTURES_FEATURE_FREQUENCY_MISMATCH")
            groups[(frequency, bar.owner)].append(bar)
    prepared = {}
    for key, bars in groups.items():
        bars.sort(key=lambda b: b.bar_end)
        for i, bar in enumerate(bars):
            if i and bar.bar_end == bars[i - 1].bar_end:
                raise ValueError("FUTURES_FEATURE_DUPLICATE_BAR")
            if i and (bar.product != bars[i - 1].product or bar.confirmed_at < bars[i - 1].confirmed_at):
                raise ValueError("FUTURES_FEATURE_PREFIX_INVALID")
        prepared[key] = _features(bars)
    return PreparedFeatures(MappingProxyType(prepared))


def prepare_features(bars_by_frequency: Mapping[str, Sequence[Bar]]) -> PreparedFeatures:
    """Prepare immutable features under the frozen decimal context, leaving callers untouched."""
    with localcontext(_DECIMAL_CONTEXT):
        return _prepare_features(bars_by_frequency)
