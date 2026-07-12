from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    DataQualityReport,
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    MarketDataFile,
)
from app.services.rqdata_ingest.reference_metadata_gap_apply import (
    ReferenceMetadataApplyConfirmationError,
    run_reference_metadata_gap_apply,
)


class FakeReferenceMetadataClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, date, date, str | None]] = []

    def trading_dates(self, start_date: date, end_date: date) -> list[date]:
        self.calls.append(("trading_dates", "", start_date, end_date, None))
        return [date(2024, 1, 2), date(2024, 1, 3)]

    def listed_contracts(self, product: str, trade_date: date) -> pd.DataFrame:
        self.calls.append(("listed_contracts", product, trade_date, trade_date, None))
        return pd.DataFrame([{"contract": f"{product.upper()}2405"}, {"contract": f"{product.upper()}2410"}])

    def continuous_contract_by_type(self, product: str, start_date: date, end_date: date, continuous_type: str) -> pd.DataFrame:
        self.calls.append(("continuous_contract_by_type", product, start_date, end_date, continuous_type))
        contract = f"{product.upper()}2405" if continuous_type == "front_month" else f"{product.upper()}2410"
        return pd.DataFrame(
            [
                {"date": date(2024, 1, 2), "contract": contract},
                {"date": date(2024, 1, 3), "contract": contract},
            ]
        )


class EmptyContinuousClient(FakeReferenceMetadataClient):
    def continuous_contract_by_type(self, product: str, start_date: date, end_date: date, continuous_type: str) -> pd.DataFrame:
        self.calls.append(("continuous_contract_by_type", product, start_date, end_date, continuous_type))
        return pd.DataFrame()


@contextmanager
def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _candidates(path: Path) -> Path:
    candidate_path = path / "apply_candidate_rows.csv"
    pd.DataFrame(
        [
            {
                "classification": "needs_contract_universe_sync",
                "dataset": "contract_universe",
                "target_table": "futures_contract_universe",
                "product": "rb",
                "year": 2024,
                "candidate_start_date": "2024-01-01",
                "candidate_end_date": "2024-01-03",
                "db_row_count_for_year": "0",
                "apply_unit": "product_year",
                "apply_order": "12024",
                "human_gate": "required_before_rqdata_or_db_write",
            },
            {
                "classification": "needs_continuous_contract_sync",
                "dataset": "continuous_contract_map",
                "target_table": "futures_continuous_contract_map",
                "product": "rb",
                "year": 2024,
                "candidate_start_date": "2024-01-01",
                "candidate_end_date": "2024-01-03",
                "db_row_count_for_year": "0",
                "apply_unit": "product_year",
                "apply_order": "22024",
                "human_gate": "required_before_rqdata_or_db_write",
            },
        ]
    ).to_csv(candidate_path, index=False)
    return candidate_path


def test_reference_metadata_gap_apply_dry_run_does_not_call_rqdata_or_write_db(tmp_path: Path) -> None:
    client = FakeReferenceMetadataClient()
    with _session() as session:
        result = run_reference_metadata_gap_apply(
            session=session,
            client=client,
            candidate_rows_csv=_candidates(tmp_path),
            output_dir=tmp_path / "out",
            apply=False,
            confirm_metadata_only=False,
        )

        assert result["apply"] is False
        assert result["candidate_count"] == 2
        assert result["status_counts"] == {"planned": 2}
        assert client.calls == []
        assert session.scalar(select(func.count()).select_from(FuturesContractUniverse)) == 0
        assert session.scalar(select(func.count()).select_from(FuturesContinuousContractMap)) == 0
        assert Path(result["ledger_path"]).exists()


def test_reference_metadata_gap_apply_requires_explicit_confirmation(tmp_path: Path) -> None:
    with _session() as session:
        with pytest.raises(ReferenceMetadataApplyConfirmationError):
            run_reference_metadata_gap_apply(
                session=session,
                client=FakeReferenceMetadataClient(),
                candidate_rows_csv=_candidates(tmp_path),
                output_dir=tmp_path / "out",
                apply=True,
                confirm_metadata_only=False,
            )


