from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    DataProfile,
    DataQualityReport,
    MainContractMap,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.services.active_dataset import (
    ActiveDatasetDomainError,
    BarsResult,
    DatasetRequest,
)
from app.services.market_data_service import MarketDataService
from app.services.market_workbench import MarketAccessError, get_market_bars
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


BAR_START = datetime(2026, 7, 30, 9, 0)
PROFILE_ID = "task5_research_v1"


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    with SessionLocal() as db_session:
        yield db_session
    engine.dispose()


def _write_bars(
    path: Path,
    *,
    contract: str,
    provider: str,
    data_version: str,
    closes: list[float],
    start: datetime = BAR_START,
    source_interval: str | None = None,
) -> list[datetime]:
    path.parent.mkdir(parents=True, exist_ok=True)
    times = [start + timedelta(minutes=15 * index) for index in range(len(closes))]
    rows: list[dict[str, Any]] = []
    for index, (bar_time, close) in enumerate(zip(times, closes, strict=True)):
        row: dict[str, Any] = {
            "symbol": "jm",
            "contract": contract,
            "exchange": "DCE",
            "datetime": bar_time,
            "trading_day": bar_time.date(),
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 100 + index,
            "open_interest": 1000 + index,
            "turnover": close * (100 + index),
            "period": "15m",
            "provider": provider,
            "data_version": data_version,
        }
        if source_interval is not None:
            row["source_interval"] = source_interval
        rows.append(row)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return times


def _add_market_file(
    session: Session,
    path: Path,
    *,
    contract: str,
    provider: str,
    data_version: str,
    quality_status: str,
    times: list[datetime],
    checksum: str,
) -> MarketDataFile:
    market_file = MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="jm",
        contract_code=contract,
        period="15m",
        start_time=times[0].replace(tzinfo=UTC),
        end_time=times[-1].replace(tzinfo=UTC),
        file_path=str(path),
        row_count=len(times),
        checksum=checksum,
        data_version=data_version,
        data_role="primary",
        quality_status=quality_status,
    )
    session.add(market_file)
    session.flush()
    return market_file


def _add_quality_report(
    session: Session,
    market_file: MarketDataFile,
    *,
    status: str = "passed",
    missing_bars: int = 0,
) -> None:
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider=market_file.provider,
            data_type="bars",
            instrument_symbol="jm",
            contract_code=market_file.contract_code,
            period="15m",
            start_time=market_file.start_time,
            end_time=market_file.end_time,
            status=status,
            missing_bars=missing_bars,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            details={
                "check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION,
                "warning_reasons": (
                    ["controlled_missing_bar"] if status == "warning" else []
                ),
            },
        )
    )


