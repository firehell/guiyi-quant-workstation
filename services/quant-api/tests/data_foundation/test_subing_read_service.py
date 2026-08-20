from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data import composition
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    DatasetKey,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    DominantContractSummary,
    MarketDataError,
    MarketDataService,
)
from app.market_data.market_read_service import MarketReadState
from app.market_data.subing_calibration import SubingCalibration, SubingCalibrationError
from app.market_data.subing_lifecycle import (
    LifecycleAvailability,
    LifecycleStage,
    evaluate_subing_lifecycle as reduce_subing_lifecycle,
)
from app.market_data.subing_lifecycle_policy import (
    SubingLifecyclePolicyError,
    load_subing_lifecycle_policy,
)
from app.market_data.subing_read_service import (
    SubingReadRequest,
    SubingReadService,
    SubingReadSnapshot,
)
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
    calculate_subing_factor,
    calculate_subing_factor_series as calculate_factor_series,
)
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import Exchange, Instrument, TradingSession


_SEGMENT_START = date(2026, 8, 3)
_NOW = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)


@pytest.fixture
def real_market_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            (
                Exchange(code="DCE", name="DCE"),
                Instrument(
                    symbol="jm",
                    name="JM",
                    exchange_code="DCE",
                    is_active=True,
                ),
                TradingSession(
                    exchange_code="DCE",
                    instrument_symbol="jm",
                    session_name="day",
                    start_time=time(9),
                    end_time=time(15),
                    effective_from=date(2025, 1, 1),
                    is_active=True,
                ),
            )
        )
        session.commit()
        yield session


def test_current_intraday_snapshot_uses_real_latest_page_beyond_canonical_edge(
    real_market_session: Session,
    tmp_path: Path,
) -> None:
    """Catches current reads sending wall-clock cutoffs beyond Catalog coverage."""
    history = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=150,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=50,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }
    live = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=3,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 12, 35, tzinfo=UTC),
            first_close=Decimal("250"),
        ),
        BarFrequency.M15: (
            _bar(
                datetime(2026, 8, 3, 12, 45, tzinfo=UTC),
                _SEGMENT_START,
                Decimal("250"),
            ),
        ),
    }
    store = CanonicalMonthlyStore(tmp_path)
    catalog = MarketCatalog(real_market_session, tmp_path)
    for frequency in (BarFrequency.M5, BarFrequency.M15):
        bars = history[frequency]
        partition = store.publish(
            PublishRequest(
                dataset=DatasetKey("contract", "jm", "JM2609", frequency),
                year=bars[0].trading_day.year,
                month=bars[0].trading_day.month,
                bars=bars,
                expected_bar_ends=tuple(bar.bar_end for bar in bars),
            )
        )
        catalog.register_partition(partition)
    real_market_session.commit()

    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_RealHistoryMarketRead(
            history,
            MarketDataService(catalog, store),
            live=live,
            live_available=True,
        ),
        calibration=_pending_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == datetime(
        2026, 8, 3, 12, 45, tzinfo=UTC
    )
    assert result.companion is not None
    assert result.companion.snapshot is not None
    assert result.companion.snapshot.bar_end == datetime(
        2026, 8, 3, 12, 45, tzinfo=UTC
    )
    assert result.source_mode == "canonical_live"


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


def test_snapshot_fails_closed_when_history_extends_past_rank1_segment() -> None:
    """Catches post-rank1 same-contract bars poisoning Factor and Signal state."""
    current = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    post_segment = _bars(
        frequency=BarFrequency.M5,
        count=50,
        trading_day=date(2026, 8, 4),
        first_end=datetime(2026, 8, 4, 1, 5, tzinfo=UTC),
        first_close=Decimal("900"),
    )
    companion = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("200"),
    )

    with pytest.raises(MarketDataError, match="DOMINANT_SEGMENT_HISTORY_INCONSISTENT"):
        _service(
            {
                BarFrequency.M5: current + post_segment,
                BarFrequency.M15: companion,
            }
        ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)


def test_future_historical_bar_is_excluded_from_v1_and_lifecycle() -> None:
    completed_5m = _bars(
        frequency=BarFrequency.M5,
        count=150,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    completed_15m = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    future = _bar(_NOW + timedelta(minutes=5), _SEGMENT_START, Decimal("999"))

    result = _service_with_lifecycle(
        {
            BarFrequency.M5: completed_5m + (future,),
            BarFrequency.M15: completed_15m,
        }
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == completed_5m[-1].bar_end
    assert result.lifecycle.observed_at == completed_5m[-1].bar_end


def test_current_latest_bootstrap_restarts_strictly_after_concurrent_future_publish() -> None:
    """Catches a post-state Canonical publish shrinking the causal 300-Bar projection."""
    history = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=400,
            trading_day=_SEGMENT_START,
            first_end=_NOW - timedelta(minutes=5 * 398),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=400,
            trading_day=_SEGMENT_START,
            first_end=_NOW - timedelta(minutes=15 * 398),
            first_close=Decimal("100"),
        ),
    }
    strict = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_CursorHonoringMarketRead(history, live_available=False),
        calibration=_accepted_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)
    raced = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_StaleCanonicalEndMarketRead(history, live_available=False),
        calibration=_accepted_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert raced.primary == strict.primary
    assert raced.companion == strict.companion
    assert raced.primary.snapshot is not None
    assert raced.primary.snapshot.bar_end == _NOW
    assert raced.companion is not None
    assert raced.companion.snapshot is not None
    assert raced.companion.snapshot.bar_end == _NOW


