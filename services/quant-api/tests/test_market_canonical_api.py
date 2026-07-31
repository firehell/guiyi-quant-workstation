from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import market as market_api
from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import BarFrequency, BarsResult, DatasetKey, DatasetKind
from app.data_core.catalog import HistoricalCatalog, PartitionManifest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.canonical_market_data import get_canonical_coverage


START = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
END = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)


def _result() -> BarsResult:
    dataset = DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )
    bar = CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M1,
        bar_end=END,
        trading_day=date(2026, 7, 1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("12"),
        turnover=Decimal("1206"),
        open_interest=Decimal("99"),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )
    return BarsResult(
        bars=(bar,),
        source_datasets=(dataset,),
        manifest_digests=("a" * 64,),
        requested_window=(START, END),
        data_type=DatasetKind.ACTUAL_DOMINANT,
        derived_frequency=None,
        source_data_versions=("rqdata-test-v1",),
    )


def _rollover_result() -> BarsResult:
    first = _result()
    second_dataset = DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2701",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )
    second_bar = CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2701",
        frequency=BarFrequency.M1,
        bar_end=datetime(2026, 7, 1, 1, 2, tzinfo=UTC),
        trading_day=date(2026, 7, 1),
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101.5"),
        volume=Decimal("13"),
        turnover=Decimal("1319.5"),
        open_interest=Decimal("100"),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )
    return BarsResult(
        bars=(*first.bars, second_bar),
        source_datasets=(*first.source_datasets, second_dataset),
        manifest_digests=("a" * 64, "b" * 64),
        requested_window=(START, datetime(2026, 7, 1, 1, 2, tzinfo=UTC)),
        data_type=DatasetKind.ACTUAL_DOMINANT,
        derived_frequency=None,
        source_data_versions=("rqdata-test-v1", "rqdata-test-v2"),
    )


