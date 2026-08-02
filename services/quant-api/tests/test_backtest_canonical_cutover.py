from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.service import BacktestService
from app.backtest.runner import BacktestTaskRunner
from app.api.backtests import report_api_payload, task_api_payload
from app.backtest.v1b_jm_tasks import build_jm_v1b_formal_request
from app.data_core.bar_schema import CANONICAL_BAR_SCHEMA_VERSION, CanonicalBar
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    BarsResult,
    DataGapError,
    DatasetAmbiguousError,
    DatasetKey,
)
from app.db.base import Base
from app.models.backtest import BacktestReportModel, BacktestTask
from app.db.session import get_db
from app.main import app
from app.services.batch_backtest import create_batch_task
from app.vnpy_integration.errors import BacktestConfigurationError
from app.schemas.backtest import FormalBacktestTaskRequest
from app.vnpy_integration.backtest_runner import _validate_standard_rows


def _formal_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset_kind": "actual_dominant",
        "instrument_symbol": "jm",
        "contract_or_series": None,
        "exchange": "DCE",
        "interval": "15m",
        "auxiliary_periods": ["1d"],
        "start": datetime(2024, 1, 2, tzinfo=UTC),
        "end": datetime(2024, 2, 2, tzinfo=UTC),
        "strategy_class_path": "tests.test_backtest_canonical_cutover:FakeStrategy",
        "strategy_code": "canonical_cutover_test",
        "strategy_version": "v1",
        "strategy_parameters": {
            "indicator_versions": ["ema21"],
            "formal_policy_ids": ["ema_sma_window_v1"],
            "confirmed_only": True,
            "research_status": "formal_candidate",
        },
    }
    payload.update(overrides)
    return payload


class FakeStrategy:
    pass


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _canonical_result(query: BarQuery) -> BarsResult:
    source_frequency = BarFrequency.M1 if query.frequency is BarFrequency.M15 else query.frequency
    source = DatasetKey(
        provider="rqdata",
        dataset_kind=query.dataset_kind,
        symbol=query.symbol,
        contract_or_series=(query.contract_or_series or "JM2405"),
        frequency=source_frequency,
        adjustment="none",
        schema_version=CANONICAL_BAR_SCHEMA_VERSION,
    )
    bar = CanonicalBar(
        provider="rqdata",
        dataset_kind=query.dataset_kind,
        symbol=query.symbol,
        contract_or_series=(query.contract_or_series or "JM2405"),
        frequency=query.frequency,
        bar_end=datetime(2024, 1, 2, 15, 0, tzinfo=UTC),
        trading_day=date(2024, 1, 2),
        open=Decimal("1000.123456789012345678"),
        high=Decimal("1002"),
        low=Decimal("999"),
        close=Decimal("1001.5"),
        volume=Decimal("10"),
        turnover=Decimal("600000"),
        open_interest=Decimal("100"),
        adjustment="none",
        schema_version=CANONICAL_BAR_SCHEMA_VERSION,
    )
    return BarsResult(
        bars=(bar,),
        source_datasets=(source,),
        manifest_digests=(("a" if query.frequency is BarFrequency.M15 else "b") * 64,),
        source_data_versions=(("canonical-15m" if query.frequency is BarFrequency.M15 else "canonical-1d"),),
        requested_window=(query.start, query.end),
        data_type=query.dataset_kind,
        derived_frequency=(BarFrequency.M15 if query.frequency is BarFrequency.M15 else None),
    )


class FakeMarketDataService:
    def __init__(self) -> None:
        self.queries: list[BarQuery] = []

    def get_bars(self, query: BarQuery) -> BarsResult:
        self.queries.append(query)
        return _canonical_result(query)


class GapAfterFreezeMarketDataService(FakeMarketDataService):
    def get_bars(self, query: BarQuery) -> BarsResult:
        if len(self.queries) >= 2:
            raise DataGapError(facts={"phase": "execution_reread"})
        return super().get_bars(query)


class AmbiguousMarketDataService:
    def get_bars(self, query: BarQuery) -> BarsResult:
        raise DatasetAmbiguousError(
            facts={"symbol": query.symbol, "dataset_kind": query.dataset_kind.value}
        )


class CapturingAdapter:
    def __init__(self) -> None:
        self.request = None

    def run(self, request):
        self.request = request
        return {
            "statistics": {"capital": request.capital},
            "prepared": {
                "vt_symbol": f"{request.symbol}.{request.exchange}",
                "interval": request.interval,
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
                "capital": request.capital,
                "size": request.size,
                "pricetick": request.pricetick,
            },
            "trades": [],
            "orders": [],
        }


def test_formal_request_uses_canonical_dataset_identity_and_rejects_legacy_identity() -> None:
    request = FormalBacktestTaskRequest.model_validate(_formal_payload())

    assert request.dataset_kind.value == "actual_dominant"
    assert request.instrument_symbol == "jm"
    assert request.contract_or_series is None

    for forbidden in (
        {"profile_id": "intraday_research_v1"},
        {"contract_code": "jm.MAIN"},
        {"bar_data_path": "/tmp/escape.parquet"},
        {"auxiliary_bar_data_paths": {"1d": "/tmp/escape.parquet"}},
    ):
        with pytest.raises(ValidationError):
            FormalBacktestTaskRequest.model_validate({**_formal_payload(), **forbidden})