def _add_profile_binding(
    session: Session,
    market_file: MarketDataFile | None,
    *,
    profile_id: str = PROFILE_ID,
    data_version: str,
    market_data_file_id: int | None,
) -> None:
    session.add(
        DataProfile(
            profile_id=profile_id,
            label="Task 5 controlled research",
            description="in-memory equivalence fixture",
            contract_roles=["actual_contract"],
            periods=["15m"],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
    )
    session.add(
        ProfileActiveBinding(
            profile_id=profile_id,
            instrument_symbol="jm",
            contract_code="JM2609",
            contract_role="actual_contract",
            period="15m",
            data_version=data_version,
            market_data_file_id=market_data_file_id,
            binding_status="active",
            activated_at=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        )
    )
    if market_file is not None:
        assert market_file.data_version == data_version


def _populated_table_counts(session: Session) -> dict[str, int]:
    connection = session.connection()
    names = [
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    counts: dict[str, int] = {}
    for name in names:
        quoted = name.replace('"', '""')
        count = int(
            connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{quoted}"').scalar_one()
        )
        if count:
            counts[name] = count
    return counts


def _assert_session_clean(session: Session) -> None:
    assert list(session.new) == []
    assert list(session.dirty) == []
    assert list(session.deleted) == []


def _assert_read_state(
    session: Session,
    *,
    baseline_counts: dict[str, int],
    write_statements: list[str],
) -> None:
    assert _populated_table_counts(session) == baseline_counts
    _assert_session_clean(session)
    assert write_statements == []


class _ReadAudit:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.engine = session.get_bind()
        self.baseline_counts = _populated_table_counts(session)
        self.write_statements: list[str] = []

    def __enter__(self) -> _ReadAudit:
        _assert_session_clean(self.session)
        event.listen(
            self.engine,
            "before_cursor_execute",
            self._record_statement,
        )
        return self

    def __exit__(self, *_exc_info: object) -> None:
        event.remove(
            self.engine,
            "before_cursor_execute",
            self._record_statement,
        )

    def assert_unchanged(self) -> None:
        _assert_read_state(
            self.session,
            baseline_counts=self.baseline_counts,
            write_statements=self.write_statements,
        )

    def _record_statement(
        self,
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        keyword = statement.lstrip().split(maxsplit=1)[0].upper()
        if keyword in {
            "ALTER",
            "CREATE",
            "DELETE",
            "DROP",
            "INSERT",
            "REPLACE",
            "UPDATE",
        }:
            self.write_statements.append(statement)


def _assert_full_equivalence(
    session: Session,
    *,
    legacy_kwargs: dict[str, Any],
    request: DatasetRequest,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    tail: bool,
) -> tuple[Any, BarsResult, Any]:
    with _ReadAudit(session) as audit:
        oracle = get_market_bars(session, **legacy_kwargs)
        audit.assert_unchanged()

        service = MarketDataService(session)
        result = service.get_bars(
            request,
            start=start,
            end=end,
            limit=limit,
            tail=tail,
        )
        adapted = service.to_market_bars_response(result)
        audit.assert_unchanged()

    assert adapted.model_dump(mode="json") == oracle.model_dump(mode="json")
    assert result.descriptor.lineage_token == oracle.lineage.lineage_token
    assert [asset.market_data_file_id for asset in result.descriptor.assets] == (
        oracle.lineage.market_data_file_ids
    )
    assert result.descriptor.source_coverage_row_count == sum(
        _market_file_row_counts(
            session,
            oracle.lineage.market_data_file_ids,
        )
    )
    assert result.response_bar_count == len(oracle.bars)
    return oracle, result, adapted


def _market_file_row_counts(session: Session, file_ids: list[int]) -> list[int]:
    return [
        int(market_file.row_count or 0)
        for file_id in file_ids
        if (market_file := session.get(MarketDataFile, file_id)) is not None
    ]


def _legacy_kwargs(
    *,
    contract: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    tail: bool,
    provider: str | None = None,
    data_role: str | None = None,
    profile_id: str | None = None,
    access_mode: str = "browser",
    expected_file_id: int | None = None,
    expected_token: str | None = None,
    quote_mode: bool = False,
    allow_continuous: bool = False,
) -> dict[str, Any]:
    return {
        "symbol": "jm",
        "contract": contract,
        "period": "15m",
        "start": start,
        "end": end,
        "provider": provider,
        "data_role": data_role,
        "limit": limit,
        "quote_mode": quote_mode,
        "allow_continuous": allow_continuous,
        "tail": tail,
        "profile_id": profile_id,
        "access_mode": access_mode,
        "expected_market_data_file_id": expected_file_id,
        "expected_lineage_token": expected_token,
    }


def _request(
    *,
    contract: str,
    provider: str | None = None,
    data_role: str | None = None,
    profile_id: str | None = None,
    access_mode: str = "browser",
    expected_file_id: int | None = None,
    expected_token: str | None = None,
    quote_mode: bool = False,
    allow_continuous: bool = False,
) -> DatasetRequest:
    return DatasetRequest(
        data_context="historical",
        symbol="jm",
        contract_selector="explicit",
        contract=contract,
        period="15m",
        access_mode=access_mode,  # type: ignore[arg-type]
        profile_id=profile_id,
        provider=provider,
        data_role=data_role,
        expected_market_data_file_id=expected_file_id,
        expected_lineage_token=expected_token,
        quote_mode=quote_mode,
        allow_continuous=allow_continuous,
    )


def _assert_same_market_error_read_only(
    session: Session,
    *,
    legacy_kwargs: dict[str, Any],
    request: DatasetRequest,
    start: datetime | None,
    end: datetime | None,
    expected_code: str,
) -> None:
    with _ReadAudit(session) as audit:
        with pytest.raises(MarketAccessError) as legacy_error:
            get_market_bars(session, **legacy_kwargs)
        audit.assert_unchanged()

        with pytest.raises(MarketAccessError) as facade_error:
            MarketDataService(session).get_bars(
                request,
                start=start,
                end=end,
                limit=int(legacy_kwargs["limit"]),
                tail=bool(legacy_kwargs["tail"]),
            )
        audit.assert_unchanged()

    assert legacy_error.value.code == expected_code
    assert facade_error.value.code == expected_code
    assert legacy_error.value.status_code == facade_error.value.status_code == 422


def test_continuous_browser_coverage_derived_request_is_complete_json_equivalent(
    session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "canonical" / "bars" / "rqdata-jm-main-15m.parquet"
    times = _write_bars(
        path,
        contract="jm.MAIN",
        provider="rqdata",
        data_version="continuous-v1",
        closes=[1100, 1101, 1102, 1103],
    )
    market_file = _add_market_file(
        session,
        path,
        contract="jm.MAIN",
        provider="rqdata",
        data_version="continuous-v1",
        quality_status="passed",
        times=times,
        checksum="sha256:continuous",
    )
    session.commit()

    oracle, result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="jm.MAIN",
            start=None,
            end=None,
            provider="rqdata",
            data_role="primary",
            limit=3,
            tail=False,
            quote_mode=True,
            allow_continuous=True,
        ),
        request=_request(
            contract="jm.MAIN",
            provider="rqdata",
            data_role="primary",
            quote_mode=True,
            allow_continuous=True,
        ),
        start=None,
        end=None,
        limit=3,
        tail=False,
    )

    assert oracle.request.start == BAR_START
    assert oracle.request.end == times[-1]
    assert result.descriptor.source_max_bar == times[2]
    assert result.descriptor.source_coverage_row_count == 4
    assert result.response_bar_count == 3
    assert [asset.market_data_file_id for asset in result.descriptor.assets] == [
        market_file.id
    ]
    assert result.descriptor.contract_role == "continuous"
    assert result.descriptor.continuous_contract == "jm.MAIN"
    assert result.descriptor.actual_contract is None


def test_actual_tail_and_expected_identity_are_complete_json_equivalent(
    session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "canonical" / "bars" / "rqdata-jm2609-15m.parquet"
    times = _write_bars(
        path,
        contract="JM2609",
        provider="rqdata",
        data_version="actual-v1",
        closes=[1200, 1201, 1202, 1203, 1204],
    )
    market_file = _add_market_file(
        session,
        path,
        contract="JM2609",
        provider="rqdata",
        data_version="actual-v1",
        quality_status="passed",
        times=times,
        checksum="sha256:actual",
    )
    session.commit()
    start = times[1]
    end = times[-1]

    unpinned, _result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=start,
            end=end,
            provider="rqdata",
            data_role="primary",
            limit=2,
            tail=True,
            quote_mode=True,
        ),
        request=_request(
            contract="JM2609",
            provider="rqdata",
            data_role="primary",
            quote_mode=True,
        ),
        start=start,
        end=end,
        limit=2,
        tail=True,
    )
    oracle, result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=start,
            end=end,
            provider="rqdata",
            data_role="primary",
            limit=2,
            tail=True,
            expected_file_id=market_file.id,
            expected_token=unpinned.lineage.lineage_token,
            quote_mode=True,
        ),
        request=_request(
            contract="JM2609",
            provider="rqdata",
            data_role="primary",
            expected_file_id=market_file.id,
            expected_token=unpinned.lineage.lineage_token,
            quote_mode=True,
        ),
        start=start,
        end=end,
        limit=2,
        tail=True,
    )

    assert [bar["time"] for bar in oracle.bars] == [
        times[-2].isoformat(),
        times[-1].isoformat(),
    ]
    assert result.descriptor.source_max_bar == times[-1]
    assert result.descriptor.source_coverage_row_count == 5
    assert result.response_bar_count == 2
    assert result.response_request["expected_market_data_file_id"] == market_file.id
    assert (
        result.response_request["expected_lineage_token"]
        == unpinned.lineage.lineage_token
    )
    assert result.descriptor.actual_contract == "JM2609"


