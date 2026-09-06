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


def _public_decimal(number: float) -> Decimal:
    if not isfinite(number):
        raise ValueError("NEWOW_PAGE_COMPARATOR_PAGE_NUMBER_OUT_OF_RANGE")
    return Decimal(str(number))


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
    entry_price: Decimal
    exit_bar_end: datetime
    exit_price: Decimal
    return_pct: Decimal
    won: bool
    synthetic_terminal: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_bar_end", utc_timestamp(self.entry_bar_end))
        object.__setattr__(self, "exit_bar_end", utc_timestamp(self.exit_bar_end))
        if (
            not all(
                isinstance(value, Decimal) and value.is_finite()
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
    cumulative_return_pct: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    win_count: int
    loss_count: int
    win_rate_pct: Decimal
    force_closed_at_end: bool
    score: Decimal
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
                isinstance(value, Decimal) and value.is_finite()
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
class PageComparatorSourceBars:
    """Actual owner-local source range, separate from owner authority."""

    count: int
    first_trading_day: date | None
    last_trading_day: date | None
    first_bar_end: datetime | None
    last_bar_end: datetime | None
    source_identities: tuple[str, ...]
    snapshot_kind: str = "guiyi_completed_owner_segment"
    fact_identity_fields: tuple[str, ...] = (
        "product",
        "physical_contract",
        "segment_id",
        "frequency",
        "bar_end",
    )

    def __post_init__(self) -> None:
        sources = tuple(self.source_identities)
        fields = tuple(self.fact_identity_fields)
        if (
            type(self.count) is not int
            or self.count < 0
            or len(set(sources)) != len(sources)
            or self.snapshot_kind != "guiyi_completed_owner_segment"
            or fields
            != (
                "product",
                "physical_contract",
                "segment_id",
                "frequency",
                "bar_end",
            )
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SOURCE_BARS")
        for source in sources:
            _text(source)
        bounds = (
            self.first_trading_day,
            self.last_trading_day,
            self.first_bar_end,
            self.last_bar_end,
        )
        if self.count == 0:
            if any(value is not None for value in bounds) or sources:
                raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SOURCE_BARS")
        else:
            if (
                self.first_trading_day is None
                or self.last_trading_day is None
                or self.first_bar_end is None
                or self.last_bar_end is None
                or not sources
            ):
                raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SOURCE_BARS")
            _day(self.first_trading_day)
            _day(self.last_trading_day)
            first_end = utc_timestamp(self.first_bar_end)
            last_end = utc_timestamp(self.last_bar_end)
            if self.first_trading_day > self.last_trading_day or first_end > last_end:
                raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SOURCE_BARS")
            object.__setattr__(self, "first_bar_end", first_end)
            object.__setattr__(self, "last_bar_end", last_end)
        object.__setattr__(self, "source_identities", sources)
        object.__setattr__(self, "fact_identity_fields", fields)


@dataclass(frozen=True, slots=True)
class PageComparatorSegmentResult:
    physical_contract: str
    segment_id: str
    frequency: ProductFrequency
    authoritative_start_trading_day: date
    authoritative_end_trading_day: date
    source_bars: PageComparatorSourceBars
    as_of: datetime
    in_sample: bool
    repainting: bool
    repaint_status: FeatureStatus
    input_snapshot_status: FeatureStatus
    status: FeatureStatus
    results: tuple[PageWindowComparison, ...]
    ranked_windows: tuple[int, ...]

    def __post_init__(self) -> None:
        for value in (self.physical_contract, self.segment_id):
            _text(value)
        _day(self.authoritative_start_trading_day)
        _day(self.authoritative_end_trading_day)
        cutoff = utc_timestamp(self.as_of)
        source = self.source_bars
        if not isinstance(source, PageComparatorSourceBars):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SEGMENT_RESULT")
        source_outside_authority = source.count > 0 and (
            source.first_trading_day is None
            or source.last_trading_day is None
            or source.last_bar_end is None
            or source.first_trading_day < self.authoritative_start_trading_day
            or source.last_trading_day > self.authoritative_end_trading_day
            or source.last_bar_end > cutoff
        )
        expected_input_status = (
            FeatureRuntimeStatus.READY
            if source.count
            else FeatureRuntimeStatus.UNAVAILABLE
        )
        if (
            self.physical_contract != self.physical_contract.upper()
            or self.authoritative_start_trading_day > self.authoritative_end_trading_day
            or source_outside_authority
            or self.in_sample is not True
            or self.repainting is not False
            or not isinstance(self.repaint_status, FeatureStatus)
            or not isinstance(self.input_snapshot_status, FeatureStatus)
            or not isinstance(self.status, FeatureStatus)
            or self.repaint_status.status is not FeatureRuntimeStatus.READY
            or self.repaint_status.evidence_status is not _RESEARCH
            or self.input_snapshot_status.status is not expected_input_status
            or self.input_snapshot_status.evidence_status
            is not EvidenceStatus.ACTIVE_CODE_VERIFIED
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SEGMENT_RESULT")
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        object.__setattr__(self, "as_of", cutoff)
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "ranked_windows", tuple(self.ranked_windows))

    @property
    def bar_count(self) -> int:
        return self.source_bars.count


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
    source_bars: tuple[PageComparatorSourceBars, ...] = ()
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
        sources = tuple(self.source_bars)
        if any(not isinstance(source, PageComparatorSourceBars) for source in sources):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SOURCE_BARS")
        if self.value is None:
            if sources:
                raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SOURCE_BARS")
        elif sources != tuple(segment.source_bars for segment in self.value.segments):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_SOURCE_BARS")
        object.__setattr__(self, "source_bars", sources)
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
                    entry_price=_public_decimal(entry_price),
                    exit_bar_end=raw[index].bar_end,
                    exit_price=_public_decimal(closes[index]),
                    return_pct=_public_decimal(value),
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
                entry_price=_public_decimal(entry_price),
                exit_bar_end=raw[-1].bar_end,
                exit_price=_public_decimal(closes[-1]),
                return_pct=_public_decimal(value),
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
    scores: dict[int, float] = {}
    for item in calculated:
        trade_count = item.wins + item.losses
        win_rate = item.wins / trade_count * 100 if trade_count else 0.0
        score = (item.cumulative - min(0, max_return)) / max(
            1, max_return - min_return + 1
        ) + min_drawdown / max(1, item.max_drawdown or 1)
        scores[item.window] = score
        results.append(
            PageWindowComparison(
                window=item.window,
                cumulative_return_pct=_public_decimal(item.cumulative),
                max_drawdown_pct=_public_decimal(item.max_drawdown),
                trade_count=trade_count,
                win_count=item.wins,
                loss_count=item.losses,
                win_rate_pct=_public_decimal(win_rate),
                force_closed_at_end=item.forced,
                score=_public_decimal(score),
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
            key=lambda item: (-scores[item.window], by_index[item.window]),
        )
    )
    return tuple(results), ranked


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
    facts: dict[tuple[str, str, str, ProductFrequency, datetime], ProductBar] = {}
    for item in bars:
        if not isinstance(item, ProductBar):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INPUT_IDENTITY_INVALID")
        if (
            item.bar.product != identity.product
            or item.frequency != identity.frequency
            or item.series_kind != identity.series_kind
            or item.bar.observation_eligible is not True
            or item.bar.completed is not True
            or item.bar.bar_end > as_of
        ):
            raise ValueError("NEWOW_PAGE_COMPARATOR_INPUT_IDENTITY_INVALID")
        fact_identity = (
            item.bar.product,
            item.bar.physical_contract,
            item.bar.segment_id,
            item.frequency,
            item.bar.bar_end,
        )
        prior_fact = facts.get(fact_identity)
        if prior_fact is not None:
            reason = (
                "NEWOW_PAGE_COMPARATOR_DUPLICATE_FACT"
                if prior_fact == item
                else "NEWOW_PAGE_COMPARATOR_CONFLICTING_FACT"
            )
            raise ValueError(reason)
        facts[fact_identity] = item
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


def _source_bar_facts(bars: tuple[ProductBar, ...]) -> PageComparatorSourceBars:
    if not bars:
        return PageComparatorSourceBars(0, None, None, None, None, ())
    first = bars[0].bar
    last = bars[-1].bar
    return PageComparatorSourceBars(
        count=len(bars),
        first_trading_day=first.trading_day,
        last_trading_day=last.trading_day,
        first_bar_end=first.bar_end,
        last_bar_end=last.bar_end,
        source_identities=tuple(
            dict.fromkeys(item.bar.source_identity for item in bars)
        ),
    )


def compare_page_windows(
    identity: ProductIdentity,
    bars: tuple[ProductBar, ...],
    evidence: object | None,
    *,
    authoritative_segments: tuple[ComparatorOwnerSegment, ...],
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

    try:
        owners = tuple(authoritative_segments)
    except TypeError as error:
        raise ValueError("NEWOW_PAGE_COMPARATOR_INVALID_OWNER") from error
    _validate_owners(identity, owners)
    grouped = _group_bars(identity, inputs, owners, cutoff)

    segment_results = []
    for owner, owner_bars in zip(owners, grouped, strict=True):
        source_bars = _source_bar_facts(owner_bars)
        repaint_status = FeatureStatus(FeatureRuntimeStatus.READY, _RESEARCH)
        input_snapshot_status = FeatureStatus(
            FeatureRuntimeStatus.READY
            if source_bars.count
            else FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
            None if source_bars.count else "NEWOW_PAGE_COMPARATOR_NO_SOURCE_BARS",
        )
        if len(owner_bars) < 20:
            segment_results.append(
                PageComparatorSegmentResult(
                    physical_contract=owner.physical_contract,
                    segment_id=owner.segment_id,
                    frequency=identity.frequency,
                    authoritative_start_trading_day=owner.start_trading_day,
                    authoritative_end_trading_day=owner.end_trading_day,
                    source_bars=source_bars,
                    as_of=cutoff,
                    in_sample=True,
                    repainting=False,
                    repaint_status=repaint_status,
                    input_snapshot_status=input_snapshot_status,
                    status=FeatureStatus(
                        FeatureRuntimeStatus.UNAVAILABLE,
                        _RESEARCH,
                        "NEWOW_PAGE_COMPARATOR_INSUFFICIENT_BARS",
                    ),
                    results=(),
                    ranked_windows=(),
                )
            )
            continue
        results, ranked = _score_windows(
            tuple(_calculate_window(owner_bars, window) for window in CANDIDATE_WINDOWS)
        )
        segment_results.append(
            PageComparatorSegmentResult(
                physical_contract=owner.physical_contract,
                segment_id=owner.segment_id,
                frequency=identity.frequency,
                authoritative_start_trading_day=owner.start_trading_day,
                authoritative_end_trading_day=owner.end_trading_day,
                source_bars=source_bars,
                as_of=cutoff,
                in_sample=True,
                repainting=False,
                repaint_status=repaint_status,
                input_snapshot_status=input_snapshot_status,
                status=FeatureStatus(FeatureRuntimeStatus.READY, _RESEARCH),
                results=results,
                ranked_windows=ranked,
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
        source_bars=tuple(segment.source_bars for segment in segments),
        value=value,
    )
