from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.env import PROJECT_ROOT
from app.market_data import composition
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    DominantContractSummary,
)
from app.market_data.market_read_service import MarketReadState
from app.market_data.subing_calibration import SubingCalibration, SubingCalibrationError
from app.market_data.subing_read_service import SubingReadRequest, SubingReadService
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
    SubingSignalResolution,
    SubingSignalEvaluation,
    SubingSignalStatus,
)


_SEGMENT_START = date(2026, 8, 3)
_NOW = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def test_snapshot_reads_only_the_current_rank1_contract_segment() -> None:
    """Catches actual-dominant or older same-contract bars poisoning current warm-up."""
    current = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    old_same_contract = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=date(2026, 7, 1),
        first_end=datetime(2026, 7, 1, 1, 5, tzinfo=UTC),
        first_close=Decimal("10000"),
    )
    companion = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("200"),
    )

    clean = _service({BarFrequency.M5: current, BarFrequency.M15: companion}).snapshot(
        SubingReadRequest("jm", BarFrequency.M5), now=_NOW
    )
    poisoned = _service(
        {
            BarFrequency.M5: old_same_contract + current,
            BarFrequency.M15: companion,
        }
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert poisoned == clean
    assert poisoned.actual_contract == "JM2609"
    assert poisoned.segment_start_trading_day == _SEGMENT_START
    assert poisoned.primary.snapshot is not None
    assert poisoned.primary.snapshot.trading_day == _SEGMENT_START
    assert poisoned.calibration_state == "pending"


def test_companion_is_cut_off_at_the_primary_confirmed_bar() -> None:
    """Catches a later companion observation leaking future information into the snapshot."""
    primary = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    primary_cutoff = primary[-1].bar_end
    companion = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=primary_cutoff - timedelta(minutes=15 * 48),
        first_close=Decimal("200"),
    )

    result = _service({BarFrequency.M5: primary, BarFrequency.M15: companion}).snapshot(
        SubingReadRequest("jm", BarFrequency.M5), now=_NOW
    )

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == primary_cutoff
    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_end == primary_cutoff
    assert result.companion.snapshot.bar_end <= result.primary.snapshot.bar_end


def test_live_contract_mismatch_keeps_the_snapshot_historical_only() -> None:
    """Catches bars from a different Live contract being merged into current rank1 history."""
    historical = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M5,
        count=80,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    mismatched_live = _bar(
        historical[-1].bar_end + timedelta(minutes=15),
        _SEGMENT_START,
        Decimal("9999"),
    )
    market_read = _FakeMarketRead(
        {BarFrequency.M15: historical, BarFrequency.M5: companion},
        live={BarFrequency.M15: (mismatched_live,)},
        live_contract="JM2610",
    )

    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=market_read,
        calibration=_pending_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == historical[-1].bar_end
    assert result.primary.snapshot.close == historical[-1].close
    assert result.primary.snapshot.bar_source == "canonical"
    assert result.source_mode == "canonical"
    assert result.live_observation == "unavailable"
    assert result.live_reason == "contract_mismatch"


def test_same_contract_live_bars_are_merged_after_the_historical_seam() -> None:
    """Catches available completed Live bars being ignored for an intraday current contract."""
    historical = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M5,
        count=160,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    live_primary = _bar(
        historical[-1].bar_end + timedelta(minutes=15),
        _SEGMENT_START,
        Decimal("999"),
    )
    market_read = _FakeMarketRead(
        {BarFrequency.M15: historical, BarFrequency.M5: companion},
        live={BarFrequency.M15: (live_primary,)},
    )

    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=market_read,
        calibration=_pending_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == live_primary.bar_end
    assert result.primary.snapshot.close == Decimal("999")
    assert result.primary.snapshot.bar_source == "live"
    assert result.source_mode == "canonical_live"
    assert result.live_observation == "available"
    assert result.live_reason is None
    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_end <= live_primary.bar_end


