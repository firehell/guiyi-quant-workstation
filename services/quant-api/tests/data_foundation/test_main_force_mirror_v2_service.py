from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.actual_dominant_research import ActualDominantResearchSeries
from app.market_data.composition import member_rank_repository_from_env
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.errors import InfrastructureError
from app.market_data.main_force_mirror_v2_service import (
    MainForceMirrorV2Error,
    MainForceMirrorV2Service,
)
from app.market_data.member_rank_snapshot import (
    MemberRankDay,
    MemberRankRow,
    MemberRankSnapshotError,
)


_DAY = date(2026, 8, 21)
_PREVIOUS_DAY = date(2026, 8, 20)


def _bar(
    index: int,
    *,
    trading_day: date = _DAY,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    volume: float | None = None,
    open_interest: float | None = None,
) -> CanonicalBar:
    close_value = 100.0 + index if close is None else close
    return CanonicalBar(
        datetime(2026, 8, 21, tzinfo=UTC) + timedelta(hours=index),
        trading_day,
        Decimal(str(close_value - 0.5 if open_ is None else open_)),
        Decimal(str(close_value + 1.0 if high is None else high)),
        Decimal(str(close_value - 1.0 if low is None else low)),
        Decimal(str(close_value)),
        Decimal(str(1000.0 + index if volume is None else volume)),
        None,
        Decimal(str(5000.0 + 10.0 * index if open_interest is None else open_interest)),
    )


