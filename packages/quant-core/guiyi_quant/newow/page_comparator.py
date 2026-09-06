"""Evidence-gated page window comparison isolated from strategy trade facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from math import isfinite

from .oscillation_channel import CHANNEL_FORMULA_VERSION, OSCILLATION_FORMULA_VERSION
from .product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
)
from .product_identity import utc_timestamp


PAGE_COMPARATOR_FORMULA_VERSION = "newow_hhv_llv_window_optimizer_page_v1"
FUTURES_SEGMENT_ADAPTER_VERSION = "guiyi_newow_page_comparator_segment_adapter_v1"
CANDIDATE_WINDOWS = (10, 20, 24, 30, 52)
BUILDER_SHA256 = "a4491db837d710d3eda3b3d7b82ceae93b08d4b6418ae814c9649e0ef2ef23e0"
ORACLE_SHA256 = "ec353dd6608da2ed99d6a2cc582d4fc629aa5704c88e558d87aed7b23772b3bb"
INPUT_SHA256 = "15473f0ebe577081eabdd24b663ce13374f8caf1a53997321f38b6af17424bb4"
PAGE_SOURCE_SHA256 = "cd962170085dc2145fbaebf28a47ce6764b9f519e6032b54a896e37f0c9d0cf9"
_EXPECTED_FORMULAS = frozenset((OSCILLATION_FORMULA_VERSION, CHANNEL_FORMULA_VERSION))
_RESEARCH = EvidenceStatus.RESEARCH_EVIDENCE_ONLY


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_TEXT")


def _day(value: object) -> None:
    if type(value) is not date:
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_OWNER")


def _finite_number(value: Decimal) -> float:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_PRICE")
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_PRICE")
    return number


def _to_fixed(number: float, digits: int) -> str:
    quantum = Decimal(1).scaleb(-digits)
    with localcontext() as context:
        context.prec = 64
        context.rounding = ROUND_HALF_UP
        rounded = Decimal.from_float(number).quantize(quantum)
    return f"{rounded:.{digits}f}"


@dataclass(frozen=True, slots=True)
class VerifiedPageComparatorEvidence:
    """Exact offline-source evidence; it does not certify browser rendering."""

    builder_sha256: str = BUILDER_SHA256
    oracle_sha256: str = ORACLE_SHA256
    input_sha256: str = INPUT_SHA256
    page_source_sha256: str = PAGE_SOURCE_SHA256
    evidence_kind: str = "offline_page_source_oracle"
    browser_render_status: str = "UNAVAILABLE_CONTROL_TIMEOUT"
    input_mode: str = "frozen_raw_source_response"

    def __post_init__(self) -> None:
        if (
            self.builder_sha256 != BUILDER_SHA256
            or self.oracle_sha256 != ORACLE_SHA256
            or self.input_sha256 != INPUT_SHA256
            or self.page_source_sha256 != PAGE_SOURCE_SHA256
            or self.evidence_kind != "offline_page_source_oracle"
            or self.browser_render_status != "UNAVAILABLE_CONTROL_TIMEOUT"
            or self.input_mode != "frozen_raw_source_response"
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_EVIDENCE_IDENTITY")


@dataclass(frozen=True, slots=True)
class ComparatorOwnerSegment:
    """Guiyi-owned authoritative owner interval, including legal empty segments."""

    product: str
    physical_contract: str
    segment_id: str
    start_trading_day: date
    end_trading_day: date

    def __post_init__(self) -> None:
        for value in (self.product, self.physical_contract, self.segment_id):
            _text(value)
        _day(self.start_trading_day)
        _day(self.end_trading_day)
        if (
            self.product != self.product.lower()
            or self.physical_contract != self.physical_contract.upper()
            or self.start_trading_day > self.end_trading_day
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_OWNER")


@dataclass(frozen=True, slots=True)
class PageComparatorTrade:
    """One comparator-only close-to-close outcome, never a StrategyAction."""

    entry_bar_end: datetime
    entry_price: float
    exit_bar_end: datetime
    exit_price: float
    return_pct: float
    won: bool
    synthetic_terminal: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_bar_end", utc_timestamp(self.entry_bar_end))
        object.__setattr__(self, "exit_bar_end", utc_timestamp(self.exit_bar_end))
        if (
            not all(
                isfinite(value)
                for value in (self.entry_price, self.exit_price, self.return_pct)
            )
            or self.entry_price <= 0
            or self.exit_price <= 0
            or type(self.won) is not bool
            or type(self.synthetic_terminal) is not bool
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_TRADE")


@dataclass(frozen=True, slots=True)
class PageComparatorDisplay:
    cumulative_return_pct: str
    max_drawdown_pct: str
    win_rate_pct: str


@dataclass(frozen=True, slots=True)
class PageWindowComparison:
    window: int
    cumulative_return_pct: float
    max_drawdown_pct: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate_pct: float
    force_closed_at_end: bool
    score: float
    page_display: PageComparatorDisplay
    trades: tuple[PageComparatorTrade, ...]

    def __post_init__(self) -> None:
        if (
            self.window not in CANDIDATE_WINDOWS
            or self.trade_count != self.win_count + self.loss_count
            or self.trade_count != len(self.trades)
            or self.win_count < 0
            or self.loss_count < 0
            or not all(
                isfinite(value)
                for value in (
                    self.cumulative_return_pct,
                    self.max_drawdown_pct,
                    self.win_rate_pct,
                    self.score,
                )
            )
            or self.max_drawdown_pct < 0
            or type(self.force_closed_at_end) is not bool
            or not isinstance(self.page_display, PageComparatorDisplay)
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_RESULT")
        object.__setattr__(self, "trades", tuple(self.trades))


@dataclass(frozen=True, slots=True)
class PageComparatorSegmentResult:
    physical_contract: str
    segment_id: str
    frequency: ProductFrequency
    start_trading_day: date
    end_trading_day: date
    bar_count: int
    status: FeatureStatus
    results: tuple[PageWindowComparison, ...]
    ranked_windows: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, FeatureStatus) or self.bar_count < 0:
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SEGMENT_RESULT")
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "ranked_windows", tuple(self.ranked_windows))


@dataclass(frozen=True, slots=True)
class ComparatorSubfeature:
    name: str
    status: FeatureStatus
    value: object | None

    def __post_init__(self) -> None:
        _text(self.name)
        if not isinstance(self.status, FeatureStatus):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SUBFEATURE")


@dataclass(frozen=True, slots=True)
class PageComparatorValue:
    segments: tuple[PageComparatorSegmentResult, ...]
    default_segment_id: str | None
    candidate_windows: tuple[int, ...]
    page_formula_version: str
    futures_adapter_version: str
    page_source_kernel_page_parity: bool
    futures_adapter_page_parity: bool
    in_sample: bool
    executable: bool
    input_mode: str
    subfeatures: tuple[ComparatorSubfeature, ...]
    cross_segment_ranking: None = None
    account_aggregation: None = None

    def __post_init__(self) -> None:
        segments = tuple(self.segments)
        features = tuple(self.subfeatures)
        if (
            self.candidate_windows != CANDIDATE_WINDOWS
            or self.page_formula_version != PAGE_COMPARATOR_FORMULA_VERSION
            or self.futures_adapter_version != FUTURES_SEGMENT_ADAPTER_VERSION
            or self.page_source_kernel_page_parity is not True
            or self.futures_adapter_page_parity is not False
            or self.in_sample is not True
            or self.executable is not False
            or self.input_mode != "guiyi_completed_owner_segment"
            or len({feature.name for feature in features}) != len(features)
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_VALUE")
        if self.default_segment_id is not None:
            _text(self.default_segment_id)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "subfeatures", features)


@dataclass(frozen=True, slots=True)
class PageComparatorResult:
    identity: ProductIdentity
    status: FeatureRuntimeStatus
    evidence_status: EvidenceStatus
    reason_code: str | None
    as_of: datetime
    formula_versions: tuple[str, ...] = ()
    value: PageComparatorValue | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProductIdentity):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_IDENTITY")
        object.__setattr__(self, "status", FeatureRuntimeStatus(self.status))
        object.__setattr__(
            self, "evidence_status", EvidenceStatus(self.evidence_status)
        )
        object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
        object.__setattr__(self, "formula_versions", tuple(self.formula_versions))
        if self.status is not FeatureRuntimeStatus.READY:
            _text(self.reason_code)


@dataclass(frozen=True, slots=True)
class _CalculatedWindow:
    window: int
    cumulative: float
    max_drawdown: float
    wins: int
    losses: int
    forced: bool
    trades: tuple[PageComparatorTrade, ...]


def _calculate_window(bars: tuple[ProductBar, ...], window: int) -> _CalculatedWindow:
    raw = tuple(item.bar for item in bars)
    highs = tuple(_finite_number(item.high) for item in raw)
    lows = tuple(_finite_number(item.low) for item in raw)
    closes = tuple(_finite_number(item.close) for item in raw)
    holding = False
    entry_price = 0.0
    entry_bar_end: datetime | None = None
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    wins = 0
    losses = 0
    trades: list[PageComparatorTrade] = []

    for index in range(window - 1, len(raw)):
        upper = max(highs[index + 1 - window : index + 1])
        lower = min(lows[index + 1 - window : index + 1])
        if holding and highs[index] >= upper:
            if entry_bar_end is None:
                raise RuntimeError("NEWOW_PAGE_COMPARATOR_INTERNAL_STATE")
            value = (closes[index] - entry_price) / entry_price * 100
            won = value > 0
            wins += int(won)
            losses += int(not won)
            cumulative += value
            trades.append(
                PageComparatorTrade(
                    entry_bar_end=entry_bar_end,
                    entry_price=entry_price,
                    exit_bar_end=raw[index].bar_end,
                    exit_price=closes[index],
                    return_pct=value,
                    won=won,
                    synthetic_terminal=False,
                )
            )
            holding = False
            entry_bar_end = None
        if not holding and lows[index] <= lower:
            holding = True
            entry_price = closes[index]
            entry_bar_end = raw[index].bar_end
        current_equity = cumulative
        if holding:
            current_equity += (closes[index] - entry_price) / entry_price * 100
        if current_equity > peak:
            peak = current_equity
        drawdown = peak - current_equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    forced = holding
    if forced:
        if entry_bar_end is None:
            raise RuntimeError("NEWOW_PAGE_COMPARATOR_INTERNAL_STATE")
        value = (closes[-1] - entry_price) / entry_price * 100
        won = value > 0
        wins += int(won)
        losses += int(not won)
        cumulative += value
        trades.append(
            PageComparatorTrade(
                entry_bar_end=entry_bar_end,
                entry_price=entry_price,
                exit_bar_end=raw[-1].bar_end,
                exit_price=closes[-1],
                return_pct=value,
                won=won,
                synthetic_terminal=True,
            )
        )
    return _CalculatedWindow(
        window,
        cumulative,
        max_drawdown,
        wins,
        losses,
        forced,
        tuple(trades),
    )


def _score_windows(
    calculated: tuple[_CalculatedWindow, ...],
) -> tuple[tuple[PageWindowComparison, ...], tuple[int, ...]]:
    max_return = max(item.cumulative for item in calculated)
    min_return = min(item.cumulative for item in calculated)
    min_drawdown = min(item.max_drawdown for item in calculated)
    results = []
    for item in calculated:
        trade_count = item.wins + item.losses
        win_rate = item.wins / trade_count * 100 if trade_count else 0.0
        score = (item.cumulative - min(0, max_return)) / max(
            1, max_return - min_return + 1
        ) + min_drawdown / max(1, item.max_drawdown or 1)
        results.append(
            PageWindowComparison(
                window=item.window,
                cumulative_return_pct=item.cumulative,
                max_drawdown_pct=item.max_drawdown,
                trade_count=trade_count,
                win_count=item.wins,
                loss_count=item.losses,
                win_rate_pct=win_rate,
                force_closed_at_end=item.forced,
                score=score,
                page_display=PageComparatorDisplay(
                    cumulative_return_pct=_to_fixed(item.cumulative, 2),
                    max_drawdown_pct=_to_fixed(item.max_drawdown, 2),
                    win_rate_pct=_to_fixed(win_rate, 1) if trade_count else "0",
                ),
                trades=item.trades,
            )
        )
    by_index = {window: index for index, window in enumerate(CANDIDATE_WINDOWS)}
    ranked = tuple(
        item.window
        for item in sorted(
            results,
            key=lambda item: (-item.score, by_index[item.window]),
        )
    )
    return tuple(results), ranked


def _infer_owners(bars: tuple[ProductBar, ...]) -> tuple[ComparatorOwnerSegment, ...]:
    grouped: list[list[ProductBar]] = []
    current: tuple[str, str] | None = None
    seen: set[tuple[str, str]] = set()
    for item in bars:
        if not isinstance(item, ProductBar):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INPUT_IDENTITY_INVALID")
        owner = (item.bar.physical_contract, item.bar.segment_id)
        if owner != current:
            if owner in seen:
                raise ValueError("NEWOW_PAGE_COMPARATOR_INPUT_ORDER")
            seen.add(owner)
            grouped.append([])
            current = owner
        grouped[-1].append(item)
    return tuple(
        ComparatorOwnerSegment(
            product=items[0].bar.product,
            physical_contract=items[0].bar.physical_contract,
            segment_id=items[0].bar.segment_id,
            start_trading_day=items[0].bar.trading_day,
            end_trading_day=items[-1].bar.trading_day,
        )
        for items in grouped
    )


def _validate_owners(
    identity: ProductIdentity,
    owners: tuple[ComparatorOwnerSegment, ...],
) -> None:
    previous: ComparatorOwnerSegment | None = None
    keys: set[tuple[str, str]] = set()
    for owner in owners:
        if (
            not isinstance(owner, ComparatorOwnerSegment)
            or owner.product != identity.product
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_OWNER")
        key = (owner.physical_contract, owner.segment_id)
        if key in keys or (
            previous is not None and owner.start_trading_day <= previous.end_trading_day
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_OWNER_ORDER")
        keys.add(key)
        previous = owner


def _group_bars(
    identity: ProductIdentity,
    bars: tuple[ProductBar, ...],
    owners: tuple[ComparatorOwnerSegment, ...],
    as_of: datetime,
) -> tuple[tuple[ProductBar, ...], ...]:
    owner_indexes = {
        (owner.physical_contract, owner.segment_id): index
        for index, owner in enumerate(owners)
    }
    grouped: list[list[ProductBar]] = [[] for _ in owners]
    prior_owner_index = -1
    previous_by_owner: dict[int, ProductBar] = {}
    sources: set[str] = set()
    for item in bars:
        if (
            not isinstance(item, ProductBar)
            or item.bar.product != identity.product
            or item.frequency != identity.frequency
            or item.series_kind != identity.series_kind
            or item.bar.observation_eligible is not True
            or item.bar.completed is not True
            or item.bar.bar_end > as_of
            or item.bar.source_identity in sources
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INPUT_IDENTITY_INVALID")
        key = (item.bar.physical_contract, item.bar.segment_id)
        owner_index = owner_indexes.get(key)
        if owner_index is None or owner_index < prior_owner_index:
            raise ValueError("NEWOW_PAGE_COMPARATOR_INPUT_ORDER")
        owner = owners[owner_index]
        if not owner.start_trading_day <= item.bar.trading_day <= owner.end_trading_day:
            raise ValueError("NEWOW_PAGE_COMPARATOR_OWNER_MISMATCH")
        previous = previous_by_owner.get(owner_index)
        if previous is not None and (
            item.bar.bar_end <= previous.bar.bar_end
            or (
                identity.frequency is not ProductFrequency.HOURLY
                and item.bar.trading_day <= previous.bar.trading_day
            )
            or (
                identity.frequency is ProductFrequency.HOURLY
                and item.bar.trading_day < previous.bar.trading_day
            )
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INPUT_ORDER")
        for value in (
            item.bar.open,
            item.bar.high,
            item.bar.low,
            item.bar.close,
        ):
            _finite_number(value)
        if type(item.bar.volume) is not int or item.bar.volume < 0:
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_VOLUME")
        sources.add(item.bar.source_identity)
        grouped[owner_index].append(item)
        previous_by_owner[owner_index] = item
        prior_owner_index = owner_index
    return tuple(tuple(items) for items in grouped)


def _subfeatures() -> tuple[ComparatorSubfeature, ...]:
    ready_research = FeatureStatus(FeatureRuntimeStatus.READY, _RESEARCH)
    ready_adapter = FeatureStatus(
        FeatureRuntimeStatus.READY, EvidenceStatus.ACTIVE_CODE_VERIFIED
    )
    gaps = (
        (
            "browser_final_kline",
            "NEWOW_PAGE_COMPARATOR_BROWSER_INPUT_EVIDENCE_REQUIRED",
        ),
        ("browser_dom_rendering", "NEWOW_PAGE_COMPARATOR_DOM_EVIDENCE_REQUIRED"),
        ("browser_tie_golden", "NEWOW_PAGE_COMPARATOR_TIE_EVIDENCE_REQUIRED"),
        (
            "original_page_futures_owner_behavior",
            "NEWOW_PAGE_COMPARATOR_PAGE_FUTURES_EVIDENCE_REQUIRED",
        ),
    )
    return (
        ComparatorSubfeature(
            "offline_page_source_kernel",
            ready_research,
            PAGE_COMPARATOR_FORMULA_VERSION,
        ),
        ComparatorSubfeature(
            "guiyi_owner_segment_adapter",
            ready_adapter,
            FUTURES_SEGMENT_ADAPTER_VERSION,
        ),
        *(
            ComparatorSubfeature(
                name,
                FeatureStatus(
                    FeatureRuntimeStatus.EVIDENCE_REQUIRED,
                    EvidenceStatus.EVIDENCE_REQUIRED,
                    reason,
                ),
                None,
            )
            for name, reason in gaps
        ),
    )


def compare_page_windows(
    identity: ProductIdentity,
    bars: tuple[ProductBar, ...],
    evidence: object | None,
    *,
    authoritative_segments: tuple[ComparatorOwnerSegment, ...] | None = None,
    as_of: datetime | None = None,
) -> PageComparatorResult:
    """Compare fixed windows per owner segment without producing trade authority."""

    if not isinstance(identity, ProductIdentity) or (
        identity.strategy is not ProductStrategy.OSCILLATION
        or frozenset(identity.formula_versions) != _EXPECTED_FORMULAS
    ):
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_IDENTITY")
    try:
        inputs = tuple(bars)
    except TypeError as error:
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_INPUT") from error
    cutoff = (
        utc_timestamp(as_of)
        if as_of is not None
        else max(
            (item.bar.bar_end for item in inputs if isinstance(item, ProductBar)),
            default=datetime.min.replace(tzinfo=UTC),
        )
    )
    if evidence is None:
        return PageComparatorResult(
            identity=identity,
            status=FeatureRuntimeStatus.EVIDENCE_REQUIRED,
            evidence_status=EvidenceStatus.EVIDENCE_REQUIRED,
            reason_code="NEWOW_PAGE_COMPARATOR_EVIDENCE_REQUIRED",
            as_of=cutoff,
        )
    if not isinstance(evidence, VerifiedPageComparatorEvidence):
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_EVIDENCE")

    if authoritative_segments is None:
        owners = _infer_owners(inputs)
    else:
        try:
            owners = tuple(authoritative_segments)
        except TypeError as error:
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_OWNER") from error
    _validate_owners(identity, owners)
    grouped = _group_bars(identity, inputs, owners, cutoff)

    segment_results = []
    for owner, owner_bars in zip(owners, grouped, strict=True):
        if len(owner_bars) < 20:
            segment_results.append(
                PageComparatorSegmentResult(
                    owner.physical_contract,
                    owner.segment_id,
                    identity.frequency,
                    owner.start_trading_day,
                    owner.end_trading_day,
                    len(owner_bars),
                    FeatureStatus(
                        FeatureRuntimeStatus.UNAVAILABLE,
                        _RESEARCH,
                        "NEWOW_PAGE_COMPARATOR_INSUFFICIENT_BARS",
                    ),
                    (),
                    (),
                )
            )
            continue
        results, ranked = _score_windows(
            tuple(_calculate_window(owner_bars, window) for window in CANDIDATE_WINDOWS)
        )
        segment_results.append(
            PageComparatorSegmentResult(
                owner.physical_contract,
                owner.segment_id,
                identity.frequency,
                owner.start_trading_day,
                owner.end_trading_day,
                len(owner_bars),
                FeatureStatus(FeatureRuntimeStatus.READY, _RESEARCH),
                results,
                ranked,
            )
        )

    segments = tuple(segment_results)
    default_segment_id = owners[-1].segment_id if owners else None
    value = PageComparatorValue(
        segments=segments,
        default_segment_id=default_segment_id,
        candidate_windows=CANDIDATE_WINDOWS,
        page_formula_version=PAGE_COMPARATOR_FORMULA_VERSION,
        futures_adapter_version=FUTURES_SEGMENT_ADAPTER_VERSION,
        page_source_kernel_page_parity=True,
        futures_adapter_page_parity=False,
        in_sample=True,
        executable=False,
        input_mode="guiyi_completed_owner_segment",
        subfeatures=_subfeatures(),
    )
    if not owners:
        status = FeatureRuntimeStatus.UNAVAILABLE
        reason = "NEWOW_PAGE_COMPARATOR_NO_OWNER_SEGMENTS"
    elif not grouped[-1]:
        status = FeatureRuntimeStatus.UNAVAILABLE
        reason = "NEWOW_PAGE_COMPARATOR_LATEST_SEGMENT_EMPTY"
    elif segments[-1].status.status is not FeatureRuntimeStatus.READY:
        status = FeatureRuntimeStatus.UNAVAILABLE
        reason = "NEWOW_PAGE_COMPARATOR_INSUFFICIENT_BARS"
    else:
        status = FeatureRuntimeStatus.READY
        reason = None
    return PageComparatorResult(
        identity=identity,
        status=status,
        evidence_status=_RESEARCH,
        reason_code=reason,
        as_of=cutoff,
        formula_versions=(
            PAGE_COMPARATOR_FORMULA_VERSION,
            FUTURES_SEGMENT_ADAPTER_VERSION,
        ),
        value=value,
    )
