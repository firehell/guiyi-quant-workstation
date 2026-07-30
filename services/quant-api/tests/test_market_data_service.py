from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MarketDataFile
from app.schemas.market import (
    LiveMarketBarsQuality,
    LiveMarketBarsRequest,
    LiveMarketBarsResponse,
    MarketBarsCoverage,
)
from app.services.active_dataset import ActiveDatasetDomainError, DatasetRequest
from app.services.active_dataset_resolver import ActiveDatasetResolver
from app.services.market_data_service import MarketDataService
from app.services.market_workbench import (
    MarketAccessError,
    get_market_bars,
    resolve_market_read_context,
)


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_bars(path, *, provider: str, closes: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, close in enumerate(closes):
        bar_time = datetime(2026, 7, 30, 9, index * 15)
        rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": bar_time,
                "trading_day": bar_time.date(),
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000 + index,
                "turnover": close * 100,
                "period": "15m",
                "provider": provider,
                "data_version": f"{provider}-v1",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _market_file(path, *, provider: str, data_version: str) -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="15m",
        start_time=datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 7, 30, 9, 30, tzinfo=UTC),
        file_path=str(path),
        row_count=3,
        data_version=data_version,
        data_role="primary",
        quality_status="passed",
    )


def _live_15m_response(
    *,
    source_modes: tuple[str | None, str | None] = (
        "live_1m_sequential_bucket",
        "live_1m_sequential_bucket",
    ),
) -> LiveMarketBarsResponse:
    later_bar = {
        "live_bar_id": 22,
        "time": "2026-07-30T09:15:00",
        "datetime": datetime(2026, 7, 30, 9, 15),
        "trading_day": date(2026, 7, 30),
        "symbol": "jm",
        "contract": "JM2609",
        "exchange": "DCE",
        "open": 1102.0,
        "high": 1104.0,
        "low": 1101.0,
        "close": 1103.0,
        "volume": 14.0,
        "openInterest": 1002.0,
        "turnover": None,
        "period": "15m",
        "provider": "rqdata",
        "data_version": None,
        "bar_status": "confirmed",
        "quality_status": "warning",
        "source_mode": source_modes[1],
        "revision": 2,
        "confirmed_at": "2026-07-30T09:15:01",
        "quality_reasons": ["partial_bucket"],
        "source_bar_count": 14,
        "expected_bar_count": 15,
        "source_start_datetime": "2026-07-30T09:01:00",
        "source_end_datetime": "2026-07-30T09:15:00",
    }
    earlier_bar = {
        "live_bar_id": 11,
        "time": "2026-07-30T09:00:00",
        "datetime": datetime(2026, 7, 30, 9, 0),
        "trading_day": date(2026, 7, 30),
        "symbol": "jm",
        "contract": "JM2609",
        "exchange": "DCE",
        "open": 1100.0,
        "high": 1102.0,
        "low": 1099.0,
        "close": 1101.0,
        "volume": 15.0,
        "openInterest": 1001.0,
        "turnover": 16515.0,
        "period": "15m",
        "provider": "rqdata",
        "data_version": None,
        "bar_status": "confirmed",
        "quality_status": "passed",
        "source_mode": source_modes[0],
        "revision": 1,
        "confirmed_at": "2026-07-30T09:00:01",
        "quality_reasons": [],
        "source_bar_count": 15,
        "expected_bar_count": 15,
        "source_start_datetime": "2026-07-30T08:46:00",
        "source_end_datetime": "2026-07-30T09:00:00",
    }
    return LiveMarketBarsResponse(
        bars=[later_bar, earlier_bar],
        quality=LiveMarketBarsQuality(
            status="warning",
            row_count=2,
            chart_row_count=2,
            passed_count=1,
            warning_count=1,
            failed_count=0,
            rejected_count=0,
            partial_count=1,
        ),
        coverage=MarketBarsCoverage(
            symbol="jm",
            contract="JM2609",
            period="15m",
            provider="rqdata",
            data_type="live_db",
            source_mode="live_1m_sequential_bucket",
            start_time=datetime(2026, 7, 30, 9, 0),
            end_time=datetime(2026, 7, 30, 9, 15),
            latest_bar_time=datetime(2026, 7, 30, 9, 15),
            row_count=2,
            quality_status="warning",
        ),
        request=LiveMarketBarsRequest(
            symbol="jm",
            contract="JM2609",
            period="15m",
            start=datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
            end=datetime(2026, 7, 30, 9, 30, tzinfo=UTC),
            provider="rqdata",
            source_mode="live_1m_sequential_bucket",
            limit=20,
        ),
        message="legacy-live-warning",
    )