def test_browser_multi_asset_priority_dedupe_and_order_are_json_equivalent(
    session: Session,
    tmp_path: Path,
) -> None:
    local_path = tmp_path / "canonical" / "bars" / "local-jm2609-15m.parquet"
    rqdata_path = tmp_path / "canonical" / "bars" / "rqdata-jm2609-15m.parquet"
    times = _write_bars(
        local_path,
        contract="JM2609",
        provider="local_parquet",
        data_version="local-v1",
        closes=[2100, 2101, 2102],
    )
    _write_bars(
        rqdata_path,
        contract="JM2609",
        provider="rqdata",
        data_version="rqdata-v1",
        closes=[3100, 3101, 3102],
    )
    local_file = _add_market_file(
        session,
        local_path,
        contract="JM2609",
        provider="local_parquet",
        data_version="local-v1",
        quality_status="passed",
        times=times,
        checksum="sha256:local",
    )
    rqdata_file = _add_market_file(
        session,
        rqdata_path,
        contract="JM2609",
        provider="rqdata",
        data_version="rqdata-v1",
        quality_status="passed",
        times=times,
        checksum="sha256:rqdata",
    )
    session.commit()

    oracle, result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=None,
            end=None,
            limit=10,
            tail=False,
        ),
        request=_request(contract="JM2609"),
        start=None,
        end=None,
        limit=10,
        tail=False,
    )

    assert oracle.lineage.market_data_file_ids == [local_file.id, rqdata_file.id]
    assert [asset.market_data_file_id for asset in result.descriptor.assets] == [
        local_file.id,
        rqdata_file.id,
    ]
    assert [bar["provider"] for bar in oracle.bars] == ["rqdata"] * 3
    assert [bar["close"] for bar in oracle.bars] == [3100.0, 3101.0, 3102.0]
    assert oracle.quality.status == "warning"
    assert oracle.quality.cross_file_conflicts == 3
    assert result.descriptor.source_coverage_row_count == 6
    assert result.descriptor.source_max_bar == times[-1]
    assert result.response_bar_count == 3