def test_companion_keeps_live_source_when_cutoff_removes_only_later_live_bars() -> None:
    """Catches companion cutoff relabeling a retained Live observation as canonical."""
    primary = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    retained_live = _bar(primary[-1].bar_end, _SEGMENT_START, Decimal("500"))
    later_live = _bar(
        primary[-1].bar_end + timedelta(minutes=5),
        _SEGMENT_START,
        Decimal("600"),
    )
    market_read = _FakeMarketRead(
        {BarFrequency.M15: primary, BarFrequency.M5: companion},
        live={BarFrequency.M5: (retained_live, later_live)},
    )

    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=market_read,
        calibration=_pending_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_end == retained_live.bar_end
    assert result.companion.snapshot.close == retained_live.close
    assert result.companion.snapshot.bar_source == "live"


def test_source_mode_uses_only_live_bars_retained_by_the_primary_cutoff() -> None:
    """Catches source_mode being decided before later companion Live bars are cut off."""
    primary = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    later_companion_live = _bar(
        primary[-1].bar_end + timedelta(minutes=5),
        _SEGMENT_START,
        Decimal("500"),
    )
    market_read = _FakeMarketRead(
        {BarFrequency.M15: primary, BarFrequency.M5: companion},
        live={BarFrequency.M5: (later_companion_live,)},
    )

    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=market_read,
        calibration=_pending_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_source == "canonical"
    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_source == "canonical"
    assert result.source_mode == "canonical"
    assert result.live_observation == "available"


def test_read_request_rejects_malformed_ascii_product_symbols() -> None:
    """Catches malformed non-product text reaching dominant resolution."""
    with pytest.raises(ValueError, match="invalid SuBing symbol"):
        SubingReadRequest("###", BarFrequency.M5)


def test_daily_snapshot_is_historical_only_and_has_no_companion() -> None:
    """Catches 1d SuBing reads consulting transient Live or inventing a companion series."""
    daily = _bars(
        frequency=BarFrequency.D1,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 6, 15, 7, 0, tzinfo=UTC),
        first_close=Decimal("100"),
        trading_day_step=True,
    )
    market_read = _HistoricalOnlyMarketRead({BarFrequency.D1: daily})

    result = SubingReadService(
        market_data=_FakeMarketData(segment_start=daily[0].trading_day),
        market_read=market_read,
        calibration=_pending_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.D1), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == daily[-1].bar_end
    assert result.primary.snapshot.bar_source == "canonical"
    assert result.companion is None
    assert result.source_mode == "canonical"
    assert result.live_observation == "not_applicable"
    assert result.live_reason == "daily_historical_only"


@pytest.mark.parametrize("frequency", [BarFrequency.M5, BarFrequency.M15])
def test_intraday_snapshot_keeps_primary_evaluation_separate_from_resolved_signal(
    monkeypatch: pytest.MonkeyPatch,
    frequency: BarFrequency,
) -> None:
    """Catches same-boundary resolution replacing the requested timeframe state."""
    companion_frequency = (
        BarFrequency.M15 if frequency is BarFrequency.M5 else BarFrequency.M5
    )
    boundary = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor",
        lambda _bars, *, timeframe, **_kwargs: _signal_factor(
            timeframe,
            boundary,
            cross=MacdCross.NONE,
        ),
    )

    result = _service_with_calibration(
        {
            frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
            companion_frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
        }
    ).snapshot(SubingReadRequest("jm", frequency), now=_NOW)

    assert result.primary_signal.status is SubingSignalStatus.NOT_MATCHED
    assert result.primary_signal.trigger_timeframe is frequency
    assert result.resolved_signal is None
    assert result.frequency is frequency