def test_formal_request_requires_series_only_for_continuous_and_timezone_aware_window() -> None:
    continuous = FormalBacktestTaskRequest.model_validate(
        _formal_payload(dataset_kind="continuous", contract_or_series="JM.MAIN")
    )
    assert continuous.contract_or_series == "JM.MAIN"

    with pytest.raises(ValidationError):
        FormalBacktestTaskRequest.model_validate(
            _formal_payload(dataset_kind="continuous", contract_or_series=None)
        )
    with pytest.raises(ValidationError):
        FormalBacktestTaskRequest.model_validate(
            _formal_payload(start=datetime(2024, 1, 2))
        )
    with pytest.raises(ValidationError):
        FormalBacktestTaskRequest.model_validate(_formal_payload(interval="2m"))


def test_actual_dominant_non_jm_is_rejected_with_stable_code() -> None:
    with pytest.raises(ValidationError) as caught:
        FormalBacktestTaskRequest.model_validate(
            _formal_payload(instrument_symbol="rb")
        )

    error = caught.value.errors()[0]
    assert error["type"] == "backtest_actual_dominant_product_unsupported"
    assert error["ctx"]["code"] == "BACKTEST_ACTUAL_DOMINANT_PRODUCT_UNSUPPORTED"


def test_fixed_jm_formal_spec_contains_no_profile_or_file_identity() -> None:
    spec = build_jm_v1b_formal_request("15m")

    assert spec.request.dataset_kind.value == "continuous"
    assert spec.request.contract_or_series == "JM.MAIN"
    assert spec.request.auxiliary_periods == ["1d"]
    assert "profile" not in json.dumps(spec.server_context)
    assert "file" not in json.dumps(spec.server_context)