def test_pinned_research_profile_quality_and_binding_are_json_equivalent(
    session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "canonical" / "bars" / "research-jm2609-15m.parquet"
    times = _write_bars(
        path,
        contract="JM2609",
        provider="rqdata",
        data_version="research-v1",
        closes=[1300, 1301, 1302, 1303],
        source_interval="1m",
    )
    market_file = _add_market_file(
        session,
        path,
        contract="JM2609",
        provider="rqdata",
        data_version="research-v1",
        quality_status="passed",
        times=times,
        checksum="sha256:research",
    )
    _add_quality_report(session, market_file)
    _add_profile_binding(
        session,
        market_file,
        data_version="research-v1",
        market_data_file_id=market_file.id,
    )
    session.commit()

    unpinned, _result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=times[0],
            end=times[-1],
            provider="rqdata",
            data_role="primary",
            profile_id=PROFILE_ID,
            access_mode="research",
            limit=4,
            tail=False,
        ),
        request=_request(
            contract="JM2609",
            provider="rqdata",
            data_role="primary",
            profile_id=PROFILE_ID,
            access_mode="research",
        ),
        start=times[0],
        end=times[-1],
        limit=4,
        tail=False,
    )
    oracle, result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=times[0],
            end=times[-1],
            provider="rqdata",
            data_role="primary",
            profile_id=PROFILE_ID,
            access_mode="research",
            expected_file_id=market_file.id,
            expected_token=unpinned.lineage.lineage_token,
            limit=4,
            tail=False,
        ),
        request=_request(
            contract="JM2609",
            provider="rqdata",
            data_role="primary",
            profile_id=PROFILE_ID,
            access_mode="research",
            expected_file_id=market_file.id,
            expected_token=unpinned.lineage.lineage_token,
        ),
        start=times[0],
        end=times[-1],
        limit=4,
        tail=False,
    )

    assert oracle.strict_research_ready is True
    assert oracle.quality.report_count == 1
    assert oracle.lineage.profile_id == PROFILE_ID
    assert oracle.lineage.binding_snapshot is not None
    assert oracle.lineage.binding_snapshot["market_data_file_id"] == market_file.id
    assert oracle.lineage.source_interval == "1m"
    assert result.descriptor.strict_research_ready is True
    assert result.descriptor.binding_snapshot == oracle.lineage.binding_snapshot
    assert result.descriptor.lineage_token == unpinned.lineage.lineage_token