def test_workbench_frozen_context_does_not_reselect_and_preserves_legacy_response(tmp_path) -> None:
    """A newly active rqdata asset cannot enter bars, quality, coverage, or lineage."""
    SessionLocal = _session_factory()
    frozen_path = tmp_path / "parquet" / "canonical" / "bars" / "frozen-local.parquet"
    later_path = tmp_path / "parquet" / "canonical" / "bars" / "later-rqdata.parquet"
    _write_bars(frozen_path, provider="local_parquet", closes=[1101, 1102, 1103])
    _write_bars(later_path, provider="rqdata", closes=[9901, 9902, 9903])

    with SessionLocal() as session:
        frozen_file = _market_file(
            frozen_path,
            provider="local_parquet",
            data_version="frozen-local-v1",
        )
        session.add(frozen_file)
        session.commit()
        frozen_file_id = frozen_file.id
        context = resolve_market_read_context(
            session,
            symbol="jm",
            contract="JM2609",
            period="15m",
            provider=None,
            data_role=None,
            profile_id=None,
            access_mode="browser",
        )

        session.add(
            _market_file(
                later_path,
                provider="rqdata",
                data_version="later-rqdata-v1",
            )
        )
        session.commit()

        response = get_market_bars(
            session,
            symbol="jm",
            contract="JM2609",
            period="15m",
            start=None,
            end=None,
            provider=None,
            data_role=None,
            limit=10,
            tail=False,
            access_mode="browser",
            resolved_context=context,
            frozen_market_data_file_ids=context.lineage.market_data_file_ids,
            frozen_asset_evidence=context.lineage.asset_evidence,
        )

    assert [bar["close"] for bar in response.bars] == [1101.0, 1102.0, 1103.0]
    assert response.lineage.market_data_file_ids == [frozen_file_id]
    assert response.lineage.asset_evidence == context.lineage.asset_evidence
    assert response.quality.status == "passed"
    assert response.coverage is not None
    assert response.coverage.provider == "local_parquet"
    assert response.coverage.row_count == 3
    assert response.request.start == datetime(2026, 7, 30, 9, 0)
    assert response.request.end == datetime(2026, 7, 30, 9, 30)


def test_workbench_frozen_context_rejects_file_set_drift_with_legacy_code(tmp_path) -> None:
    """A frozen ID/evidence mismatch must use the existing lineage-changed contract."""
    SessionLocal = _session_factory()
    path = tmp_path / "parquet" / "canonical" / "bars" / "frozen.parquet"
    _write_bars(path, provider="rqdata", closes=[1101, 1102, 1103])

    with SessionLocal() as session:
        session.add(
            _market_file(
                path,
                provider="rqdata",
                data_version="frozen-rqdata-v1",
            )
        )
        session.commit()
        context = resolve_market_read_context(
            session,
            symbol="jm",
            contract="JM2609",
            period="15m",
            provider=None,
            data_role=None,
            profile_id=None,
            access_mode="browser",
        )

        with pytest.raises(MarketAccessError) as raised:
            get_market_bars(
                session,
                symbol="jm",
                contract="JM2609",
                period="15m",
                start=None,
                end=None,
                provider=None,
                data_role=None,
                limit=10,
                tail=False,
                access_mode="browser",
                resolved_context=context,
                frozen_market_data_file_ids=[999],
                frozen_asset_evidence=context.lineage.asset_evidence,
            )

    assert raised.value.code == "MARKET_LINEAGE_CHANGED"
    assert raised.value.status_code == 409


