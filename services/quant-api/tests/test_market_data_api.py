from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, Exchange, FuturesTradingParameter, Instrument, LiveMinuteBar, MainContractMap, MarketDataFile
from app.schemas.market import (
    MarketBarsCoverage,
    MarketBarsQuality,
    MarketBarsRequest,
    MarketBarsResponse,
    MarketReadLineage,
)
from app.services.active_dataset import ActiveDatasetDomainError
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def _expected_empty_legacy_bars_payload(
    *,
    contract: str,
    period: str,
) -> dict[str, object]:
    return {
        "bars": [],
        "quality": {
            "status": "unchecked",
            "missing_bars": 0,
            "duplicated_bars": 0,
            "abnormal_price_count": 0,
            "abnormal_volume_count": 0,
            "report_count": 0,
            "warning_reasons": [],
            "cross_file_conflicts": 0,
            "conflict_details": None,
        },
        "coverage": None,
        "request": {
            "symbol": "jm",
            "contract": contract,
            "period": period,
            "start": None,
            "end": None,
            "provider": None,
            "data_role": None,
            "profile_id": None,
            "access_mode": "browser",
            "expected_market_data_file_id": None,
            "expected_lineage_token": None,
            "limit": 10,
            "tail": True,
        },
        "lineage": {
            "access_mode": "browser",
            "strict_research_ready": False,
            "profile_id": None,
            "quality_policy": None,
            "market_data_file_id": None,
            "market_data_file_ids": [],
            "data_version": None,
            "data_versions": [],
            "provider": None,
            "data_role": None,
            "quality_status": "unchecked",
            "source_interval": None,
            "source_intervals": [],
            "source_interval_basis": None,
            "binding_snapshot": None,
            "lineage_token": "a37615c815978cef231ceea27628df784e9a379b939e624fb9b6f716cb011d24",
            "source_mode": "historical",
            "view_role": "actual_contract",
            "continuous_contract": "jm.MAIN",
            "actual_contract": contract,
            "asset_evidence": [],
        },
        "strict_research_ready": False,
        "message": "当前选择没有可展示的 K 线",
    }