def test_reference_metadata_gap_apply_writes_only_reference_tables(tmp_path: Path) -> None:
    with _session() as session:
        result = run_reference_metadata_gap_apply(
            session=session,
            client=FakeReferenceMetadataClient(),
            candidate_rows_csv=_candidates(tmp_path),
            output_dir=tmp_path / "out",
            apply=True,
            confirm_metadata_only=True,
        )

        assert result["status_counts"] == {"success": 2}
        assert session.scalar(select(func.count()).select_from(FuturesContractUniverse)) == 4
        assert session.scalar(select(func.count()).select_from(FuturesContinuousContractMap)) == 4
        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 0
        assert session.scalar(select(func.count()).select_from(DataQualityReport)) == 0

        ledger = pd.read_csv(result["ledger_path"])
        assert set(ledger["target_table"]) == {"futures_contract_universe", "futures_continuous_contract_map"}
        assert set(ledger["writes_market_data_files"]) == {False}
        assert set(ledger["writes_quality_status"]) == {False}
        assert set(ledger["writes_parquet"]) == {False}


def test_reference_metadata_gap_apply_marks_zero_row_continuous_apply_as_no_data(tmp_path: Path) -> None:
    with _session() as session:
        result = run_reference_metadata_gap_apply(
            session=session,
            client=EmptyContinuousClient(),
            candidate_rows_csv=_candidates(tmp_path),
            output_dir=tmp_path / "out",
            apply=True,
            confirm_metadata_only=True,
            dataset="continuous_contract_map",
        )

        assert result["status_counts"] == {"no_data": 1}
        assert session.scalar(select(func.count()).select_from(FuturesContinuousContractMap)) == 0
        ledger = pd.read_csv(result["ledger_path"])
        assert ledger.loc[0, "error_type"] == "NoRowsFetched"
        assert "continuous_contract_map" in ledger.loc[0, "error_message"]


def test_reference_metadata_gap_apply_derives_continuous_map_from_contract_universe(tmp_path: Path) -> None:
    client = EmptyContinuousClient()
    with _session() as session:
        for trade_date in (date(2024, 1, 2), date(2024, 1, 3)):
            session.add(
                FuturesContractUniverse(
                    instrument_symbol="rb",
                    trade_date=trade_date,
                    contract_code="RB2405",
                    sort_order=0,
                    provider="rqdata",
                    data_version="rqdata_structured_v1",
                    raw_payload={"source": "test"},
                )
            )
            session.add(
                FuturesContractUniverse(
                    instrument_symbol="rb",
                    trade_date=trade_date,
                    contract_code="RB2410",
                    sort_order=1,
                    provider="rqdata",
                    data_version="rqdata_structured_v1",
                    raw_payload={"source": "test"},
                )
            )
        session.commit()

        result = run_reference_metadata_gap_apply(
            session=session,
            client=client,
            candidate_rows_csv=_candidates(tmp_path),
            output_dir=tmp_path / "out",
            apply=True,
            confirm_metadata_only=True,
            dataset="continuous_contract_map",
            derive_continuous_from_universe=True,
        )

        assert result["status_counts"] == {"success": 1}
        assert client.calls == []
        rows = session.scalars(
            select(FuturesContinuousContractMap).order_by(
                FuturesContinuousContractMap.trade_date,
                FuturesContinuousContractMap.continuous_type,
            )
        ).all()
        assert [(row.trade_date, row.continuous_type, row.contract_code, row.data_version) for row in rows] == [
            (date(2024, 1, 2), "front_month", "RB2405", "rqdata_contract_universe_derived_v1"),
            (date(2024, 1, 2), "next_month", "RB2410", "rqdata_contract_universe_derived_v1"),
            (date(2024, 1, 3), "front_month", "RB2405", "rqdata_contract_universe_derived_v1"),
            (date(2024, 1, 3), "next_month", "RB2410", "rqdata_contract_universe_derived_v1"),
        ]
        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 0
        assert session.scalar(select(func.count()).select_from(DataQualityReport)) == 0