def test_single_candidate_idless_profile_fallback_is_json_equivalent(
    session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "canonical" / "bars" / "idless-jm2609-15m.parquet"
    times = _write_bars(
        path,
        contract="JM2609",
        provider="rqdata",
        data_version="idless-v1",
        closes=[1400, 1401, 1402],
        source_interval="1m",
    )
    market_file = _add_market_file(
        session,
        path,
        contract="JM2609",
        provider="rqdata",
        data_version="idless-v1",
        quality_status="passed",
        times=times,
        checksum="sha256:idless",
    )
    _add_quality_report(session, market_file)
    _add_profile_binding(
        session,
        market_file,
        data_version="idless-v1",
        market_data_file_id=None,
    )
    session.commit()

    oracle, result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=None,
            end=None,
            profile_id=PROFILE_ID,
            access_mode="research",
            limit=3,
            tail=False,
        ),
        request=_request(
            contract="JM2609",
            profile_id=PROFILE_ID,
            access_mode="research",
        ),
        start=None,
        end=None,
        limit=3,
        tail=False,
    )

    assert oracle.lineage.binding_snapshot is not None
    assert oracle.lineage.binding_snapshot["market_data_file_id"] is None
    assert oracle.lineage.market_data_file_id == market_file.id
    assert result.descriptor.assets[0].market_data_file_id == market_file.id
    assert result.descriptor.source_coverage_row_count == 3
    assert result.response_bar_count == 3


@pytest.mark.parametrize("quality_status", ["warning", "unchecked"])
def test_nonfailed_browser_quality_visibility_is_json_equivalent(
    session: Session,
    tmp_path: Path,
    quality_status: str,
) -> None:
    path = tmp_path / "canonical" / "bars" / f"{quality_status}-jm2609-15m.parquet"
    times = _write_bars(
        path,
        contract="JM2609",
        provider="rqdata",
        data_version=f"{quality_status}-v1",
        closes=[1500, 1501],
    )
    _add_market_file(
        session,
        path,
        contract="JM2609",
        provider="rqdata",
        data_version=f"{quality_status}-v1",
        quality_status=quality_status,
        times=times,
        checksum=f"sha256:{quality_status}",
    )
    session.commit()

    oracle, result, _adapted = _assert_full_equivalence(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=None,
            end=None,
            limit=2,
            tail=False,
        ),
        request=_request(contract="JM2609"),
        start=None,
        end=None,
        limit=2,
        tail=False,
    )

    assert oracle.quality.status == quality_status
    assert oracle.strict_research_ready is False
    assert result.descriptor.quality_status == quality_status
    assert result.descriptor.strict_research_ready is False


def test_ambiguous_rank1_mapping_fails_closed_without_read_or_write(
    session: Session,
) -> None:
    mapping_date = date(2026, 7, 30)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=mapping_date,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-a",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=mapping_date,
                rank=1,
                contract_code="JM2610",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-b",
            ),
        ]
    )
    session.commit()

    with _ReadAudit(session) as audit:
        with pytest.raises(ValueError, match="^ACTUAL_CONTRACT_MAPPING_CONFLICT$"):
            MarketDataService(session).get_bars(
                DatasetRequest(
                    data_context="historical",
                    symbol="jm",
                    contract_selector="dominant_rank1",
                    contract=None,
                    period="15m",
                    access_mode="browser",
                    mapping_date=mapping_date,
                ),
                start=None,
                end=None,
                limit=10,
                tail=False,
            )
        audit.assert_unchanged()