def test_klines_api_returns_canonical_bars(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        _write_api_bar_file(
            path,
            provider="rqdata",
            symbol="rb",
            contract="rb.MAIN",
            exchange="SHFE",
            period="5m",
            closes=[4010.0, 4020.0],
            start=datetime(2021, 1, 4, 9, 5),
        )
        market_file = _market_file(
            path,
            provider="rqdata",
            data_role="primary",
            quality_status="passed",
            symbol="rb",
            contract="rb.MAIN",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 10, tzinfo=UTC),
        )
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file, status="passed"))
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        response = client.get(
            "/api/klines",
            params={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "5m",
                "start": "2021-01-04",
                "end": "2021-01-04",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 2
        assert payload[0]["symbol"] == "rb"
        assert payload[0]["contract"] == "rb.MAIN"
        assert payload[0]["time"].startswith("2021-01-04T09:05:00")
        assert payload[0]["openInterest"] == 100.0

        missing_param = client.get("/api/klines", params={"symbol": "rb", "contract": "rb.MAIN"})
        assert missing_param.status_code == 422

        empty = client.get(
            "/api/klines",
            params={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "15m",
                "start": datetime(2021, 1, 4, tzinfo=UTC).isoformat(),
                "end": datetime(2021, 1, 5, tzinfo=UTC).isoformat(),
            },
        )
        assert empty.status_code == 200
        assert empty.json() == []
    finally:
        app.dependency_overrides.clear()


def test_market_workbench_coverage_and_bars_use_canonical_data(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        _write_api_bar_file(
            path,
            provider="rqdata",
            symbol="rb",
            contract="rb.MAIN",
            exchange="SHFE",
            period="5m",
            closes=[3010.0, 3020.0],
        )
        market_file = _market_file(path, provider="rqdata", data_role="primary", quality_status="warning", symbol="rb", contract="rb.MAIN")
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file, status="warning"))
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        coverage = client.get("/api/v1/market/workbench/coverage")
        assert coverage.status_code == 200
        payload = coverage.json()
        assert payload["default_selection"]["symbol"] == "rb"
        assert payload["default_selection"]["contract"] == "rb.MAIN"
        assert payload["default_selection"]["period"] == "5m"
        assert payload["items"][0]["quality_status"] == "warning"
        assert payload["items"][0]["row_count"] == 2

        bars = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "5m",
                "start": "2026-01-05",
                "end": "2026-01-05",
            },
        )
        assert bars.status_code == 200
        bars_payload = bars.json()
        assert len(bars_payload["bars"]) == 2
        assert bars_payload["bars"][0]["time"].startswith("2026-01-05T09:05:00")
        assert bars_payload["quality"]["status"] == "warning"
        assert bars_payload["coverage"]["quality_status"] == "warning"

        too_many = client.get(
            "/api/v1/market/bars",
            params={"symbol": "rb", "contract": "rb.MAIN", "period": "5m", "limit": 10001},
        )
        assert too_many.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_workbench_coverage_filters_by_symbol_contract_period_and_excludes_paths(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        jm_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m.parquet"
        rb_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        _write_api_bar_file(
            jm_path,
            provider="rqdata",
            symbol="jm",
            contract="JM2609",
            exchange="DCE",
            period="15m",
            closes=[1700.0, 1710.0],
            start=datetime(2026, 7, 7, 9, 15),
        )
        _write_api_bar_file(
            rb_path,
            provider="rqdata",
            symbol="rb",
            contract="rb.MAIN",
            exchange="SHFE",
            period="5m",
            closes=[3010.0, 3020.0],
        )
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2609",
                period="15m",
                start_time=datetime(2026, 7, 7, 9, 15, tzinfo=UTC),
                end_time=datetime(2026, 7, 7, 15, 0, tzinfo=UTC),
                file_path=str(jm_path),
                row_count=2,
                data_version="jm_15m_test",
                data_role="primary",
                quality_status="passed",
            )
        )
        rb_file = _market_file(rb_path, provider="rqdata", data_role="primary", quality_status="passed", symbol="rb", contract="rb.MAIN")
        session.add(rb_file)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        scoped = client.get(
            "/api/v1/market/workbench/coverage",
            params={"symbol": "jm", "contract": "JM2609", "period": "15m"},
        )
        assert scoped.status_code == 200
        scoped_payload = scoped.json()
        assert len(scoped_payload["items"]) == 1
        assert scoped_payload["items"][0]["symbol"] == "jm"
        assert scoped_payload["items"][0]["contract"] == "JM2609"
        assert scoped_payload["items"][0]["period"] == "15m"
        assert scoped_payload["items"][0]["file_path"] is None

        summary = client.get(
            "/api/v1/market/workbench/coverage",
            params={"symbol": "jm", "contract": "JM2609", "period": "15m", "summary": "true"},
        )
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["available"] is True
        assert summary_payload["row_count"] == 2
        assert summary_payload["quality_status"] == "passed"

        full = client.get("/api/v1/market/workbench/coverage")
        assert full.status_code == 200
        assert len(full.json()["items"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_market_workbench_coverage_exposes_actual_contract_view_metadata(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    main_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_main_15m.parquet"
    actual_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m.parquet"
    _write_api_bar_file(
        main_path,
        provider="rqdata",
        symbol="jm",
        contract="jm.MAIN",
        exchange="DCE",
        period="15m",
        closes=[1700.0, 1710.0],
        start=datetime(2026, 7, 7, 9, 15),
    )
    _write_api_bar_file(
        actual_path,
        provider="rqdata",
        symbol="jm",
        contract="JM2609",
        exchange="DCE",
        period="15m",
        closes=[1800.0, 1810.0],
        start=datetime(2026, 7, 7, 9, 15),
    )

    with TestingSessionLocal() as session:
        main_file = _market_file(
            main_path,
            provider="rqdata",
            data_role="primary",
            quality_status="passed",
            symbol="jm",
            contract="jm.MAIN",
            start=datetime(2026, 7, 7, 9, 15, tzinfo=UTC),
            end=datetime(2026, 7, 7, 9, 30, tzinfo=UTC),
        )
        main_file.period = "15m"
        main_file.data_version = "rqdata_jm_main_15m_v1"
        actual_file = _market_file(
            actual_path,
            provider="rqdata",
            data_role="primary",
            quality_status="passed",
            symbol="jm",
            contract="JM2609",
            start=datetime(2026, 7, 7, 9, 15, tzinfo=UTC),
            end=datetime(2026, 7, 7, 9, 30, tzinfo=UTC),
        )
        actual_file.period = "15m"
        actual_file.data_version = "rqdata_actual_contract_bars_jm_JM2609_15m_20260706_20260707_v1"
        session.add_all([main_file, actual_file])
        session.flush()
        session.add_all([_quality_report(main_file, status="passed"), _quality_report(actual_file, status="passed")])
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        coverage = client.get("/api/v1/market/workbench/coverage", params={"include_paths": "true"})
        assert coverage.status_code == 200
        payload = coverage.json()
        items = {(item["contract"], item["period"]): item for item in payload["items"]}
        main = items[("jm.MAIN", "15m")]
        actual = items[("JM2609", "15m")]

        assert payload["default_selection"]["contract"] == "JM2609"
        assert main["view_role"] == "continuous"
        assert main["continuous_contract"] == "jm.MAIN"
        assert main["actual_contract"] is None
        assert main["latest_bar_time"].startswith("2026-07-07T09:30:00")
        assert main["data_version"] == "rqdata_jm_main_15m_v1"
        assert main["file_path"].endswith("jm_main_15m.parquet")

        assert actual["view_role"] == "actual_contract"
        assert actual["continuous_contract"] == "jm.MAIN"
        assert actual["actual_contract"] == "JM2609"
        assert actual["latest_bar_time"].startswith("2026-07-07T09:30:00")
        assert actual["data_version"] == "rqdata_actual_contract_bars_jm_JM2609_15m_20260706_20260707_v1"
        assert actual["file_path"].endswith("jm2609_15m.parquet")

        bars = client.get(
            "/api/v1/market/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "15m", "limit": 10},
        )
        assert bars.status_code == 200
        bars_payload = bars.json()
        assert bars_payload["coverage"]["view_role"] == "actual_contract"
        assert bars_payload["coverage"]["actual_contract"] == "JM2609"
        assert bars_payload["coverage"]["latest_bar_time"].startswith("2026-07-07T09:30:00")
        assert bars_payload["coverage"]["data_version"] == actual["data_version"]
        assert bars_payload["coverage"]["file_path"] == actual["file_path"]
    finally:
        app.dependency_overrides.clear()


def test_market_dominants_and_quote_mode_reject_main_contract(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
        session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=datetime(2026, 7, 7).date(),
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-v1",
            )
        )
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m.parquet"
        _write_api_bar_file(
            path,
            provider="rqdata",
            symbol="jm",
            contract="JM2609",
            exchange="DCE",
            period="15m",
            closes=[1800.0],
            start=datetime(2026, 7, 7, 9, 15),
        )
        market_file = _market_file(
            path,
            provider="rqdata",
            data_role="primary",
            quality_status="passed",
            symbol="jm",
            contract="JM2609",
            start=datetime(2026, 7, 7, 9, 15, tzinfo=UTC),
            end=datetime(2026, 7, 7, 9, 30, tzinfo=UTC),
        )
        market_file.period = "15m"
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file, status="passed"))
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        dominants = client.get("/api/v1/market/dominants")
        assert dominants.status_code == 200
        payload = dominants.json()
        assert payload["items"][0]["actual_contract"] == "JM2609"
        assert payload["items"][0]["quote_ready"] is True

        rejected = client.get(
            "/api/v1/market/bars",
            params={"symbol": "jm", "contract": "jm.MAIN", "period": "15m", "quote_mode": True},
        )
        assert rejected.status_code == 422
        assert "actual_contract" in rejected.json()["detail"]

        allowed = client.get(
            "/api/v1/market/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "15m", "quote_mode": True},
        )
        assert allowed.status_code == 200
        assert len(allowed.json()["bars"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_market_bars_filters_provider_and_data_role_for_report_kline(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    rqdata_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_5m.parquet"
    tqsdk_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=tqsdk" / "jm_5m.parquet"
    _write_jm_api_bar_file(rqdata_path, provider="rqdata", close=1005.0)
    _write_jm_api_bar_file(tqsdk_path, provider="tqsdk", close=9005.0)

    with TestingSessionLocal() as session:
        rqdata_file = _market_file(rqdata_path, provider="rqdata", data_role="primary", quality_status="passed")
        tqsdk_file = _market_file(tqsdk_path, provider="tqsdk", data_role="validation", quality_status="warning")
        session.add_all([rqdata_file, tqsdk_file])
        session.flush()
        session.add_all(
            [
                _quality_report(rqdata_file, status="passed"),
                _quality_report(tqsdk_file, status="warning"),
            ]
        )
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        response = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "5m",
                "provider": "rqdata",
                "data_role": "primary",
                "limit": 10,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["request"]["provider"] == "rqdata"
        assert payload["request"]["data_role"] == "primary"
        assert payload["coverage"]["provider"] == "rqdata"
        assert payload["coverage"]["quality_status"] == "passed"
        assert payload["quality"]["status"] == "passed"
        assert [bar["provider"] for bar in payload["bars"]] == ["rqdata"]
        assert [bar["close"] for bar in payload["bars"]] == [1005.0]

        mismatched = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "5m",
                "provider": "tqsdk",
                "data_role": "primary",
                "limit": 10,
            },
        )
        assert mismatched.status_code == 200
        assert mismatched.json()["bars"] == []
    finally:
        app.dependency_overrides.clear()


def test_market_bars_uses_historical_facade_and_preserves_full_response(monkeypatch) -> None:
    from app.api import market as market_api

    facade_response = MarketBarsResponse(
        bars=[
            {
                "time": "2026-07-01T09:00:00",
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "close": 1234.5,
            }
        ],
        quality=MarketBarsQuality(status="warning", warning_reasons=["coverage_pending"]),
        coverage=MarketBarsCoverage(
            symbol="jm",
            contract="JM2609",
            period="15m",
            provider="rqdata",
            data_role="primary",
            quality_status="warning",
            row_count=1,
        ),
        request=MarketBarsRequest(
            symbol="jm",
            contract="JM2609",
            period="15m",
            start=datetime(2026, 7, 1, 9, 0),
            end=datetime(2026, 7, 2, 4, 45),
            provider="rqdata",
            data_role="primary",
            profile_id="intraday_research_v1",
            access_mode="research",
            expected_market_data_file_id=17,
            expected_lineage_token="dataset-descriptor-snapshot-v1:abc",
            limit=7,
            tail=False,
        ),
        lineage=MarketReadLineage(
            access_mode="research",
            strict_research_ready=True,
            profile_id="intraday_research_v1",
            quality_policy="passed_only",
            market_data_file_id=17,
            market_data_file_ids=[17],
            data_version="jm_15m_v1",
            data_versions=["jm_15m_v1"],
            provider="rqdata",
            data_role="primary",
            quality_status="warning",
            lineage_token="dataset-descriptor-snapshot-v1:abc",
            source_mode="historical",
            view_role="actual_contract",
            actual_contract="JM2609",
        ),
        strict_research_ready=True,
        message="facade response",
    )

    class HistoricalFacade:
        observed: dict[str, object] | None = None

        def __init__(self, session) -> None:
            self.session = session

        def get_bars(self, request, *, start, end, limit, tail):
            HistoricalFacade.observed = {
                "request": request,
                "start": start,
                "end": end,
                "limit": limit,
                "tail": tail,
            }
            return facade_response

        def to_market_bars_response(self, result):
            assert result is facade_response
            return result

    monkeypatch.setattr(market_api, "MarketDataService", HistoricalFacade, raising=False)
    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "start": "2026-07-01T09:00:00",
                "end": "2026-07-02T04:45:00",
                "provider": "rqdata",
                "data_role": "primary",
                "profile_id": "intraday_research_v1",
                "access_mode": "research",
                "expected_market_data_file_id": 17,
                "expected_lineage_token": "dataset-descriptor-snapshot-v1:abc",
                "quote_mode": True,
                "allow_continuous": True,
                "tail": False,
                "limit": 7,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == facade_response.model_dump(mode="json")
    observed = HistoricalFacade.observed
    assert observed is not None
    request = observed["request"]
    assert request.data_context == "historical"
    assert request.contract_selector == "explicit"
    assert request.symbol == "jm"
    assert request.contract == "JM2609"
    assert request.period == "15m"
    assert request.access_mode == "research"
    assert request.profile_id == "intraday_research_v1"
    assert request.provider == "rqdata"
    assert request.data_role == "primary"
    assert request.expected_market_data_file_id == 17
    assert request.expected_lineage_token == "dataset-descriptor-snapshot-v1:abc"
    assert request.quote_mode is True
    assert request.allow_continuous is True
    assert observed["start"] == datetime(2026, 7, 1, 9, 0)
    assert observed["end"] == datetime(2026, 7, 2, 4, 45)
    assert observed["limit"] == 7
    assert observed["tail"] is False


@pytest.mark.parametrize(
    ("profile_id", "domain_code"),
    [
        ("missing_profile", "DATASET_ASSET_MISSING"),
        ("wrong_profile", "DATASET_ASSET_AMBIGUOUS"),
    ],
)
def test_market_bars_prioritizes_quote_contract_error_over_profile_resolution(
    monkeypatch,
    profile_id: str,
    domain_code: str,
) -> None:
    from app.services import market_data_service as market_data_service_module

    class ProfileFailureResolver:
        def __init__(self, session) -> None:
            self.session = session

        def resolve_historical(self, request):
            raise ActiveDatasetDomainError(domain_code)

    monkeypatch.setattr(
        market_data_service_module,
        "ActiveDatasetResolver",
        ProfileFailureResolver,
    )

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "15m",
                "profile_id": profile_id,
                "quote_mode": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json() == {
        "detail": "行情页请使用 actual_contract，主连 *.MAIN 仅用于回测"
    }


@pytest.mark.parametrize(
    ("contract", "period"),
    [
        ("JM-BAD", "15m"),
        ("JM2609", "2m"),
        ("jm2609", "15m"),
    ],
)
def test_market_bars_preserves_legacy_json_for_noncanonical_or_unsupported_jm_shapes(
    contract: str,
    period: str,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": contract,
                "period": period,
                "limit": 10,
            },
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert response.json() == _expected_empty_legacy_bars_payload(
        contract=contract,
        period=period,
    )


def test_market_bars_maps_facade_domain_errors_to_legacy_http_contracts(monkeypatch) -> None:
    from app.api import market as market_api

    expected_errors = {
        "DATASET_ASSET_MISSING": (
            422,
            {
                "detail": {
                    "code": "MARKET_PROFILE_FILE_MISSING",
                    "message": "market Profile physical file is missing",
                    "context": {
                        "profile_id": None,
                        "symbol": "jm",
                        "contract": "JM2609",
                        "period": "15m",
                    },
                }
            },
        ),
        "DATASET_ASSET_AMBIGUOUS": (
            422,
            {
                "detail": {
                    "code": "MARKET_PROFILE_IDENTITY_MISMATCH",
                    "message": "market Profile asset identity does not match the request",
                    "context": {
                        "profile_id": None,
                        "symbol": "jm",
                        "contract": "JM2609",
                        "period": "15m",
                    },
                }
            },
        ),
        "DATASET_LINEAGE_CHANGED": (
            409,
            {
                "detail": {
                    "code": "MARKET_LINEAGE_CHANGED",
                    "message": "market lineage changed after the bars snapshot",
                    "context": {
                        "profile_id": None,
                        "symbol": "jm",
                        "contract": "JM2609",
                        "period": "15m",
                    },
                }
            },
        ),
    }

    for domain_code, (status_code, expected_json) in expected_errors.items():
        class HistoricalFacade:
            def __init__(self, session) -> None:
                self.session = session

            def get_bars(self, request, *, start, end, limit, tail):
                raise ActiveDatasetDomainError(domain_code)

        monkeypatch.setattr(market_api, "MarketDataService", HistoricalFacade, raising=False)
        def override_get_db():
            yield object()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.get(
                "/api/v1/market/bars",
                params={"symbol": "jm", "contract": "JM2609", "period": "15m"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == status_code
        assert response.json() == expected_json
        assert domain_code not in response.text
        assert "DATASET_" not in response.text


def test_market_bars_does_not_mislabel_or_leak_unapproved_facade_domain_errors(
    monkeypatch,
) -> None:
    from app.api import market as market_api

    class HistoricalFacade:
        def __init__(self, session) -> None:
            self.session = session

        def get_bars(self, request, *, start, end, limit, tail):
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    monkeypatch.setattr(
        market_api,
        "MarketDataService",
        HistoricalFacade,
        raising=False,
    )

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get(
            "/api/v1/market/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "15m"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "MARKET_PROFILE_IDENTITY_MISMATCH" not in response.text
    assert "DATASET_" not in response.text


def test_live_market_api_requires_explicit_live_endpoints_and_keeps_historical_clean(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    historical_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_5m.parquet"
    _write_jm_api_bar_file(historical_path, provider="rqdata", close=1005.0)
    with TestingSessionLocal() as session:
        market_file = _market_file(historical_path, provider="rqdata", data_role="primary", quality_status="passed")
        session.add(market_file)
        session.add(
            LiveMinuteBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period="1m",
                bar_datetime=datetime(2026, 7, 7, 9, 1),
                trading_day=datetime(2026, 7, 7).date(),
                open=100,
                high=102,
                low=99,
                close=101,
                volume=10,
                open_interest=100,
                turnover=1000,
                bar_status="confirmed",
                quality_status="warning",
                source_mode="poll_get_price_1m",
                raw_payload={"quality_reasons": ["missing_trading_day"]},
            )
        )
        session.flush()
        session.add(_quality_report(market_file, status="passed"))
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        historical = client.get(
            "/api/v1/market/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "1m", "limit": 10},
        )
        assert historical.status_code == 200
        assert historical.json()["bars"] == []

        coverage = client.get("/api/v1/market/live/coverage")
        assert coverage.status_code == 200
        coverage_payload = coverage.json()
        assert coverage_payload["items"][0]["data_type"] == "live_db"
        assert coverage_payload["items"][0]["quality_status"] == "warning"

        live = client.get(
            "/api/v1/market/live/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "1m", "limit": 10},
        )
        assert live.status_code == 200
        live_payload = live.json()
        assert len(live_payload["bars"]) == 1
        assert live_payload["bars"][0]["source_mode"] == "poll_get_price_1m"
        assert live_payload["bars"][0]["quality_status"] == "warning"
        assert live_payload["quality"]["status"] == "warning"
        assert live_payload["coverage"]["data_type"] == "live_db"

        unsupported = client.get(
            "/api/v1/market/live/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "1d", "limit": 10},
        )
        assert unsupported.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_live_targets_api_resolves_actual_contract_target_and_coverage(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        _add_live_target_metadata(session, tmp_path, periods=("1m", "5m", "15m"))
        session.add(
            LiveMinuteBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period="1m",
                bar_datetime=datetime(2026, 7, 7, 9, 1),
                trading_day=date(2026, 7, 7),
                open=100,
                high=102,
                low=99,
                close=101,
                volume=10,
                open_interest=100,
                turnover=1000,
                bar_status="confirmed",
                quality_status="passed",
                source_mode="poll_get_price_1m",
            )
        )
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/v1/market/live/targets")

        assert response.status_code == 200
        payload = response.json()
        assert payload["preview_only"] is True
        assert payload["writes_strategy_signal"] is False
        assert payload["writes_signal_event"] is False
        assert payload["sends_notification"] is False
        assert payload["auto_order"] is False
        assert payload["readiness_status"] == "ready"
        item = payload["items"][0]
        assert item["product"] == "jm"
        assert item["continuous_contract"] == "jm.MAIN"
        assert item["actual_contract"] == "JM2609"
        assert item["dominant_mapping_date"] == "2026-07-07"
        assert item["blocked_reasons"] == []
        assert item["trading_parameter_status"]["status"] == "passed"
        assert item["historical_coverage"]["15m"]["quality_status"] == "passed"
        assert item["historical_coverage"]["15m"]["data_role"] == "primary"
        assert item["live_coverage"]["1m"]["data_type"] == "live_db"
        assert item["live_coverage"]["1m"]["quality_status"] == "passed"
    finally:
        app.dependency_overrides.clear()


def test_live_targets_api_reports_blocked_actual_contract_coverage(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        _add_live_target_metadata(session, tmp_path, periods=("15m",))
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/v1/market/live/targets")

        assert response.status_code == 200
        payload = response.json()
        assert payload["readiness_status"] == "blocked"
        reasons = payload["items"][0]["blocked_reasons"]
        assert reasons == ["historical_actual_contract_coverage_missing:1m,5m"]
    finally:
        app.dependency_overrides.clear()


def _write_api_bar_file(
    path,
    *,
    provider: str,
    symbol: str,
    contract: str,
    exchange: str,
    period: str,
    closes: list[float],
    start: datetime = datetime(2026, 1, 5, 9, 5),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "symbol": symbol,
                "contract": contract,
                "exchange": exchange,
                "datetime": start + pd.Timedelta(minutes=index * 5),
                "trading_day": start.date(),
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 10,
                "open_interest": 100,
                "turnover": close * 10,
                "period": period,
                "provider": provider,
                "data_version": f"{provider}_{symbol}_{period}_test",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_jm_api_bar_file(path, *, provider: str, close: float) -> None:
    _write_api_bar_file(
        path,
        provider=provider,
        symbol="jm",
        contract="jm.MAIN",
        exchange="DCE",
        period="5m",
        closes=[close],
    )


def _add_live_target_metadata(session, tmp_path, *, periods: tuple[str, ...]) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 7),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="map-v1",
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code="JM2609",
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=date(2026, 7, 7),
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.12"),
            open_commission=Decimal("0.0001"),
            close_commission=Decimal("0.0001"),
            close_today_commission=Decimal("0.0001"),
            commission_type="ratio",
            price_tick=Decimal("0.5"),
            contract_multiplier=60,
            provider="rqdata",
            data_version="params-v1",
        )
    )
    for period in periods:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / f"jm2609_{period}.parquet"
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2609",
                period=period,
                start_time=datetime(2026, 7, 7, 9, 1, tzinfo=UTC),
                end_time=datetime(2026, 7, 7, 15, 0, tzinfo=UTC),
                file_path=str(path),
                row_count=100,
                data_version=f"actual-{period}-v1",
                data_role="primary",
                quality_status="passed",
            )
        )


def _market_file(
    path,
    *,
    provider: str,
    data_role: str,
    quality_status: str,
    symbol: str = "jm",
    contract: str = "jm.MAIN",
    start: datetime = datetime(2026, 1, 5, 9, 5, tzinfo=UTC),
    end: datetime = datetime(2026, 1, 5, 9, 10, tzinfo=UTC),
) -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period="5m",
        start_time=start,
        end_time=end,
        file_path=str(path),
        row_count=2,
        data_version=f"{provider}_{symbol}_5m_test",
        data_role=data_role,
        quality_status=quality_status,
    )


def _quality_report(market_file: MarketDataFile, *, status: str) -> DataQualityReport:
    return DataQualityReport(
        file_id=market_file.id,
        provider=market_file.provider,
        data_type="bars",
        instrument_symbol=market_file.instrument_symbol,
        contract_code=market_file.contract_code,
        period="5m",
        start_time=market_file.start_time,
        end_time=market_file.end_time,
        status=status,
        missing_bars=0,
        duplicated_bars=0,
        abnormal_price_count=0,
        abnormal_volume_count=0,
        details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
    )