def test_future_live_bar_is_excluded_from_v1_and_lifecycle() -> None:
    history = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=150,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=50,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }
    future = _bar(_NOW + timedelta(minutes=5), _SEGMENT_START, Decimal("999"))

    result = _service_with_lifecycle(
        history,
        live={BarFrequency.M5: (future,), BarFrequency.M15: ()},
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == history[BarFrequency.M5][-1].bar_end
    assert result.lifecycle.observed_at == history[BarFrequency.M5][-1].bar_end


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "rb"),
        ("series_kind", SeriesKind.ACTUAL_DOMINANT.value),
        ("frequency", BarFrequency.M30.value),
    ],
)
def test_wrong_market_read_state_identity_cannot_admit_live(
    field: str,
    value: str,
) -> None:
    history = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=150,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=50,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }
    live_bar = _bar(
        history[BarFrequency.M5][-1].bar_end + timedelta(minutes=5),
        _SEGMENT_START,
        Decimal("999"),
    )
    canonical = _service_with_lifecycle(history).snapshot(
        SubingReadRequest("jm", BarFrequency.M5), now=_NOW
    )
    invalid = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_StateIdentityOverrideMarketRead(
            history,
            live={BarFrequency.M5: (live_bar,), BarFrequency.M15: ()},
            field=field,
            value=value,
        ),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(history),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert invalid.primary == canonical.primary
    assert invalid.lifecycle == canonical.lifecycle
    assert invalid.source_mode == "canonical"
    assert invalid.live_reason == "live_unavailable"


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


def test_source_mode_retains_live_companion_provenance_when_factor_is_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = datetime(2026, 8, 3, 1, 15, tzinfo=UTC)
    history = {
        BarFrequency.M15: (
            _bar(boundary, _SEGMENT_START, Decimal("100")),
        ),
        BarFrequency.M5: (
            _bar(boundary - timedelta(minutes=10), _SEGMENT_START, Decimal("100")),
        ),
    }
    retained_live = _bar(boundary, _SEGMENT_START, Decimal("101"))

    def factor_series(bars, *, timeframe, **_kwargs):
        if timeframe is BarFrequency.M5:
            return tuple(
                SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None)
                for _bar_value in bars
            )
        return _repeat_factor(
            bars,
            _signal_factor(timeframe, boundary, cross=MacdCross.NONE),
        )

    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        factor_series,
    )
    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(
            history,
            live={BarFrequency.M5: (retained_live,), BarFrequency.M15: ()},
        ),
        calibration=_accepted_calibration(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert result.companion is not None
    assert result.companion.status is SubingFactorStatus.INSUFFICIENT_DATA
    assert result.companion.snapshot is None
    assert result.source_mode == "canonical_live"


@pytest.mark.parametrize(
    ("requested", "primary_count", "companion_count"),
    [
        (BarFrequency.M5, 150, 55),
        (BarFrequency.M15, 45, 150),
        (BarFrequency.M5, 10, 50),
        (BarFrequency.M15, 3, 150),
    ],
)
def test_full_factor_series_companion_projection_matches_cutoff_prefix(
    requested: BarFrequency,
    primary_count: int,
    companion_count: int,
) -> None:
    companion_frequency = _companion_frequency(requested)
    history = {
        requested: _bars(
            frequency=requested,
            count=primary_count,
            trading_day=_SEGMENT_START,
            first_end=_first_end(requested),
            first_close=Decimal("100"),
        ),
        companion_frequency: _bars(
            frequency=companion_frequency,
            count=companion_count,
            trading_day=_SEGMENT_START,
            first_end=_first_end(companion_frequency),
            first_close=Decimal("200"),
        ),
    }

    result = _service_with_calibration(history).snapshot(
        SubingReadRequest("jm", requested), now=_NOW
    )

    assert result.primary.snapshot is not None or primary_count < 21
    primary_cutoff = history[requested][-1].bar_end
    completed_prefix = tuple(
        bar
        for bar in history[companion_frequency]
        if bar.bar_end <= min(primary_cutoff, _NOW)
    )
    expected = calculate_subing_factor(
        completed_prefix,
        timeframe=companion_frequency,
        contract="JM2609",
        segment_start_trading_day=_SEGMENT_START,
        latest_bar_source="canonical",
    )
    assert result.companion == expected


@pytest.mark.parametrize(
    ("requested", "expected_status"),
    [
        (BarFrequency.M5, SubingFactorStatus.READY),
        (BarFrequency.M15, SubingFactorStatus.READY),
        (BarFrequency.M5, SubingFactorStatus.INSUFFICIENT_DATA),
        (BarFrequency.M15, SubingFactorStatus.INSUFFICIENT_DATA),
    ],
)
def test_live_companion_projection_matches_exact_cutoff_prefix_and_source(
    requested: BarFrequency,
    expected_status: SubingFactorStatus,
) -> None:
    companion_frequency = _companion_frequency(requested)
    ready = expected_status is SubingFactorStatus.READY
    if ready:
        primary_count = 150 if requested is BarFrequency.M5 else 50
        companion_count = 50 if companion_frequency is BarFrequency.M15 else 150
        historical_companion_count = (
            40 if companion_frequency is BarFrequency.M15 else 120
        )
    else:
        primary_count = 6 if requested is BarFrequency.M5 else 2
        companion_count = 2
        historical_companion_count = 1
    primary = _bars(
        frequency=requested,
        count=primary_count,
        trading_day=_SEGMENT_START,
        first_end=_first_end(requested),
        first_close=Decimal("100"),
    )
    if ready:
        companion = _bars(
            frequency=companion_frequency,
            count=companion_count,
            trading_day=_SEGMENT_START,
            first_end=_first_end(companion_frequency),
            first_close=Decimal("200"),
        )
    else:
        companion = (
            _bar(_first_end(companion_frequency), _SEGMENT_START, Decimal("200")),
            _bar(primary[-1].bar_end, _SEGMENT_START, Decimal("201")),
        )
    history = {
        requested: primary,
        companion_frequency: companion[:historical_companion_count],
    }
    live = {
        requested: (),
        companion_frequency: companion[historical_companion_count:],
    }

    result = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(history, live=live),
        calibration=_accepted_calibration(),
    ).snapshot(SubingReadRequest("jm", requested), now=_NOW)

    completed_prefix = tuple(
        bar for bar in companion if bar.bar_end <= min(primary[-1].bar_end, _NOW)
    )
    expected = calculate_subing_factor(
        completed_prefix,
        timeframe=companion_frequency,
        contract="JM2609",
        segment_start_trading_day=_SEGMENT_START,
        latest_bar_source="live",
    )
    assert result.companion == expected
    assert result.companion.status is expected_status
    assert result.source_mode == "canonical_live"