def test_historical_service_resolves_once_and_adapter_matches_complete_legacy_response(
    tmp_path,
) -> None:
    """The Facade must freeze once and reconstruct the legacy response exactly."""
    SessionLocal = _session_factory()
    path = tmp_path / "parquet" / "canonical" / "bars" / "jm-15m.parquet"
    _write_bars(path, provider="rqdata", closes=[1101, 1102, 1103])

    with SessionLocal() as session:
        session.add(
            _market_file(
                path,
                provider="rqdata",
                data_version="frozen-rqdata-v1",
            )
        )
        session.commit()
        first_response = get_market_bars(
            session,
            symbol="jm",
            contract="JM2609",
            period="15m",
            start=None,
            end=None,
            provider=None,
            data_role=None,
            limit=2,
            quote_mode=True,
            allow_continuous=False,
            tail=False,
            access_mode="browser",
        )
        expected_file_id = first_response.lineage.market_data_file_id
        expected_token = first_response.lineage.lineage_token
        oracle = get_market_bars(
            session,
            symbol="jm",
            contract="JM2609",
            period="15m",
            start=None,
            end=None,
            provider=None,
            data_role=None,
            limit=2,
            quote_mode=True,
            allow_continuous=False,
            tail=False,
            access_mode="browser",
            expected_market_data_file_id=expected_file_id,
            expected_lineage_token=expected_token,
        )

        class CountingResolver:
            def __init__(self) -> None:
                self.calls = 0
                self.delegate = ActiveDatasetResolver(session)

            def resolve_historical(self, request: DatasetRequest):
                self.calls += 1
                return self.delegate.resolve_historical(request)

        resolver = CountingResolver()
        service = MarketDataService(session, resolver=resolver)
        result = service.get_bars(
            DatasetRequest(
                data_context="historical",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="15m",
                access_mode="browser",
                expected_market_data_file_id=expected_file_id,
                expected_lineage_token=expected_token,
                quote_mode=True,
                allow_continuous=False,
            ),
            start=None,
            end=None,
            limit=2,
            tail=False,
        )
        adapted = service.to_market_bars_response(result)

    assert resolver.calls == 1
    assert adapted.model_dump(mode="json") == oracle.model_dump(mode="json")
    assert result.response_bar_count == 2
    assert result.descriptor.source_max_bar == datetime(2026, 7, 30, 9, 15)
    assert result.descriptor.source_revision_hash is not None
    assert result.descriptor.lineage_token == expected_token
    assert result.response_request["expected_market_data_file_id"] == expected_file_id
    assert result.response_request["expected_lineage_token"] == expected_token


@pytest.mark.parametrize("drift_field", ["market_data_file_ids", "asset_evidence", "lineage_token"])
def test_historical_service_rejects_post_read_lineage_drift_without_retry(
    tmp_path,
    drift_field: str,
) -> None:
    """Every frozen lineage component must be checked after the legacy read."""
    SessionLocal = _session_factory()
    path = tmp_path / "parquet" / "canonical" / "bars" / "jm-15m.parquet"
    _write_bars(path, provider="rqdata", closes=[1101, 1102, 1103])

    with SessionLocal() as session:
        session.add(
            _market_file(
                path,
                provider="rqdata",
                data_version="frozen-rqdata-v1",
            )
        )
        session.commit()
        oracle = get_market_bars(
            session,
            symbol="jm",
            contract="JM2609",
            period="15m",
            start=None,
            end=None,
            provider=None,
            data_role=None,
            limit=3,
            tail=False,
            access_mode="browser",
        )
        lineage = oracle.lineage.model_copy(deep=True)
        if drift_field == "market_data_file_ids":
            lineage.market_data_file_ids = [999]
        elif drift_field == "asset_evidence":
            lineage.asset_evidence[0]["checksum"] = "drifted"
        else:
            lineage.lineage_token = "drifted"
        drifted_response = oracle.model_copy(update={"lineage": lineage})
        loader_calls = 0

        def load_drifted_response(*_args, **_kwargs):
            nonlocal loader_calls
            loader_calls += 1
            return drifted_response

        service = MarketDataService(
            session,
            historical_bars_loader=load_drifted_response,
        )
        with pytest.raises(MarketAccessError) as raised:
            service.get_bars(
                DatasetRequest(
                    data_context="historical",
                    symbol="jm",
                    contract_selector="explicit",
                    contract="JM2609",
                    period="15m",
                    access_mode="browser",
                ),
                start=None,
                end=None,
                limit=3,
                tail=False,
            )

    assert loader_calls == 1
    assert raised.value.code == "MARKET_LINEAGE_CHANGED"
    assert raised.value.status_code == 409