@pytest.mark.parametrize(
    ("frequency", "direction", "cross"),
    [
        (BarFrequency.M5, SubingDirection.LONG, MacdCross.GOLDEN),
        (BarFrequency.M5, SubingDirection.SHORT, MacdCross.DEAD),
        (BarFrequency.M15, SubingDirection.LONG, MacdCross.GOLDEN),
        (BarFrequency.M15, SubingDirection.SHORT, MacdCross.DEAD),
    ],
)
def test_same_boundary_dual_match_resolves_to_15m_without_overwriting_primary(
    monkeypatch: pytest.MonkeyPatch,
    frequency: BarFrequency,
    direction: SubingDirection,
    cross: MacdCross,
) -> None:
    boundary = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    companion_frequency = (
        BarFrequency.M15 if frequency is BarFrequency.M5 else BarFrequency.M5
    )
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor",
        lambda _bars, *, timeframe, **_kwargs: _signal_factor(
            timeframe,
            boundary,
            cross=cross,
            direction=direction,
        ),
    )

    result = _service_with_calibration(
        {
            frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
            companion_frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
        }
    ).snapshot(SubingReadRequest("jm", frequency), now=_NOW)

    assert result.primary_signal.status is SubingSignalStatus.MATCHED
    assert result.primary_signal.trigger_timeframe is frequency
    assert result.resolved_signal is not None
    assert result.resolved_signal.status is SubingSignalStatus.MATCHED
    assert result.resolved_signal.direction is direction
    assert result.resolved_signal.trigger_timeframe is BarFrequency.M15
    assert result.resolved_signal.lower_tf_confirmation is True
    assert (
        result.resolved_signal.resolution
        is SubingSignalResolution.HIGHER_TIMEFRAME_WINS
    )
    assert not any(
        "ZERO" in condition.code or "BAND" in condition.code
        for condition in result.resolved_signal.conditions
    )


@pytest.mark.parametrize("frequency", [BarFrequency.M5, BarFrequency.M15])
def test_same_boundary_only_primary_match_resolves_to_requested_timeframe(
    monkeypatch: pytest.MonkeyPatch,
    frequency: BarFrequency,
) -> None:
    boundary = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    companion_frequency = (
        BarFrequency.M15 if frequency is BarFrequency.M5 else BarFrequency.M5
    )
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor",
        lambda _bars, *, timeframe, **_kwargs: _signal_factor(
            timeframe,
            boundary,
            cross=MacdCross.GOLDEN if timeframe is frequency else MacdCross.NONE,
        ),
    )

    result = _service_with_calibration(
        {
            frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
            companion_frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
        }
    ).snapshot(SubingReadRequest("jm", frequency), now=_NOW)

    assert result.primary_signal.status is SubingSignalStatus.MATCHED
    assert result.resolved_signal == result.primary_signal
    assert result.resolved_signal.trigger_timeframe is frequency


@pytest.mark.parametrize("frequency", [BarFrequency.M5, BarFrequency.M15])
def test_same_boundary_opposite_matches_fail_closed_without_overwriting_primary(
    monkeypatch: pytest.MonkeyPatch,
    frequency: BarFrequency,
) -> None:
    boundary = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    companion_frequency = (
        BarFrequency.M15 if frequency is BarFrequency.M5 else BarFrequency.M5
    )
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor",
        lambda _bars, *, timeframe, **_kwargs: _signal_factor(
            timeframe,
            boundary,
            cross=MacdCross.GOLDEN,
        ),
    )

    def opposite_evaluations(primary, **_kwargs):
        assert primary.snapshot is not None
        timeframe = primary.snapshot.timeframe
        return SubingSignalEvaluation(
            status=SubingSignalStatus.MATCHED,
            direction=(
                SubingDirection.LONG
                if timeframe is BarFrequency.M5
                else SubingDirection.SHORT
            ),
            trigger_timeframe=timeframe,
            bar_end=boundary,
            lower_tf_confirmation=False,
            resolution=None,
            conditions=(),
        )

    monkeypatch.setattr(
        "app.market_data.subing_read_service.evaluate_subing_signal",
        opposite_evaluations,
    )
    result = _service_with_calibration(
        {
            frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
            companion_frequency: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
        }
    ).snapshot(SubingReadRequest("jm", frequency), now=_NOW)

    assert result.primary_signal.status is SubingSignalStatus.MATCHED
    assert result.primary_signal.trigger_timeframe is frequency
    assert result.resolved_signal is not None
    assert result.resolved_signal.status is SubingSignalStatus.NOT_MATCHED
    assert result.resolved_signal.direction is SubingDirection.NONE
    assert result.resolved_signal.error_code == "SUBING_SIGNAL_DIRECTION_CONFLICT"
    assert (
        result.resolved_signal.resolution is SubingSignalResolution.DIRECTION_CONFLICT
    )