def test_read_request_rejects_malformed_ascii_product_symbols() -> None:
    """Catches malformed non-product text reaching dominant resolution."""
    with pytest.raises(ValueError, match="invalid SuBing symbol"):
        SubingReadRequest("###", BarFrequency.M5)


def test_daily_snapshot_is_historical_only_and_has_no_companion() -> None:
    """Catches 1d SuBing reads consulting transient Live or inventing a companion series."""
    daily = _bars(
        frequency=BarFrequency.D1,
        count=50,
        trading_day=date(2026, 6, 15),
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


def test_intraday_lifecycle_is_independent_of_requested_v1_timeframe() -> None:
    bars = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=150,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=50,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }
    service = _service_with_lifecycle(bars)

    requested_5m = service.snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)
    requested_15m = service.snapshot(
        SubingReadRequest("jm", BarFrequency.M15), now=_NOW
    )

    assert requested_5m.frequency is BarFrequency.M5
    assert requested_15m.frequency is BarFrequency.M15
    assert requested_5m.lifecycle == requested_15m.lifecycle
    assert requested_5m.lifecycle.availability is LifecycleAvailability.READY


@pytest.mark.parametrize("requested", (BarFrequency.M5, BarFrequency.M15))
def test_long_segment_preserves_legacy_v1_latest_300_projection(
    requested: BarFrequency,
) -> None:
    """Catches lifecycle pagination silently reseeding frozen V1 outputs."""
    full = _long_segment_bars()
    paged = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_CursorHonoringMarketRead(full, live_available=False),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(full),
    ).snapshot(SubingReadRequest("jm", requested), now=_NOW)
    legacy_window = _service_with_lifecycle(
        {frequency: bars[-300:] for frequency, bars in full.items()}
    ).snapshot(SubingReadRequest("jm", requested), now=_NOW)

    assert _v1_projection(paged) == _v1_projection(legacy_window)


def test_long_segment_lifecycle_matches_direct_full_segment_reducer() -> None:
    """Catches a single latest-page read recreating opportunity identity after 300 bars."""
    full = _long_segment_bars()
    service_snapshot = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_CursorHonoringMarketRead(full, live_available=False),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(full),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)
    factors_5m = calculate_factor_series(
        full[BarFrequency.M5],
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=_SEGMENT_START,
        latest_bar_source="canonical",
    )
    factors_15m = calculate_factor_series(
        full[BarFrequency.M15],
        timeframe=BarFrequency.M15,
        contract="JM2609",
        segment_start_trading_day=_SEGMENT_START,
        latest_bar_source="canonical",
    )
    direct = reduce_subing_lifecycle(
        symbol="jm",
        contract="JM2609",
        segment_start_trading_day=_SEGMENT_START,
        bars_5m=full[BarFrequency.M5],
        factors_5m=factors_5m,
        bars_15m=full[BarFrequency.M15],
        factors_15m=factors_15m,
        calibration=_accepted_calibration(),
        policy=load_subing_lifecycle_policy(),
    )

    assert service_snapshot.lifecycle == direct.current_snapshot
    assert service_snapshot.lifecycle.stage is LifecycleStage.SETUP_ARMED