class _FakeLiveReader:
    def __init__(self, response: LiveMarketBarsResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get_bars(self, **kwargs) -> LiveMarketBarsResponse:
        self.calls.append(kwargs)
        return self.response


def test_live_service_reads_once_and_hashes_the_complete_legacy_response_snapshot() -> None:
    """The hash covers the full JSON bar payload while the result preserves reader order."""
    response = _live_15m_response()
    reader = _FakeLiveReader(response)
    service = MarketDataService(object(), live_reader=reader)
    start = datetime(2026, 7, 30, 9, 0, tzinfo=UTC)
    end = datetime(2026, 7, 30, 9, 30, tzinfo=UTC)

    result = service.get_bars(
        DatasetRequest(
            data_context="live",
            symbol="jm",
            contract_selector="explicit",
            contract="JM2609",
            period="15m",
            access_mode="browser",
            provider="rqdata",
            live_source_mode="live_1m_sequential_bucket",
        ),
        start=start,
        end=end,
        limit=20,
        tail=False,
    )

    assert reader.calls == [
        {
            "symbol": "jm",
            "contract": "JM2609",
            "period": "15m",
            "start": start,
            "end": end,
            "provider": "rqdata",
            "source_mode": "live_1m_sequential_bucket",
            "limit": 20,
        }
    ]
    assert result.bars == tuple(response.bars)
    assert [bar["live_bar_id"] for bar in result.bars] == [22, 11]
    assert result.quality == response.quality.model_dump(mode="python")
    assert result.coverage == response.coverage.model_dump(mode="python")
    assert result.response_request == response.request.model_dump(mode="python")
    assert result.message == "legacy-live-warning"
    assert result.response_bar_count == 2
    assert result.descriptor.assets == ()
    assert result.descriptor.strict_research_ready is False
    assert result.descriptor.quality_status == "warning"
    assert result.descriptor.source_coverage_row_count == 2
    assert result.descriptor.source_max_bar == datetime(2026, 7, 30, 9, 15)
    assert result.descriptor.source_revision_hash == (
        "live-response-revision-v1:"
        "c44db0e2b15bc3b9ff397746c06af1684c26eab1b850eee14b4dc5ebd762ca56"
    )
    assert result.descriptor.lineage_kind == "live_response_snapshot"
    assert result.descriptor.lineage_token == (
        "live-response-snapshot-v1:"
        "6bdc788a706cedb834dbd5fdb253e1e6873877c328d688f5ceffef1f83858b9b"
    )
    assert result.descriptor.warnings == ("live_source_identity_unverified",)


@pytest.mark.parametrize(
    ("field", "drifted_value"),
    [
        ("start", datetime(2026, 7, 30, 8, 45, tzinfo=UTC)),
        ("end", datetime(2026, 7, 30, 9, 45, tzinfo=UTC)),
        ("limit", 21),
    ],
)
def test_live_service_rejects_drifted_response_request_window_without_retry(
    field: str,
    drifted_value: datetime | int,
) -> None:
    response = _live_15m_response()
    response = response.model_copy(
        update={
            "request": response.request.model_copy(
                update={field: drifted_value},
            )
        }
    )
    reader = _FakeLiveReader(response)
    service = MarketDataService(object(), live_reader=reader)
    start = datetime(2026, 7, 30, 9, 0, tzinfo=UTC)
    end = datetime(2026, 7, 30, 9, 30, tzinfo=UTC)

    with pytest.raises(ActiveDatasetDomainError) as raised:
        service.get_bars(
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="15m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode="live_1m_sequential_bucket",
            ),
            start=start,
            end=end,
            limit=20,
            tail=False,
        )

    assert raised.value.code == "DATASET_LINEAGE_CHANGED"
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    ("field", "drifted_value"),
    [
        ("symbol", "j"),
        ("contract", "JM2610"),
        ("period", "1m"),
    ],
)
def test_live_service_rejects_drifted_response_coverage_identity_without_retry(
    field: str,
    drifted_value: str,
) -> None:
    response = _live_15m_response()
    assert response.coverage is not None
    response = response.model_copy(
        update={
            "coverage": response.coverage.model_copy(
                update={field: drifted_value},
            )
        }
    )
    reader = _FakeLiveReader(response)
    service = MarketDataService(object(), live_reader=reader)

    with pytest.raises(ActiveDatasetDomainError) as raised:
        service.get_bars(
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="15m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode="live_1m_sequential_bucket",
            ),
            start=response.request.start,
            end=response.request.end,
            limit=response.request.limit,
            tail=False,
        )

    assert raised.value.code == "DATASET_LINEAGE_CHANGED"
    assert len(reader.calls) == 1