@pytest.mark.parametrize(
    ("route", "payload", "expected_code"),
    [
        (
            "/api/backtests/run",
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "15m",
                "profile_id": "intraday_research_v1",
                "start": "2024-01-02",
                "end": "2024-02-02",
            },
            "BACKTEST_LEGACY_INLINE_DISABLED",
        ),
        (
            "/api/backtests/run-batch",
            {
                "watchlist_code": "black",
                "period": "15m",
                "profile_id": "intraday_research_v1",
                "start": "2024-01-02",
                "end": "2024-02-02",
                "run_inline": True,
            },
            "BACKTEST_LEGACY_BATCH_DISABLED",
        ),
    ],
)
def test_legacy_formal_routes_fail_closed_before_creating_task_or_report(
    route: str,
    payload: dict[str, object],
    expected_code: str,
) -> None:
    SessionLocal = _session_factory()

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(route, json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == expected_code
    with SessionLocal() as session:
        assert session.query(BacktestTask).count() == 0
        assert session.query(BacktestReportModel).count() == 0


def test_legacy_batch_service_cannot_create_nonresearch_task() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session, pytest.raises(
        BacktestConfigurationError,
        match="BACKTEST_LEGACY_BATCH_DISABLED",
    ):
        create_batch_task(
            session,
            {
                "watchlist_code": "black",
                "period": "15m",
                "start": "2024-01-02T00:00:00+00:00",
                "end": "2024-02-02T00:00:00+00:00",
            },
        )


def test_formal_task_freezes_canonical_input_and_leaves_legacy_columns_null() -> None:
    SessionLocal = _session_factory()
    market_data = FakeMarketDataService()
    with SessionLocal() as session:
        task = BacktestService(session, market_data=market_data).create_formal_task(
            _formal_payload()
        )

        assert [query.frequency.value for query in market_data.queries] == ["15m", "1d"]
        assert task.profile_id is None
        assert task.market_data_file_id is None
        assert task.binding_snapshot["schema_version"] == "backtest_canonical_inputs_v1"
        assert task.binding_snapshot["input_identity"]["schema_version"] == "canonical_consumer_input_v1"
        assert task.binding_snapshot["input_identity"]["strategy_input_version"] == "canonical_cutover_test@v1"
        assert task.binding_snapshot["auxiliary_input_identities"]["1d"]["schema_version"] == "canonical_consumer_input_v1"
        assert task.data_version == task.binding_snapshot["input_identity"]["digest"]
        assert len(task.data_version) == 64
        assert task.request_payload["bar_data_path"] is None
        assert task.request_payload["auxiliary_bar_data_paths"] == {}


def test_runner_rereads_identity_and_injects_canonical_rows_in_memory() -> None:
    SessionLocal = _session_factory()
    market_data = FakeMarketDataService()
    adapter = CapturingAdapter()
    with SessionLocal() as session:
        service = BacktestService(session, market_data=market_data)
        task = service.create_formal_task(
            _formal_payload(
                dataset_kind="continuous", contract_or_series="JM.MAIN"
            )
        )
        session.commit()

        outcome = BacktestTaskRunner(
            session,
            adapter=adapter,
            service=service,
        ).run(task.id)

        assert outcome["status"] == "success", outcome
        assert task.research_only is True
        assert adapter.request.bar_data_path is None
        assert adapter.request.auxiliary_bar_data_paths == {}
        assert adapter.request.bars[0]["open"] == Decimal("1000.123456789012345678")
        assert adapter.request.bars[0]["data_role"] == "primary"
        assert adapter.request.bars[0]["quality_status"] == "passed"
        assert adapter.request.auxiliary_bars["1d"][0]["interval"] == "1d"
        assert len(market_data.queries) == 4

        report = session.query(BacktestReportModel).one()
        assert report.research_only is True
        for payload in (task_api_payload(task), report_api_payload(report)):
            assert payload["input_identity"]["schema_version"] == "canonical_consumer_input_v1"
            assert payload["research_only"] is True
            assert payload["contract_semantics"] == "research_contract_only"
            assert payload["observation_only"] is True
            assert payload["not_trading_instruction"] is True
            assert payload["auto_order"] is False
            assert "profile_id" not in payload
            assert "market_data_file_id" not in payload
            assert "binding_snapshot" not in payload
            encoded = json.dumps(payload, default=str)
            assert '"profile_id"' not in encoded
            assert '"market_data_file_id"' not in encoded
            assert '"binding_snapshot"' not in encoded


def test_asia_shanghai_window_is_stored_and_executed_as_utc() -> None:
    SessionLocal = _session_factory()
    market_data = FakeMarketDataService()
    adapter = CapturingAdapter()
    china = timezone(timedelta(hours=8))
    with SessionLocal() as session:
        service = BacktestService(session, market_data=market_data)
        task = service.create_formal_task(
            _formal_payload(
                start=datetime(2024, 1, 2, 8, 0, tzinfo=china),
                end=datetime(2024, 2, 2, 8, 0, tzinfo=china),
                auxiliary_periods=[],
                dataset_kind="continuous",
                contract_or_series="JM.MAIN",
            )
        )
        session.commit()

        outcome = BacktestTaskRunner(
            session,
            adapter=adapter,
            service=service,
        ).run(task.id)

        assert outcome["status"] == "success"
        assert task.request_payload["start"] == "2024-01-02T00:00:00Z"
        assert task.request_payload["end"] == "2024-02-02T00:00:00Z"
        assert adapter.request.start == datetime(2024, 1, 2, tzinfo=UTC)
        assert adapter.request.end == datetime(2024, 2, 2, tzinfo=UTC)
        assert market_data.queries[0].start == datetime(2024, 1, 2, tzinfo=UTC)


def test_continuous_report_is_labeled_research_contract_only() -> None:
    SessionLocal = _session_factory()
    market_data = FakeMarketDataService()
    with SessionLocal() as session:
        service = BacktestService(session, market_data=market_data)
        task = service.create_formal_task(
            _formal_payload(
                dataset_kind="continuous",
                contract_or_series="JM.MAIN",
                auxiliary_periods=[],
            )
        )

        metadata = service.report_metadata(task, service.config_from_task(task))

        assert metadata["dataset_kind"] == "continuous"
        assert metadata["contract_semantics"] == "research_contract_only"
        assert metadata["research_only"] is True
        assert metadata["observation_only"] is True
        assert metadata["not_trading_instruction"] is True
        assert metadata["auto_order"] is False
        assert task.research_only is True


def test_runner_data_gap_fails_closed_without_creating_report() -> None:
    SessionLocal = _session_factory()
    market_data = GapAfterFreezeMarketDataService()
    adapter = CapturingAdapter()
    with SessionLocal() as session:
        service = BacktestService(session, market_data=market_data)
        task = service.create_formal_task(_formal_payload())
        session.commit()

        outcome = BacktestTaskRunner(
            session,
            adapter=adapter,
            service=service,
        ).run(task.id)

        assert outcome["status"] == "failed"
        assert outcome["error_type"] == "DATA_GAP"
        assert adapter.request is None
        assert session.query(BacktestReportModel).count() == 0


def test_dataset_ambiguity_creates_neither_task_nor_report() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        service = BacktestService(session, market_data=AmbiguousMarketDataService())

        with pytest.raises(DatasetAmbiguousError):
            service.create_formal_task(_formal_payload())

        assert session.query(BacktestTask).count() == 0
        assert session.query(BacktestReportModel).count() == 0


def test_vnpy_adapter_validates_exact_decimals_before_float_boundary() -> None:
    row = {
        "datetime": datetime(2024, 1, 2, tzinfo=UTC),
        "open": Decimal("1.000000000000000001"),
        "high": Decimal("1.000000000000000000"),
        "low": Decimal("1"),
        "close": Decimal("1"),
        "volume": Decimal("1"),
        "turnover": Decimal("1"),
        "open_interest": Decimal("1"),
        "data_role": "primary",
        "quality_status": "passed",
    }

    with pytest.raises(Exception, match="high"):
        _validate_standard_rows([row])