def test_missing_calibration_keeps_intraday_signal_research_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor",
        lambda _bars, *, timeframe, **_kwargs: _signal_factor(
            timeframe,
            boundary,
            cross=MacdCross.GOLDEN,
        ),
    )
    pending = SubingCalibration(None, frozenset(), {})
    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(
            {
                BarFrequency.M5: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
                BarFrequency.M15: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
            },
            live_available=False,
        ),
        calibration=pending,
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert result.calibration_state == "pending"
    assert result.primary_signal.status is SubingSignalStatus.RESEARCH_PENDING
    assert result.resolved_signal is None


def test_daily_signal_remains_research_pending_with_accepted_intraday_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = datetime(2026, 8, 3, 7, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor",
        lambda _bars, *, timeframe, **_kwargs: _signal_factor(
            timeframe,
            boundary,
            cross=MacdCross.GOLDEN,
        ),
    )
    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_HistoricalOnlyMarketRead(
            {BarFrequency.D1: (_bar(boundary, _SEGMENT_START, Decimal("100")),)}
        ),
        calibration=_accepted_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.D1), now=_NOW)

    assert result.calibration_state == "accepted"
    assert result.primary_signal.status is SubingSignalStatus.RESEARCH_PENDING
    assert result.primary_signal.error_code == "SUBING_DAILY_RESEARCH_PENDING"
    assert result.resolved_signal is None


def test_signal_provenance_keeps_factor_and_scoped_policy_ids_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor",
        lambda _bars, *, timeframe, **_kwargs: _signal_factor(
            timeframe,
            boundary,
            cross=MacdCross.GOLDEN,
        ),
    )
    result = _service_with_calibration(
        {
            BarFrequency.M5: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
            BarFrequency.M15: (_bar(boundary, _SEGMENT_START, Decimal("100")),),
        }
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert result.macd_policy_id == "web_macd_legacy_v1"
    assert result.signal_macd_policy_id == "subing_macd_sma_window_scale2_v1"
    assert result.calibration_id == "subing_intraday_v1"


def test_composition_injects_only_the_tracked_production_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _accepted_calibration()
    observed: dict[str, object] = {}

    monkeypatch.setattr(composition, "build_market_data_service", lambda _session: "md")
    monkeypatch.setattr(composition, "build_market_read_service", lambda _session: "mr")

    def load(path):
        observed["path"] = path
        return expected

    class CapturingService:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

    monkeypatch.setattr(composition, "load_subing_calibration", load, raising=False)
    monkeypatch.setattr(composition, "SubingReadService", CapturingService)

    composition.build_subing_read_service(object())

    assert observed == {
        "path": PROJECT_ROOT
        / "data/research_policies/subing_calibration_intraday_v1.json",
        "market_data": "md",
        "market_read": "mr",
        "calibration": expected,
    }


def test_composition_propagates_malformed_calibration_without_defaulting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "load_subing_calibration",
        lambda _path: (_ for _ in ()).throw(SubingCalibrationError()),
        raising=False,
    )

    with pytest.raises(SubingCalibrationError, match="SUBING_CALIBRATION_INVALID"):
        composition.build_subing_read_service(object())


class _FakeMarketData:
    def __init__(self, *, segment_start: date = _SEGMENT_START) -> None:
        self.segment_start = segment_start

    def list_latest_dominants(self) -> tuple[DominantContractSummary, ...]:
        return (
            DominantContractSummary(
                symbol="jm",
                product_name="焦煤",
                sector="black",
                exchange="DCE",
                actual_contract="JM2609",
                dominant_mapping_date=date(2026, 8, 3),
            ),
        )

    def latest_dominant_segment(self, symbol: str) -> DominantContractSegmentSummary:
        assert symbol == "jm"
        return DominantContractSegmentSummary(
            symbol="jm",
            contract="JM2609",
            start_trading_day=self.segment_start,
            end_trading_day=date(2026, 8, 3),
        )