def _page(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> MarketSeriesPageResult:
    return MarketSeriesPageResult(
        request_identity={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "contract": None,
            "frequency": "60m",
            "before": None,
            "limit": len(bars),
        },
        bars=bars,
        canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
        has_more_before=True,
        next_before=bars[0].bar_end,
        resolved_contract_segments=segments,
    )


def _series(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> MarketSeriesResult:
    return MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=segments,
    )


class _FailingMarketData:
    def query_page(self, request):
        raise AssertionError("unsupported requests must fail before market reads")


class _Coverage:
    history_floor = date(2010, 1, 4)

    def __init__(self, previous: dict[date, date] | None = None) -> None:
        self.previous = previous or {_DAY: _PREVIOUS_DAY}
        self.requests: list[tuple[str, date]] = []

    def previous_trading_day(self, symbol: str, trading_day: date) -> date:
        self.requests.append((symbol, trading_day))
        try:
            return self.previous[trading_day]
        except KeyError as exc:
            raise InfrastructureError("COMPLETE_TRADING_DAY_MISSING") from exc


class _Loader:
    def __init__(self, loaded: ActualDominantResearchSeries) -> None:
        self.loaded = loaded
        self.requests: list[dict[str, object]] = []

    def load(self, **kwargs) -> ActualDominantResearchSeries:
        self.requests.append(kwargs)
        return self.loaded


class _MarketData:
    def __init__(
        self,
        page: MarketSeriesPageResult,
        *,
        actual_history: MarketSeriesResult | None = None,
        contract_history: MarketSeriesResult | None = None,
    ) -> None:
        self.page = page
        self.actual_history = actual_history
        self.contract_history = contract_history
        self.page_requests = []
        self.actual_requests = []
        self.contract_requests = []

    def query_page(self, request):
        self.page_requests.append(request)
        return self.page

    def query_actual_dominant_trading_days(self, request):
        self.actual_requests.append(request)
        if self.actual_history is None:
            raise AssertionError("actual history query was not expected")
        return self.actual_history

    def query_contract_trading_days(self, request):
        self.contract_requests.append(request)
        if self.contract_history is None:
            raise AssertionError("contract history query was not expected")
        return self.contract_history


def _member_day(
    physical_contract: str,
    trade_date: date,
    *,
    change: int = 10,
) -> MemberRankDay:
    rows = tuple(
        MemberRankRow(
            physical_contract=physical_contract,
            trade_date=trade_date,
            rank_by=rank_by,
            rank=rank,
            member_name=f"member-{rank_by}-{rank}",
            value=Decimal("100"),
            change=Decimal(change if rank_by == "long" else 0),
        )
        for rank_by in ("volume", "long", "short")
        for rank in range(1, 21)
    )
    return MemberRankDay(physical_contract, trade_date, rows)


class _Repository:
    def __init__(
        self,
        *,
        current: dict[tuple[str, date], MemberRankDay | None] | None = None,
        prior: tuple[MemberRankDay, ...] = (),
        admitted_products: tuple[str, ...] = ("jm",),
    ) -> None:
        self.current = current or {}
        self.prior = prior
        self.day_requests: list[tuple[str, date]] = []
        self.rank1_requests: list[tuple[str, date, int, dict[date, str]]] = []
        self.contract_requests: list[tuple[str, date, int]] = []
        self.descriptor = SimpleNamespace(
            dataset_id="fixture-member-v1",
            schema_version=1,
            admitted_products=admitted_products,
            partitions=(
                SimpleNamespace(
                    coverage_start=date(2026, 7, 1),
                    coverage_end=_PREVIOUS_DAY,
                ),
            ),
        )

    def day(self, physical_contract: str, trade_date: date):
        self.day_requests.append((physical_contract, trade_date))
        return self.current.get((physical_contract, trade_date))

    def rank1_days_before(self, symbol, before, *, limit, contract_by_day):
        self.rank1_requests.append((symbol, before, limit, dict(contract_by_day)))
        return self.prior

    def contract_days_before(self, contract, before, *, limit):
        self.contract_requests.append((contract, before, limit))
        return self.prior


def _service(
    market_data,
    loader,
    *,
    repository=None,
    coverage=None,
) -> MainForceMirrorV2Service:
    return MainForceMirrorV2Service(
        market_data=market_data,
        segment_loader=loader,
        coverage=coverage or _Coverage(),
        member_repository=repository,
    )


def test_service_rejects_unsupported_identity_before_reading_data() -> None:
    service = _service(_FailingMarketData(), object())

    with pytest.raises(
        MainForceMirrorV2Error, match="MFM_V2_UNSUPPORTED_SERIES_KIND"
    ):
        service.query_page(SeriesPageQuery("continuous", "jm", "60m"))
    with pytest.raises(
        MainForceMirrorV2Error, match="MFM_V2_UNSUPPORTED_FREQUENCY"
    ):
        service.query_page(SeriesPageQuery("actual_dominant", "jm", "15m"))


def test_actual_dominant_roll_uses_new_contract_t_minus_one_and_cross_contract_baseline() -> None:
    older_days = tuple(date(2026, 7, day) for day in range(1, 21))
    prior = tuple(_member_day("JM2609", day, change=1) for day in older_days)
    current = _member_day("JM2701", _PREVIOUS_DAY, change=2)
    repository = _Repository(
        current={("JM2701", _PREVIOUS_DAY): current},
        prior=prior,
    )
    target_bar = _bar(0)
    target_segment = (ResolvedContractSegment("JM2701", _DAY, _DAY),)
    target = _page((target_bar,), target_segment)
    calculation = _series((target_bar,), target_segment)
    rank1_bars = tuple(
        _bar(index, trading_day=day)
        for index, day in enumerate((*older_days, _DAY))
    )
    rank1_segments = (
        ResolvedContractSegment("JM2609", older_days[0], older_days[-1]),
        ResolvedContractSegment("JM2701", _DAY, _DAY),
    )
    market_data = _MarketData(
        target,
        actual_history=_series(rank1_bars, rank1_segments),
    )
    loader = _Loader(
        ActualDominantResearchSeries(
            {BarFrequency.H1: calculation},
            target_segment,
        )
    )

    result = _service(market_data, loader, repository=repository).query_page(
        SeriesPageQuery("actual_dominant", "jm", "60m", limit=1)
    )

    member = result.points[0].member
    assert member is not None
    assert member.member_trade_date == _PREVIOUS_DAY
    assert member.status == "ready"
    assert repository.day_requests == [("JM2701", _PREVIOUS_DAY)]
    assert repository.rank1_requests[0][:3] == ("jm", _PREVIOUS_DAY, 60)
    assert set(repository.rank1_requests[0][3].values()) == {"JM2609", "JM2701"}
    assert loader.requests == [
        {
            "symbol": "jm",
            "frequencies": (BarFrequency.H1,),
            "since": _DAY,
            "through": _DAY,
        }
    ]


def _latch_bars() -> tuple[CanonicalBar, ...]:
    values: list[CanonicalBar] = []
    for index in range(70):
        close = 100.0 + index if index <= 29 else 200.0 + (index - 30)
        open_interest = (
            5000.0 + 10.0 * index
            if index <= 29
            else 5150.0 - 10.0 * (index - 30)
        )
        values.append(
            _bar(
                index,
                close=close,
                open_interest=open_interest,
            )
        )
    values[30] = _bar(
        30,
        open_=150,
        high=250,
        low=128,
        close=200,
        volume=5000,
        open_interest=5150,
    )
    values[68] = _bar(
        68,
        close=238,
        volume=3000,
        open_interest=4830,
    )
    values[69] = _bar(
        69,
        close=239,
        high=243,
        low=232,
        volume=5000,
        open_interest=4730,
    )
    return tuple(values)


def test_service_computes_latch_from_true_segment_start_before_exact_page_slice() -> None:
    full_bars = _latch_bars()
    segment = (ResolvedContractSegment("JM2609", _DAY, _DAY),)
    target = _page((full_bars[-1],), segment)
    calculation = _series(full_bars, segment)
    loader = _Loader(
        ActualDominantResearchSeries({BarFrequency.H1: calculation}, segment)
    )

    result = _service(_MarketData(target), loader).query_page(
        SeriesPageQuery("actual_dominant", "jm", "60m", limit=1)
    )

    assert len(result.points) == 1
    assert result.points[0].bar_end == full_bars[-1].bar_end
    assert result.points[0].caution_ready is True
    assert result.points[0].long_caution_score == 70.0
    assert result.points[0].caution is None


def test_diagnostic_page_slices_audit_from_the_same_validated_full_prefix() -> None:
    """Catches page-only audit calculation or bypassed actual-dominant identity."""
    full_bars = _latch_bars()
    segment = (ResolvedContractSegment("JM2609", _DAY, _DAY),)
    target = _page((full_bars[-1],), segment)
    calculation = _series(full_bars, segment)
    loader = _Loader(
        ActualDominantResearchSeries({BarFrequency.H1: calculation}, segment)
    )
    request = SeriesPageQuery("actual_dominant", "jm", "60m", limit=1)

    result = _service(_MarketData(target), loader).query_diagnostic_page(request)

    assert len(result.page.points) == 1
    assert len(result.audit_trace) == 1
    assert result.audit_trace[0].bar_end == result.page.points[0].bar_end
    assert result.audit_trace[0].physical_contract == "JM2609"
    assert result.audit_trace[0].long_score == 70.0
    assert result.audit_trace[0].long_candidate is True
    assert result.audit_trace[0].long_disarmed_suppressed is True
    assert result.page.points[0].caution is None
    assert loader.requests == [
        {
            "symbol": "jm",
            "frequencies": (BarFrequency.H1,),
            "since": _DAY,
            "through": _DAY,
        }
    ]


def test_no_member_configuration_preserves_core_pressure_as_dataset_unavailable() -> None:
    bars = tuple(_bar(index) for index in range(31))
    segment = (ResolvedContractSegment("JM2609", _DAY, _DAY),)
    target = _page((bars[-1],), segment)
    loader = _Loader(
        ActualDominantResearchSeries(
            {BarFrequency.H1: _series(bars, segment)},
            segment,
        )
    )

    result = _service(_MarketData(target), loader).query_page(
        SeriesPageQuery("actual_dominant", "jm", "60m", limit=1)
    )

    assert result.points[0].pressure_ready is True
    assert result.points[0].member is None
    assert result.member_dataset.status == "unavailable"
    assert result.member_dataset.dataset_id is None


def test_no_member_configuration_still_rejects_target_loader_contract_mismatch() -> None:
    bars = tuple(_bar(index) for index in range(31))
    target_segment = (ResolvedContractSegment("JM2701", _DAY, _DAY),)
    loader_segment = (ResolvedContractSegment("JM2609", _DAY, _DAY),)
    target = _page((bars[-1],), target_segment)
    loader = _Loader(
        ActualDominantResearchSeries(
            {BarFrequency.H1: _series(bars, loader_segment)},
            loader_segment,
        )
    )

    with pytest.raises(
        MainForceMirrorV2Error,
        match="MFM_V2_MARKET_IDENTITY_CONFLICT",
    ):
        _service(_MarketData(target), loader).query_page(
            SeriesPageQuery("actual_dominant", "jm", "60m", limit=1)
        )


def test_missing_current_contract_day_is_not_filled_from_available_baseline() -> None:
    prior = tuple(
        _member_day("JM2609", date(2026, 7, day), change=1)
        for day in range(1, 21)
    )
    repository = _Repository(prior=prior)
    bar = _bar(0)
    segment = (ResolvedContractSegment("JM2609", _DAY, _DAY),)
    target = _page((bar,), segment)
    market_data = _MarketData(
        target,
        contract_history=_series((bar,), ()),
    )

    result = _service(
        market_data,
        object(),
        repository=repository,
    ).query_page(
        SeriesPageQuery(
            SeriesKind.CONTRACT,
            "jm",
            BarFrequency.H1,
            limit=1,
            contract="JM2609",
        )
    )

    member = result.points[0].member
    assert member is not None
    assert member.status == "unavailable"
    assert member.member_trade_date == _PREVIOUS_DAY
    assert member.unavailable_reason == "MFM_V2_MEMBER_CONTRACT_DAY_INCOMPLETE"
    assert repository.contract_requests == []
    assert market_data.contract_requests[0].since == date(2010, 1, 4)


def test_repository_environment_is_absent_partial_or_corrupt_fail_closed(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("GUIYI_RESEARCH_DATA_ROOT", raising=False)
    monkeypatch.delenv("GUIYI_MAIN_FORCE_MEMBER_RANK_DATASET_ID", raising=False)
    assert member_rank_repository_from_env(None) is None

    monkeypatch.setenv("GUIYI_RESEARCH_DATA_ROOT", str(tmp_path))
    with pytest.raises(
        MainForceMirrorV2Error,
        match="MFM_V2_MEMBER_DATASET_IDENTITY_CONFLICT",
    ):
        member_rank_repository_from_env(None)

    monkeypatch.setenv("GUIYI_MAIN_FORCE_MEMBER_RANK_DATASET_ID", "broken")
    with pytest.raises(
        MainForceMirrorV2Error,
        match="MFM_V2_MEMBER_DATASET_INVALID",
    ) as captured:
        member_rank_repository_from_env(None)

    assert str(tmp_path) not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    ("root_value", "dataset_id"),
    [
        ("", ""),
        ("   ", "fixture-member-v1"),
        ("/tmp/research", "\t"),
    ],
)
def test_repository_environment_present_empty_or_whitespace_is_identity_conflict(
    monkeypatch,
    root_value: str,
    dataset_id: str,
) -> None:
    monkeypatch.setenv("GUIYI_RESEARCH_DATA_ROOT", root_value)
    monkeypatch.setenv("GUIYI_MAIN_FORCE_MEMBER_RANK_DATASET_ID", dataset_id)

    with pytest.raises(
        MainForceMirrorV2Error,
        match="MFM_V2_MEMBER_DATASET_IDENTITY_CONFLICT",
    ) as captured:
        member_rank_repository_from_env(None)

    assert captured.value.__cause__ is None


def test_member_contract_day_identity_corruption_is_request_level_invalid() -> None:
    class _CorruptRepository(_Repository):
        def day(self, physical_contract: str, trade_date: date):
            raise MemberRankSnapshotError("MEMBER_CONTRACT_DAY_IDENTITY_CORRUPT")

    bar = _bar(0)
    segment = (ResolvedContractSegment("JM2609", _DAY, _DAY),)
    target = _page((bar,), segment)
    market_data = _MarketData(
        target,
        contract_history=_series((bar,), ()),
    )

    with pytest.raises(
        MainForceMirrorV2Error,
        match="MFM_V2_MEMBER_DATASET_INVALID",
    ) as captured:
        _service(
            market_data,
            object(),
            repository=_CorruptRepository(),
        ).query_page(
            SeriesPageQuery(
                SeriesKind.CONTRACT,
                "jm",
                BarFrequency.H1,
                limit=1,
                contract="JM2609",
            )
        )

    assert captured.value.__cause__ is None


def test_actual_history_rank1_identity_must_match_loader_on_overlap() -> None:
    bar = _bar(0)
    target_segment = (ResolvedContractSegment("JM2701", _DAY, _DAY),)
    history_segment = (ResolvedContractSegment("JM2609", _DAY, _DAY),)
    target = _page((bar,), target_segment)
    market_data = _MarketData(
        target,
        actual_history=_series((bar,), history_segment),
    )
    loader = _Loader(
        ActualDominantResearchSeries(
            {BarFrequency.H1: _series((bar,), target_segment)},
            target_segment,
        )
    )

    with pytest.raises(
        MainForceMirrorV2Error,
        match="MFM_V2_MARKET_IDENTITY_CONFLICT",
    ):
        _service(
            market_data,
            loader,
            repository=_Repository(),
        ).query_page(
            SeriesPageQuery("actual_dominant", "jm", "60m", limit=1)
        )

    assert len(market_data.page_requests) == 1
    assert len(loader.requests) == 1
    assert len(market_data.actual_requests) == 1