def test_live_service_supports_the_exact_1m_mode_and_retains_null_aggregate_fields() -> None:
    response = _live_15m_response()
    bar = dict(response.bars[1])
    bar.update(
        {
            "period": "1m",
            "source_mode": "poll_get_price_1m",
        }
    )
    for field in (
        "source_bar_count",
        "expected_bar_count",
        "source_start_datetime",
        "source_end_datetime",
    ):
        bar.pop(field)
    response = LiveMarketBarsResponse(
        bars=[bar],
        quality=response.quality.model_copy(
            update={
                "row_count": 1,
                "chart_row_count": 1,
                "passed_count": 1,
                "warning_count": 0,
                "partial_count": 0,
                "status": "passed",
            }
        ),
        coverage=response.coverage.model_copy(
            update={
                "period": "1m",
                "source_mode": "poll_get_price_1m",
                "row_count": 1,
                "quality_status": "passed",
            }
        ),
        request=response.request.model_copy(
            update={
                "period": "1m",
                "source_mode": "poll_get_price_1m",
                "limit": 1,
            }
        ),
        message=None,
    )
    reader = _FakeLiveReader(response)
    service = MarketDataService(object(), live_reader=reader)

    result = service.get_bars(
        DatasetRequest(
            data_context="live",
            symbol="jm",
            contract_selector="explicit",
            contract="JM2609",
            period="1m",
            access_mode="browser",
            provider="rqdata",
            live_source_mode="poll_get_price_1m",
        ),
        start=response.request.start,
        end=response.request.end,
        limit=1,
        tail=False,
    )

    assert len(reader.calls) == 1
    assert result.bars == (bar,)
    assert result.descriptor.live_source_mode == "poll_get_price_1m"
    assert result.descriptor.source_revision_hash is not None
    assert result.descriptor.source_revision_hash.startswith(
        "live-response-revision-v1:"
    )


@pytest.mark.parametrize(
    "source_modes",
    [
        (None, "live_1m_sequential_bucket"),
        ("wrong_mode", "wrong_mode"),
        ("live_1m_sequential_bucket", "wrong_mode"),
    ],
)
def test_live_service_rejects_missing_wrong_or_mixed_returned_modes_without_fallback(
    source_modes: tuple[str | None, str | None],
) -> None:
    reader = _FakeLiveReader(_live_15m_response(source_modes=source_modes))
    service = MarketDataService(object(), live_reader=reader)

    with pytest.raises(ActiveDatasetDomainError) as raised:
        service.get_bars(
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="15m",
                access_mode="browser",
                provider="rqdata",
                live_source_mode="live_1m_sequential_bucket",
            ),
            start=None,
            end=None,
            limit=20,
            tail=False,
        )

    assert raised.value.code == "LIVE_SOURCE_MODE_MISMATCH"
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    ("access_mode", "source_mode", "tail", "expected_code"),
    [
        (
            "research",
            "live_1m_sequential_bucket",
            False,
            "LIVE_SOURCE_MODE_IDENTITY_UNSUPPORTED",
        ),
        ("browser", None, False, "LIVE_SOURCE_MODE_REQUIRED"),
        (
            "browser",
            "poll_get_price_1m",
            False,
            "LIVE_SOURCE_MODE_MISMATCH",
        ),
        (
            "browser",
            "live_1m_sequential_bucket",
            True,
            "DATASET_REQUEST_UNSUPPORTED",
        ),
    ],
)
def test_live_service_rejects_unsupported_requests_before_reading(
    access_mode: str,
    source_mode: str | None,
    tail: bool,
    expected_code: str,
) -> None:
    reader = _FakeLiveReader(_live_15m_response())
    service = MarketDataService(object(), live_reader=reader)

    with pytest.raises(ActiveDatasetDomainError) as raised:
        service.get_bars(
            DatasetRequest(
                data_context="live",
                symbol="jm",
                contract_selector="explicit",
                contract="JM2609",
                period="15m",
                access_mode=access_mode,  # type: ignore[arg-type]
                provider="rqdata",
                live_source_mode=source_mode,
            ),
            start=None,
            end=None,
            limit=20,
            tail=tail,
        )

    assert raised.value.code == expected_code
    assert reader.calls == []