class _FakeMarketRead:
    def __init__(
        self,
        history: dict[BarFrequency, tuple[CanonicalBar, ...]],
        *,
        live: dict[BarFrequency, tuple[CanonicalBar, ...]] | None = None,
        live_contract: str = "JM2609",
        live_available: bool = True,
    ) -> None:
        self.history = history
        self.live = live or {}
        self.live_contract = live_contract
        self.live_available = live_available

    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        assert request.series_kind is SeriesKind.CONTRACT
        assert request.symbol == "jm"
        assert request.contract == "JM2609"
        assert request.limit == 300
        bars = self.history[request.frequency]
        return MarketSeriesPageResult(
            request_identity={},
            bars=bars,
            canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=(),
        )

    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        assert identity.series_kind is SeriesKind.CONTRACT
        assert identity.contract == "JM2609"
        assert now == _NOW
        return MarketReadState(
            symbol="jm",
            series_kind="contract",
            frequency=identity.frequency.value,
            operational=True,
            phase="trading",
            trading_day=_SEGMENT_START,
            live_eligible=True,
            live_available=self.live_available,
            live_contract=self.live_contract,
            canonical_end=self.history[identity.frequency][-1].bar_end,
            after_market={},
        )

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]:
        assert identity.series_kind is SeriesKind.CONTRACT
        assert identity.contract == "JM2609"
        assert now == _NOW
        return self.live.get(identity.frequency, ())


class _HistoricalOnlyMarketRead(_FakeMarketRead):
    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        raise AssertionError("1d SuBing must not query Live state")

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]:
        raise AssertionError("1d SuBing must not query Live snapshot")


def _service(
    history: dict[BarFrequency, tuple[CanonicalBar, ...]],
) -> SubingReadService:
    return SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(history, live_available=False),
        calibration=_pending_calibration(),
    )


def _service_with_calibration(
    history: dict[BarFrequency, tuple[CanonicalBar, ...]],
) -> SubingReadService:
    return SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(history, live_available=False),
        calibration=_accepted_calibration(),
    )


def _accepted_calibration() -> SubingCalibration:
    return SubingCalibration(
        calibration_id="subing_intraday_v1",
        accepted_timeframes=frozenset({BarFrequency.M5, BarFrequency.M15}),
        slope_flat_threshold_bps_per_bar={
            BarFrequency.M5: Decimal("0.688190651160584793944957992"),
            BarFrequency.M15: Decimal("1.329531078893356968545882036"),
        },
    )


def _pending_calibration() -> SubingCalibration:
    return SubingCalibration(None, frozenset(), {})


def _signal_factor(
    timeframe: BarFrequency,
    bar_end: datetime,
    *,
    cross: MacdCross,
    direction: SubingDirection = SubingDirection.LONG,
) -> SubingFactorResult:
    is_long = direction is SubingDirection.LONG
    signed = Decimal("2") if is_long else Decimal("-2")
    return SubingFactorResult(
        SubingFactorStatus.READY,
        SubingFactorSnapshot(
            timeframe=timeframe,
            bar_end=bar_end,
            trading_day=_SEGMENT_START,
            contract="JM2609",
            segment_start_trading_day=_SEGMENT_START,
            bar_source="canonical",
            close=Decimal("101") if is_long else Decimal("99"),
            ema21=Decimal("100"),
            price_side=PriceSide.ABOVE if is_long else PriceSide.BELOW,
            slope_5_raw=signed,
            slope_10_raw=signed,
            slope_5_bps_per_bar=signed,
            slope_10_bps_per_bar=signed,
            macd_dif=Decimal("1") if is_long else Decimal("-1"),
            macd_dea=Decimal("0"),
            macd_histogram=signed,
            macd_cross=cross,
            macd_cross_level=Decimal("0.5"),
            macd_zero_distance_abs=Decimal("999999"),
            macd_zero_distance_bps=Decimal("999999"),
            volume=Decimal("350"),
            previous_volume=Decimal("100"),
            volume_ratio_prev=Decimal("3.5"),
        ),
    )


def _bars(
    *,
    frequency: BarFrequency,
    count: int,
    trading_day: date,
    first_end: datetime,
    first_close: Decimal,
    trading_day_step: bool = False,
) -> tuple[CanonicalBar, ...]:
    minutes = {
        BarFrequency.M5: 5,
        BarFrequency.M15: 15,
        BarFrequency.D1: 24 * 60,
    }[frequency]
    return tuple(
        _bar(
            first_end + timedelta(minutes=minutes * index),
            trading_day + timedelta(days=index) if trading_day_step else trading_day,
            first_close + Decimal(index),
        )
        for index in range(count)
    )


def _bar(bar_end: datetime, trading_day: date, close: Decimal) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("100"),
        turnover=Decimal("1000"),
        open_interest=Decimal("200"),
    )