@pytest.mark.parametrize(
    ("fault", "fault_frequency"),
    (
        ("cursor_not_progressing", BarFrequency.M5),
        ("duplicate_bar", BarFrequency.M5),
        ("missing_middle_page", BarFrequency.M5),
        ("missing_middle_page", BarFrequency.M15),
        ("missing_segment_start_prefix", BarFrequency.M5),
        ("missing_segment_start_prefix", BarFrequency.M15),
    ),
)
def test_lifecycle_pagination_fails_closed_on_invalid_page_chain(
    fault: str,
    fault_frequency: BarFrequency,
) -> None:
    """Catches malformed pagination being accepted as a complete causal segment."""
    full = _long_segment_bars()
    service = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_InvalidPaginationMarketRead(
            full,
            live_available=False,
            fault=fault,
            fault_frequency=fault_frequency,
        ),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(full),
    )

    with pytest.raises(
        MarketDataError,
        match="DOMINANT_SEGMENT_HISTORY_PAGINATION_INVALID",
    ):
        service.snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)


def test_lifecycle_pagination_fails_closed_when_segment_start_is_missing() -> None:
    """Catches a skipped page silently recreating state after the real segment start."""
    full = _long_segment_bars()
    service = SubingReadService(
        market_data=_FakeMarketData(segment_start=date(2026, 8, 1)),
        market_read=_CursorHonoringMarketRead(full, live_available=False),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(full),
    )

    with pytest.raises(
        MarketDataError,
        match="DOMINANT_SEGMENT_HISTORY_PAGINATION_INVALID",
    ):
        service.snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)


def test_daily_lifecycle_is_intraday_only_without_changing_v1_projection() -> None:
    daily = _bars(
        frequency=BarFrequency.D1,
        count=50,
        trading_day=date(2026, 6, 15),
        first_end=datetime(2026, 6, 15, 7, 0, tzinfo=UTC),
        first_close=Decimal("100"),
        trading_day_step=True,
    )
    result = SubingReadService(
        market_data=_FakeMarketData(segment_start=daily[0].trading_day),
        market_read=_HistoricalOnlyMarketRead({BarFrequency.D1: daily}),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
    ).snapshot(SubingReadRequest("jm", BarFrequency.D1), now=_NOW)

    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == daily[-1].bar_end
    assert result.primary_signal.status is SubingSignalStatus.RESEARCH_PENDING
    assert result.primary_signal.error_code == "SUBING_DAILY_RESEARCH_PENDING"
    assert result.lifecycle.availability is LifecycleAvailability.UNAVAILABLE
    assert result.lifecycle.unavailable_reason == "SUBING_LIFECYCLE_INTRADAY_ONLY"


def test_canonical_and_completed_live_prefixes_have_identical_lifecycle() -> None:
    full_5m = _bars(
        frequency=BarFrequency.M5,
        count=150,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    full_15m = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    canonical = _service_with_lifecycle(
        {BarFrequency.M5: full_5m, BarFrequency.M15: full_15m}
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)
    split = _service_with_lifecycle(
        {
            BarFrequency.M5: full_5m[:120],
            BarFrequency.M15: full_15m[:40],
        },
        live={
            BarFrequency.M15: full_15m[40:],
            BarFrequency.M5: full_5m[120:],
        },
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    assert canonical.lifecycle == split.lifecycle
    assert canonical.lifecycle.observed_at == full_5m[-1].bar_end
    assert split.source_mode == "canonical_live"


@pytest.mark.parametrize("gap_frequency", (BarFrequency.M5, BarFrequency.M15))
def test_lifecycle_rejects_gap_between_historical_and_completed_live(
    gap_frequency: BarFrequency,
) -> None:
    full = _live_seam_bars()
    history = {
        frequency: bars[:-2] if frequency is gap_frequency else bars[:-1]
        for frequency, bars in full.items()
    }
    live = {
        frequency: bars[-1:]
        for frequency, bars in full.items()
    }
    service = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(history, live=live),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(full),
    )

    with pytest.raises(
        MarketDataError,
        match="DOMINANT_SEGMENT_HISTORY_PAGINATION_INVALID",
    ):
        service.snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)