def test_canonical_market_bars_requires_explicit_v2_identity_and_window(
    monkeypatch,
) -> None:
    observed = {}

    class Reader:
        def get_bars(self, query):
            observed["query"] = query
            return _result()

    monkeypatch.setattr(market_api, "_canonical_reader", lambda _session: Reader())
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    try:
        response = TestClient(app).get(
            "/api/v1/market/bars/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T01:00:00Z",
                "end": "2026-07-01T01:01:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["bars"][0]["close"] == 100.5
    assert payload["bars"][0]["time"] == "2026-07-01T01:01:00Z"
    assert payload["quality"]["status"] == "passed"
    assert payload["coverage"]["row_count"] == 1
    assert payload["lineage"]["profile_id"] is None
    assert len(payload["lineage"]["lineage_token"]) == 64
    assert payload["strict_research_ready"] is True
    assert {
        key: value
        for key, value in payload["data_identity"].items()
        if key != "request_identity_token"
    } == {
        "dataset_kind": "actual_dominant",
        "frequency": "1m",
        "source_datasets": [
            {
                "provider": "rqdata",
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "contract_or_series": "JM2609",
                "frequency": "1m",
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
            }
        ],
        "manifest_digests": ["a" * 64],
        "source_data_versions": ["rqdata-test-v1"],
        "requested_window": ["2026-07-01T01:00:00Z", "2026-07-01T01:01:00Z"],
        "derived_frequency": None,
    }
    assert len(payload["data_identity"]["request_identity_token"]) == 64
    assert observed["query"].contract_or_series is None


def test_canonical_coverage_comes_from_catalog_without_legacy_profile() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        dataset = _result().source_datasets[0]
        HistoricalCatalog(session).register_partition(
            dataset,
            PartitionManifest(
                coverage_start=START,
                coverage_end=END,
                manifest_version="canonical-manifest-v1",
                manifest_uri="manifests/jm.json",
                manifest_digest="a" * 64,
                file_uri="bars/jm.parquet",
                checksum="b" * 64,
                row_count=1,
            ),
        )
        coverage = get_canonical_coverage(session, symbol="jm")

    assert [item.period for item in coverage.items] == [
        "1m",
        "5m",
        "15m",
        "30m",
        "60m",
    ]
    assert {item.profile_id for item in coverage.items} == {None}
    assert {item.quality_status for item in coverage.items} == {
        "catalog_only_unverified"
    }
    assert coverage.default_selection is not None
    assert coverage.default_selection.period == "1m"


def test_canonical_market_bars_rejects_naive_window_without_reading(monkeypatch) -> None:
    monkeypatch.setattr(
        market_api,
        "_canonical_reader",
        lambda _session: (_ for _ in ()).throw(AssertionError("must not read")),
    )
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    try:
        response = TestClient(app).get(
            "/api/v1/market/bars/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T01:00:00",
                "end": "2026-07-01T01:01:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DATA_CONTRACT_INVALID"


def test_canonical_rfc3339_windows_share_source_lineage_but_not_request_identity(
    monkeypatch,
) -> None:
    class Reader:
        def get_bars(self, query):
            original = _result()
            bar = original.bars[0]
            shifted_bar = CanonicalBar(
                **{
                    **{
                        field: getattr(bar, field)
                        for field in (
                            "provider",
                            "dataset_kind",
                            "symbol",
                            "contract_or_series",
                            "frequency",
                            "trading_day",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "turnover",
                            "open_interest",
                            "adjustment",
                            "schema_version",
                        )
                    },
                    "bar_end": query.end,
                }
            )
            return BarsResult(
                bars=(shifted_bar,),
                source_datasets=original.source_datasets,
                manifest_digests=original.manifest_digests,
                requested_window=(query.start, query.end),
                data_type=original.data_type,
                derived_frequency=None,
                source_data_versions=original.source_data_versions,
            )

    monkeypatch.setattr(market_api, "_canonical_reader", lambda _session: Reader())
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    try:
        client = TestClient(app)
        first = client.get(
            "/api/v1/market/bars/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T09:00:00+08:00",
                "end": "2026-07-01T09:01:00+08:00",
            },
        )
        second = client.get(
            "/api/v1/market/bars/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T09:01:00+08:00",
                "end": "2026-07-01T09:02:00+08:00",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["request"]["start"] == "2026-07-01T01:00:00Z"
    assert first_payload["lineage"]["lineage_token"] == second_payload["lineage"][
        "lineage_token"
    ]
    assert first_payload["data_identity"]["request_identity_token"] != second_payload[
        "data_identity"
    ]["request_identity_token"]


def test_canonical_public_indicator_uses_same_verified_bar_identity(monkeypatch) -> None:
    class Reader:
        def get_bars(self, _query):
            return _result()

    monkeypatch.setattr(market_api, "_canonical_reader", lambda _session: Reader())
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    try:
        response = TestClient(app).get(
            "/api/v1/market/indicators/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T01:00:00Z",
                "end": "2026-07-01T01:01:00Z",
                "indicator_codes": "ema10,ema21",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert {
        indicator["indicator_code"] for indicator in payload["indicators"]
    } == {"ema10", "ema21"}
    assert payload["data_identity"]["dataset_kind"] == "actual_dominant"
    assert payload["lineage"]["profile_id"] is None
    assert payload["lineage"]["data_versions"] == ["rqdata-test-v1"]


def test_canonical_ema_reads_lineage_bound_prewindow_warmup(monkeypatch) -> None:
    observed = {}

    class Reader:
        def get_bars(self, query):
            observed["query"] = query
            dataset = _result().source_datasets[0]
            bars = tuple(
                CanonicalBar(
                    provider="rqdata",
                    dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                    symbol="jm",
                    contract_or_series="JM2609",
                    frequency=BarFrequency.M1,
                    bar_end=query.start + timedelta(minutes=index),
                    trading_day=date(2026, 7, 1),
                    open=Decimal(str(100 + index)),
                    high=Decimal(str(101 + index)),
                    low=Decimal(str(99 + index)),
                    close=Decimal(str(100 + index)),
                    volume=Decimal("12"),
                    turnover=Decimal("1200"),
                    open_interest=Decimal("99"),
                    adjustment="none",
                    schema_version="canonical-bar-v1",
                )
                for index in range(1, int((query.end - query.start).total_seconds() // 60) + 1)
            )
            return BarsResult(
                bars=bars,
                source_datasets=(dataset,),
                manifest_digests=("a" * 64,),
                requested_window=(query.start, query.end),
                data_type=DatasetKind.ACTUAL_DOMINANT,
                derived_frequency=None,
                source_data_versions=("rqdata-test-v1",),
            )

    monkeypatch.setattr(market_api, "_canonical_reader", lambda _session: Reader())
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    try:
        response = TestClient(app).get(
            "/api/v1/market/indicators/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T01:00:00Z",
                "end": "2026-07-01T01:01:00Z",
                "indicator_codes": "ema10",
                "display_bar_count": 1,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert observed["query"].start < datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
    assert payload["indicators"][0]["points"] == [
        {
            "time": "2026-07-01T01:01:00",
            "value": 105.5,
            "ready": True,
            "valid": True,
            "reason": None,
        }
    ]
    assert payload["warmup"]["source_bar_count"] > payload["warmup"][
        "display_bar_count"
    ]


def test_canonical_actual_dominant_rollover_does_not_claim_one_actual_contract(
    monkeypatch,
) -> None:
    class Reader:
        def get_bars(self, _query):
            return _rollover_result()

    monkeypatch.setattr(market_api, "_canonical_reader", lambda _session: Reader())
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    try:
        response = TestClient(app).get(
            "/api/v1/market/bars/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T01:00:00Z",
                "end": "2026-07-01T01:02:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["contract"] == "jm.ACTUAL_DOMINANT"
    assert payload["coverage"]["actual_contract"] is None
    assert payload["lineage"]["actual_contract"] is None
    assert {
        source["contract_or_series"]
        for source in payload["data_identity"]["source_datasets"]
    } == {"JM2609", "JM2701"}


def test_canonical_public_macd_keeps_legacy_formula_and_v2_identity(monkeypatch) -> None:
    class Reader:
        def get_bars(self, _query):
            return _result()

    monkeypatch.setattr(market_api, "_canonical_reader", lambda _session: Reader())
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    try:
        response = TestClient(app).get(
            "/api/v1/market/indicators/macd/canonical",
            params={
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": "1m",
                "start": "2026-07-01T01:00:00Z",
                "end": "2026-07-01T01:01:00Z",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["policy"] == "web_macd_legacy_v1"
    assert payload["parameters"]["ema_seed_policy"] == "sma_window"
    assert payload["parameters"]["histogram_scale"] == 2
    assert payload["data_identity"]["dataset_kind"] == "actual_dominant"
    assert payload["lineage"]["lineage_token"] == payload["request"][
        "expected_lineage_token"
    ]