@pytest.mark.parametrize("candidate_count", [0, 2])
def test_idless_profile_zero_or_multiple_candidates_fails_closed(
    session: Session,
    tmp_path: Path,
    candidate_count: int,
) -> None:
    files: list[MarketDataFile] = []
    for index in range(candidate_count):
        provider = ("rqdata", "local_parquet")[index]
        path = tmp_path / "canonical" / "bars" / f"idless-{provider}-jm2609-15m.parquet"
        times = _write_bars(
            path,
            contract="JM2609",
            provider=provider,
            data_version="idless-candidate-v1",
            closes=[1600, 1601],
            source_interval="1m",
        )
        files.append(
            _add_market_file(
                session,
                path,
                contract="JM2609",
                provider=provider,
                data_version="idless-candidate-v1",
                quality_status="passed",
                times=times,
                checksum=f"sha256:{provider}:candidate",
            )
        )
    _add_profile_binding(
        session,
        files[0] if files else None,
        data_version="idless-candidate-v1",
        market_data_file_id=None,
    )
    session.commit()

    with _ReadAudit(session) as audit:
        if candidate_count == 0:
            with pytest.raises(MarketAccessError) as missing:
                MarketDataService(session).get_bars(
                    _request(
                        contract="JM2609",
                        profile_id=PROFILE_ID,
                        access_mode="research",
                    ),
                    start=None,
                    end=None,
                    limit=10,
                    tail=False,
                )
            assert missing.value.code == "MARKET_PROFILE_FILE_MISSING"
            assert missing.value.status_code == 422
        else:
            with pytest.raises(ActiveDatasetDomainError) as ambiguous:
                MarketDataService(session).get_bars(
                    _request(
                        contract="JM2609",
                        profile_id=PROFILE_ID,
                        access_mode="research",
                    ),
                    start=None,
                    end=None,
                    limit=10,
                    tail=False,
                )
            assert ambiguous.value.code == "DATASET_ASSET_AMBIGUOUS"
        audit.assert_unchanged()


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing_profile", "MARKET_PROFILE_NOT_FOUND"),
        ("missing_binding", "MARKET_PROFILE_BINDING_MISSING"),
        ("missing_market_file", "MARKET_PROFILE_FILE_MISSING"),
        ("missing_physical_file", "MARKET_PROFILE_FILE_MISSING"),
        ("uncovered_range", "MARKET_PROFILE_RANGE_NOT_COVERED"),
    ],
)
def test_profile_failure_http_contract_is_stable_and_read_only(
    session: Session,
    tmp_path: Path,
    case: str,
    expected_code: str,
) -> None:
    start: datetime | None = None
    end: datetime | None = None
    if case == "missing_binding":
        session.add(
            DataProfile(
                profile_id=PROFILE_ID,
                label="Task 5 missing binding",
                description="in-memory equivalence fixture",
                contract_roles=["actual_contract"],
                periods=["15m"],
                quality_policy="passed_only",
                provider="rqdata",
                is_active=True,
            )
        )
    elif case == "missing_market_file":
        _add_profile_binding(
            session,
            None,
            data_version="missing-v1",
            market_data_file_id=987654,
        )
    elif case == "missing_physical_file":
        times = [BAR_START, BAR_START + timedelta(minutes=15)]
        market_file = _add_market_file(
            session,
            tmp_path / "canonical" / "bars" / "not-created.parquet",
            contract="JM2609",
            provider="rqdata",
            data_version="physical-missing-v1",
            quality_status="passed",
            times=times,
            checksum="sha256:missing-physical",
        )
        _add_profile_binding(
            session,
            market_file,
            data_version="physical-missing-v1",
            market_data_file_id=market_file.id,
        )
    elif case == "uncovered_range":
        path = tmp_path / "canonical" / "bars" / "uncovered-jm2609-15m.parquet"
        times = _write_bars(
            path,
            contract="JM2609",
            provider="rqdata",
            data_version="uncovered-v1",
            closes=[1700, 1701],
            source_interval="1m",
        )
        market_file = _add_market_file(
            session,
            path,
            contract="JM2609",
            provider="rqdata",
            data_version="uncovered-v1",
            quality_status="passed",
            times=times,
            checksum="sha256:uncovered",
        )
        _add_profile_binding(
            session,
            market_file,
            data_version="uncovered-v1",
            market_data_file_id=market_file.id,
        )
        start = times[0] - timedelta(minutes=15)
        end = times[-1]
    session.commit()

    _assert_same_market_error_read_only(
        session,
        legacy_kwargs=_legacy_kwargs(
            contract="JM2609",
            start=start,
            end=end,
            profile_id=PROFILE_ID,
            access_mode="research",
            limit=10,
            tail=False,
        ),
        request=_request(
            contract="JM2609",
            profile_id=PROFILE_ID,
            access_mode="research",
        ),
        start=start,
        end=end,
        expected_code=expected_code,
    )