@pytest.mark.parametrize("gap_frequency", (BarFrequency.M5, BarFrequency.M15))
def test_lifecycle_rejects_late_live_prefix_when_historical_is_empty(
    gap_frequency: BarFrequency,
) -> None:
    full = _live_seam_bars()
    history = {
        frequency: (() if frequency is gap_frequency else bars[:-1])
        for frequency, bars in full.items()
    }
    live = {
        frequency: (bars[50:] if frequency is gap_frequency else bars[-1:])
        for frequency, bars in full.items()
    }
    service = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(history, live=live),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(full),
    )

    with pytest.raises(
        MarketDataError,
        match="DOMINANT_SEGMENT_HISTORY_PAGINATION_INVALID",
    ):
        service.snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)


def test_reversed_live_arrival_representation_has_identical_full_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_5m = _bars(
        frequency=BarFrequency.M5,
        count=150,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    full_15m = _bars(
        frequency=BarFrequency.M15,
        count=50,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    history = {
        BarFrequency.M5: full_5m[:120],
        BarFrequency.M15: full_15m[:40],
    }
    traces: list[object] = []

    def capture(**kwargs):
        trace = reduce_subing_lifecycle(**kwargs)
        traces.append(trace)
        return trace

    monkeypatch.setattr(
        "app.market_data.subing_read_service.evaluate_subing_lifecycle", capture
    )
    _service_with_lifecycle(
        history,
        live={
            BarFrequency.M5: full_5m[120:],
            BarFrequency.M15: full_15m[40:],
        },
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)
    _service_with_lifecycle(
        history,
        live={
            BarFrequency.M5: tuple(reversed(full_5m[120:])),
            BarFrequency.M15: tuple(reversed(full_15m[40:])),
        },
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert len(traces) == 2
    forward = traces[0]
    reverse = traces[1]
    assert forward.confirmed_pivots == reverse.confirmed_pivots
    assert forward.completed_opportunities == reverse.completed_opportunities
    assert forward.transitions == reverse.transitions
    assert forward.snapshots == reverse.snapshots
    assert forward.current_snapshot == reverse.current_snapshot
    boundary = full_15m[-1].bar_end
    boundary_snapshots = tuple(
        snapshot for snapshot in forward.snapshots if snapshot.observed_at == boundary
    )
    assert len(boundary_snapshots) == 1
    assert boundary_snapshots[0].anchor_bar_end == boundary
    assert sum(
        transition.transition_at == boundary for transition in forward.transitions
    ) <= 1


def test_intraday_factor_series_is_calculated_once_per_timeframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[BarFrequency] = []

    def calculate_once(bars, *, timeframe, **kwargs):
        calls.append(timeframe)
        return calculate_factor_series(bars, timeframe=timeframe, **kwargs)

    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        calculate_once,
    )
    bars = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=150,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=50,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }

    _service_with_lifecycle(bars).snapshot(
        SubingReadRequest("jm", BarFrequency.M15), now=_NOW
    )

    assert calls == [BarFrequency.M5, BarFrequency.M15]


def test_lifecycle_excludes_future_companion_from_the_reducer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_5m = _bars(
        frequency=BarFrequency.M5,
        count=150,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    bars_15m = _bars(
        frequency=BarFrequency.M15,
        count=51,
        trading_day=_SEGMENT_START,
        first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    observed: dict[str, object] = {}

    def capture(**kwargs):
        observed.update(kwargs)
        return reduce_subing_lifecycle(**kwargs)

    monkeypatch.setattr(
        "app.market_data.subing_read_service.evaluate_subing_lifecycle", capture
    )

    result = _service_with_lifecycle(
        {BarFrequency.M5: bars_5m, BarFrequency.M15: bars_15m}
    ).snapshot(SubingReadRequest("jm", BarFrequency.M15), now=_NOW)

    reducer_5m = observed["bars_5m"]
    reducer_15m = observed["bars_15m"]
    assert isinstance(reducer_5m, tuple)
    assert isinstance(reducer_15m, tuple)
    assert reducer_5m[-1].bar_end == bars_5m[-1].bar_end
    assert reducer_15m[-1].bar_end <= reducer_5m[-1].bar_end
    assert bars_15m[-1].bar_end > reducer_5m[-1].bar_end
    assert result.primary.snapshot is not None
    assert result.primary.snapshot.bar_end == bars_15m[-1].bar_end


def test_stale_live_identity_falls_back_to_canonical_for_v1_and_lifecycle() -> None:
    history = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=150,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=50,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }
    live = {
        BarFrequency.M5: (
            _bar(history[BarFrequency.M5][-1].bar_end + timedelta(minutes=5), _SEGMENT_START, Decimal("999")),
        ),
        BarFrequency.M15: (),
    }
    canonical = _service_with_lifecycle(history).snapshot(
        SubingReadRequest("jm", BarFrequency.M5), now=_NOW
    )
    stale = SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(
            history,
            live=live,
            state_trading_day=date(2026, 8, 2),
        ),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(history),
    ).snapshot(SubingReadRequest("jm", BarFrequency.M5), now=_NOW)

    assert stale.primary == canonical.primary
    assert stale.lifecycle == canonical.lifecycle
    assert stale.source_mode == "canonical"
    assert stale.live_reason == "live_unavailable"


def test_missing_lifecycle_policy_does_not_degrade_existing_v1_fields() -> None:
    bars = {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=150,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=50,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }
    ready = _service_with_lifecycle(bars).snapshot(
        SubingReadRequest("jm", BarFrequency.M5), now=_NOW
    )
    unavailable = _service_with_calibration(bars).snapshot(
        SubingReadRequest("jm", BarFrequency.M5), now=_NOW
    )

    assert _v1_projection(unavailable) == _v1_projection(ready)
    assert unavailable.lifecycle.availability is LifecycleAvailability.UNAVAILABLE
    assert unavailable.lifecycle.unavailable_reason == "SUBING_LIFECYCLE_POLICY_INVALID"


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
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(timeframe, boundary, cross=MacdCross.NONE),
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
    ("frequency", "direction", "reciprocal_cross"),
    [
        (BarFrequency.M5, SubingDirection.LONG, MacdCross.GOLDEN),
        (BarFrequency.M15, SubingDirection.SHORT, MacdCross.DEAD),
    ],
)
def test_same_boundary_reciprocal_only_match_is_resolved_without_overwriting_primary(
    monkeypatch: pytest.MonkeyPatch,
    frequency: BarFrequency,
    direction: SubingDirection,
    reciprocal_cross: MacdCross,
) -> None:
    """Catches a requested non-match suppressing a complete companion opportunity."""
    boundary = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    companion_frequency = (
        BarFrequency.M15 if frequency is BarFrequency.M5 else BarFrequency.M5
    )
    monkeypatch.setattr(
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(
                timeframe,
                boundary,
                cross=(
                    MacdCross.NONE if timeframe is frequency else reciprocal_cross
                ),
                direction=direction,
            ),
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
    assert result.resolved_signal is not None
    assert result.resolved_signal.status is SubingSignalStatus.MATCHED
    assert result.resolved_signal.direction is direction
    assert result.resolved_signal.trigger_timeframe is companion_frequency
    assert result.resolved_signal.lower_tf_confirmation is False
    assert result.resolved_signal.resolution is None


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
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(
                timeframe,
                boundary,
                cross=cross,
                direction=direction,
            ),
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
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(
                timeframe,
                boundary,
                cross=(
                    MacdCross.GOLDEN if timeframe is frequency else MacdCross.NONE
                ),
            ),
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
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(timeframe, boundary, cross=MacdCross.GOLDEN),
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
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(timeframe, boundary, cross=MacdCross.GOLDEN),
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
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(timeframe, boundary, cross=MacdCross.GOLDEN),
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
        "app.market_data.subing_read_service.calculate_subing_factor_series",
        lambda bars, *, timeframe, **_kwargs: _repeat_factor(
            bars,
            _signal_factor(timeframe, boundary, cross=MacdCross.GOLDEN),
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


def test_composition_injects_tracked_calibration_and_lifecycle_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _accepted_calibration()
    observed: dict[str, object] = {}

    monkeypatch.setattr(composition, "build_market_data_service", lambda _session: "md")
    monkeypatch.setattr(composition, "build_market_read_service", lambda _session: "mr")

    expected_policy = load_subing_lifecycle_policy()

    def load_calibration(path):
        observed["calibration_path"] = path
        return expected

    def load_lifecycle(path):
        observed["lifecycle_path"] = path
        return expected_policy

    class CapturingService:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

    monkeypatch.setattr(
        composition, "load_accepted_subing_calibration", load_calibration
    )
    monkeypatch.setattr(composition, "load_subing_lifecycle_policy", load_lifecycle)
    monkeypatch.setattr(composition, "SubingReadService", CapturingService)

    session = object()
    monkeypatch.setattr(
        "app.market_data.coverage_source.DatabaseCoverageSource",
        lambda received, *_args, **_kwargs: (
            "coverage" if received is session else "wrong-coverage-session"
        ),
    )

    composition.build_subing_read_service(session)

    assert observed == {
        "calibration_path": PROJECT_ROOT
        / "data/research_policies/subing_calibration_intraday_v1.json",
        "lifecycle_path": PROJECT_ROOT
        / "data/research_policies/subing_lifecycle_v2_research_v1.json",
        "market_data": "md",
        "market_read": "mr",
        "calibration": expected,
        "lifecycle_policy": expected_policy,
        "lifecycle_coverage": "coverage",
    }


def test_composition_propagates_malformed_calibration_without_defaulting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "load_accepted_subing_calibration",
        lambda _path: (_ for _ in ()).throw(SubingCalibrationError()),
    )

    with pytest.raises(SubingCalibrationError, match="SUBING_CALIBRATION_INVALID"):
        composition.build_subing_read_service(object())


def test_composition_degrades_only_lifecycle_when_lifecycle_policy_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr(composition, "build_market_data_service", lambda _session: "md")
    monkeypatch.setattr(composition, "build_market_read_service", lambda _session: "mr")
    monkeypatch.setattr(
        composition,
        "load_accepted_subing_calibration",
        lambda _path: _accepted_calibration(),
    )
    monkeypatch.setattr(
        composition,
        "load_subing_lifecycle_policy",
        lambda _path: (_ for _ in ()).throw(SubingLifecyclePolicyError()),
    )
    monkeypatch.setattr(
        "app.market_data.coverage_source.DatabaseCoverageSource",
        lambda *_args, **_kwargs: "coverage",
    )

    class CapturingService:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

    monkeypatch.setattr(composition, "SubingReadService", CapturingService)

    composition.build_subing_read_service(object())

    assert observed["calibration"] == _accepted_calibration()
    assert observed["lifecycle_policy"] is None
    assert observed["lifecycle_coverage"] == "coverage"


def test_composition_degrades_only_lifecycle_when_policy_is_not_utf8(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(b"\xff\xfe\x00")
    observed: dict[str, object] = {}
    monkeypatch.setattr(composition, "_SUBING_LIFECYCLE_POLICY", policy_path)
    monkeypatch.setattr(composition, "build_market_data_service", lambda _session: "md")
    monkeypatch.setattr(composition, "build_market_read_service", lambda _session: "mr")
    monkeypatch.setattr(
        composition,
        "load_accepted_subing_calibration",
        lambda _path: _accepted_calibration(),
    )
    monkeypatch.setattr(
        "app.market_data.coverage_source.DatabaseCoverageSource",
        lambda *_args, **_kwargs: "coverage",
    )

    class CapturingService:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

    monkeypatch.setattr(composition, "SubingReadService", CapturingService)

    composition.build_subing_read_service(object())

    assert observed["calibration"] == _accepted_calibration()
    assert observed["lifecycle_policy"] is None
    assert observed["lifecycle_coverage"] == "coverage"


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
        state_trading_day: date = _SEGMENT_START,
    ) -> None:
        self.history = history
        self.live = live or {}
        self.live_contract = live_contract
        self.live_available = live_available
        self.state_trading_day = state_trading_day

    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        assert request.series_kind is SeriesKind.CONTRACT
        assert request.symbol == "jm"
        assert request.contract == "JM2609"
        assert request.limit == 300
        bars = self.history[request.frequency]
        return MarketSeriesPageResult(
            request_identity=_page_identity(request),
            bars=bars,
            canonical_coverage=(
                (bars[0].bar_end, bars[-1].bar_end) if bars else None
            ),
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
            trading_day=self.state_trading_day,
            live_eligible=True,
            live_available=self.live_available,
            live_contract=self.live_contract,
            canonical_end=(
                self.history[identity.frequency][-1].bar_end
                if self.history[identity.frequency]
                else None
            ),
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


class _RealHistoryMarketRead(_FakeMarketRead):
    def __init__(self, history, market_data: MarketDataService, **kwargs) -> None:
        super().__init__(history, **kwargs)
        self.market_data = market_data

    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        return self.market_data.query_page(request)


class _CursorHonoringMarketRead(_FakeMarketRead):
    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        assert request.series_kind is SeriesKind.CONTRACT
        assert request.symbol == "jm"
        assert request.contract == "JM2609"
        assert request.limit == 300
        eligible = tuple(
            bar
            for bar in self.history[request.frequency]
            if request.before is None or bar.bar_end < request.before
        )
        has_more_before = len(eligible) > request.limit
        bars = eligible[-request.limit :]
        return MarketSeriesPageResult(
            request_identity=_page_identity(request),
            bars=bars,
            canonical_coverage=(
                (bars[0].bar_end, bars[-1].bar_end) if bars else None
            ),
            has_more_before=has_more_before,
            next_before=bars[0].bar_end if has_more_before else None,
            resolved_contract_segments=(),
        )


class _StaleCanonicalEndMarketRead(_CursorHonoringMarketRead):
    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        state = super().state(identity, now)
        return replace(state, canonical_end=now - timedelta(minutes=1))


class _FakeLifecycleCoverage:
    def __init__(
        self,
        history: dict[BarFrequency, tuple[CanonicalBar, ...]],
    ) -> None:
        self.history = history

    def expected_bar_ends(
        self,
        key,
        year: int,
        month: int,
        start: date,
        end: date,
    ) -> tuple[datetime, ...]:
        return tuple(
            bar.bar_end
            for bar in self.history[key.frequency]
            if start <= bar.trading_day <= end
            and bar.trading_day.year == year
            and bar.trading_day.month == month
        )


class _InvalidPaginationMarketRead(_CursorHonoringMarketRead):
    def __init__(
        self,
        *args,
        fault: str,
        fault_frequency: BarFrequency,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fault = fault
        self.fault_frequency = fault_frequency
        self.calls: dict[BarFrequency, int] = {}
        self.first_page_oldest: dict[BarFrequency, CanonicalBar] = {}

    def history_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult:
        page = super().history_page(request)
        if request.frequency is not self.fault_frequency:
            return page
        call = self.calls.get(request.frequency, 0) + 1
        self.calls[request.frequency] = call
        if call == 1 and page.bars:
            self.first_page_oldest[request.frequency] = page.bars[0]
        if self.fault == "cursor_not_progressing" and call == 1:
            return replace(
                page,
                next_before=(request.before or page.bars[-1].bar_end),
            )
        if self.fault == "duplicate_bar" and call == 2:
            duplicate = self.first_page_oldest[request.frequency]
            bars = (*page.bars[1:], duplicate)
            return replace(
                page,
                bars=bars,
                canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
                next_before=(bars[0].bar_end if page.has_more_before else None),
            )
        if self.fault == "missing_middle_page" and call == 2:
            bars = self.history[request.frequency][:100]
            return replace(
                page,
                bars=bars,
                canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
                has_more_before=False,
                next_before=None,
            )
        if self.fault == "missing_segment_start_prefix" and call == 3:
            width = 5 if request.frequency is BarFrequency.M5 else 15
            omitted = self.history[request.frequency][:50]
            before_segment = tuple(
                replace(
                    bar,
                    bar_end=bar.bar_end - timedelta(minutes=width * 50),
                    trading_day=_SEGMENT_START - timedelta(days=1),
                )
                for bar in omitted
            )
            retained = self.history[request.frequency][50:100]
            bars = (*before_segment, *retained)
            return replace(
                page,
                bars=bars,
                canonical_coverage=(bars[0].bar_end, bars[-1].bar_end),
                has_more_before=False,
                next_before=None,
            )
        return page


class _StateIdentityOverrideMarketRead(_FakeMarketRead):
    def __init__(self, *args, field: str, value: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.field = field
        self.value = value

    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState:
        state = super().state(identity, now)
        return replace(state, **{self.field: self.value})


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


def _service_with_lifecycle(
    history: dict[BarFrequency, tuple[CanonicalBar, ...]],
    *,
    live: dict[BarFrequency, tuple[CanonicalBar, ...]] | None = None,
) -> SubingReadService:
    coverage = {
        frequency: tuple(
            sorted(
                {
                    bar.bar_end: bar
                    for bar in (
                        *history.get(frequency, ()),
                        *(live or {}).get(frequency, ()),
                    )
                }.values(),
                key=lambda bar: bar.bar_end,
            )
        )
        for frequency in (BarFrequency.M5, BarFrequency.M15)
    }
    return SubingReadService(
        market_data=_FakeMarketData(),
        market_read=_FakeMarketRead(
            history,
            live=live,
            live_available=live is not None,
        ),
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        lifecycle_coverage=_FakeLifecycleCoverage(coverage),
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


def _repeat_factor(
    bars: tuple[CanonicalBar, ...],
    factor: SubingFactorResult,
) -> tuple[SubingFactorResult, ...]:
    return tuple(factor for _bar_value in bars)


def _v1_projection(snapshot: SubingReadSnapshot) -> tuple[object, ...]:
    return (
        snapshot.symbol,
        snapshot.product_name,
        snapshot.frequency,
        snapshot.actual_contract,
        snapshot.dominant_mapping_date,
        snapshot.segment_start_trading_day,
        snapshot.source_mode,
        snapshot.live_observation,
        snapshot.live_reason,
        snapshot.macd_policy_id,
        snapshot.signal_macd_policy_id,
        snapshot.calibration_state,
        snapshot.calibration_id,
        snapshot.primary,
        snapshot.companion,
        snapshot.primary_signal,
        snapshot.resolved_signal,
    )


def _page_identity(request: SeriesPageQuery) -> dict[str, object]:
    return {
        "series_kind": request.series_kind.value,
        "symbol": request.symbol,
        "contract": request.contract,
        "frequency": request.frequency.value,
        "before": request.before.isoformat() if request.before else None,
        "limit": request.limit,
    }


def _long_segment_bars() -> dict[BarFrequency, tuple[CanonicalBar, ...]]:
    return {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=700,
            trading_day=_SEGMENT_START,
            first_end=_NOW - timedelta(minutes=5 * 699),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=700,
            trading_day=_SEGMENT_START,
            first_end=_NOW - timedelta(minutes=15 * 699),
            first_close=Decimal("100"),
        ),
    }


def _live_seam_bars() -> dict[BarFrequency, tuple[CanonicalBar, ...]]:
    return {
        BarFrequency.M5: _bars(
            frequency=BarFrequency.M5,
            count=152,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 5, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
        BarFrequency.M15: _bars(
            frequency=BarFrequency.M15,
            count=52,
            trading_day=_SEGMENT_START,
            first_end=datetime(2026, 8, 3, 0, 15, tzinfo=UTC),
            first_close=Decimal("100"),
        ),
    }


def _companion_frequency(frequency: BarFrequency) -> BarFrequency:
    return BarFrequency.M15 if frequency is BarFrequency.M5 else BarFrequency.M5


def _first_end(frequency: BarFrequency) -> datetime:
    minute = 5 if frequency is BarFrequency.M5 else 15
    return datetime(2026, 8, 3, 0, minute, tzinfo=UTC)


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
