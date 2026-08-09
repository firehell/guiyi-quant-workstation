from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.product_retirement import (
    ProductRetiredError,
    apply_retirement,
    assert_not_retired,
    inventory_retirement,
    is_retired,
    load_retired_products,
    plan_retirement,
)
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    MarketDataset,
    MarketPartition,
    TradingSession,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def test_retired_products_file_is_exact_five_and_disjoint_from_active() -> None:
    retired = load_retired_products()
    assert retired == frozenset({"br", "cs", "ic", "if", "ih", "im", "lu", "nr", "sp"})
    from app.core.env import PROJECT_ROOT

    active = {
        line.strip().lower()
        for line in (PROJECT_ROOT / "data/universe/active_products.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    }
    assert len(active) == 60
    assert retired.isdisjoint(active)


def test_assert_not_retired_exact_match_only() -> None:
    retired = frozenset({"br", "cs", "ic", "if", "ih", "im", "lu", "nr", "sp"})
    assert_not_retired("jm", retired=retired)
    assert not is_retired("jm", retired=retired)
    with pytest.raises(ProductRetiredError) as exc:
        assert_not_retired("BR", retired=retired)
    assert exc.value.code == "PRODUCT_RETIRED"


def _seed_retired_rows(session: Session, tmp_path: Path) -> Path:
    session.add(Exchange(code="CFFEX", name="CFFEX"))
    session.add(Exchange(code="INE", name="INE"))
    session.add(Instrument(symbol="ic", name="IC", exchange_code="CFFEX", is_active=True))
    session.add(Instrument(symbol="jm", name="JM", exchange_code="INE", is_active=True))
    session.add(
        Contract(
            contract_code="IC2509",
            instrument_symbol="ic",
            exchange_code="CFFEX",
        )
    )
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="INE",
        )
    )
    session.add(
        TradingSession(
            exchange_code="CFFEX",
            instrument_symbol="ic",
            session_name="day",
            start_time=time(9, 0),
            end_time=time(15, 0),
            effective_from=date(2024, 1, 1),
        )
    )
    session.add(
        MainContractMap(
            symbol="ic",
            trade_date=date(2025, 1, 2),
            contract_code="IC2509",
        )
    )
    session.add(
        MainContractMap(
            symbol="jm",
            trade_date=date(2025, 1, 2),
            contract_code="JM2509",
        )
    )
    dataset = MarketDataset(
        kind="continuous",
        symbol="ic",
        series_or_contract="MAIN",
        frequency="1d",
    )
    session.add(dataset)
    session.flush()
    session.add(
        MarketPartition(
            dataset_id=dataset.id,
            year=2025,
            month=1,
            coverage_start=datetime(2025, 1, 1, tzinfo=UTC),
            coverage_end=datetime(2025, 1, 31, tzinfo=UTC),
            file_uri="kind=continuous/symbol=ic/series_or_contract=MAIN/frequency=1d/year=2025/month=01/part.parquet",
            row_count=1,
        )
    )
    session.commit()

    parquet = (
        tmp_path
        / "kind=continuous"
        / "symbol=ic"
        / "series_or_contract=MAIN"
        / "frequency=1d"
        / "year=2025"
        / "month=01"
        / "part.parquet"
    )
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"fake")
    keep = (
        tmp_path
        / "kind=continuous"
        / "symbol=jm"
        / "series_or_contract=MAIN"
        / "frequency=1d"
        / "year=2025"
        / "month=01"
        / "part.parquet"
    )
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"keep")
    return tmp_path


def test_retire_products_dry_run_does_not_mutate(session, tmp_path) -> None:
    root = _seed_retired_rows(session, tmp_path)
    planned = plan_retirement(session, root, products=frozenset({"ic"}))
    assert planned.status == "planned"
    assert planned.inventory.instruments == 1
    assert planned.inventory.canonical_path_count == 1
    assert session.scalar(select(func.count()).select_from(Instrument).where(Instrument.symbol == "ic")) == 1
    assert (root / "kind=continuous" / "symbol=ic").exists()


def test_retire_products_apply_reaches_residual_zero(session, tmp_path) -> None:
    root = _seed_retired_rows(session, tmp_path)
    result = apply_retirement(session, root, products=frozenset({"ic"}))
    assert result.status == "ok"
    assert result.residual.total == 0
    assert session.scalar(select(func.count()).select_from(Instrument).where(Instrument.symbol == "ic")) == 0
    assert session.scalar(select(func.count()).select_from(Instrument).where(Instrument.symbol == "jm")) == 1
    assert session.scalar(select(func.count()).select_from(MainContractMap).where(MainContractMap.symbol == "jm")) == 1
    assert not (root / "kind=continuous" / "symbol=ic").exists()
    assert (root / "kind=continuous" / "symbol=jm" / "series_or_contract=MAIN" / "frequency=1d" / "year=2025" / "month=01" / "part.parquet").exists()
    leftover = inventory_retirement(session, root, products=frozenset({"ic"}))
    assert leftover.total == 0
