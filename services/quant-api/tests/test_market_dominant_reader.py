from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.catalog import HistoricalCatalog, PartitionManifest
from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.db.base import Base
from app.models.data_center import Exchange, Instrument, MainContractMap
from app.models import data_core as _data_core_models  # noqa: F401
from app.services.market_dominant_reader import (
    DominantContractReader,
    QuoteContractError,
    validate_quote_contract,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _register_actual_coverage(
    session: Session,
    *,
    symbol: str,
    contract: str,
    frequency: BarFrequency = BarFrequency.M15,
    start: datetime | None = None,
    end: datetime | None = None,
    row_count: int = 100,
) -> None:
    catalog = HistoricalCatalog(session)
    catalog.register_partition(
        DatasetKey(
            provider="rqdata",
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol=symbol,
            contract_or_series=contract,
            frequency=frequency,
            adjustment="none",
            schema_version="v1",
        ),
        PartitionManifest(
            coverage_start=start or datetime(2026, 4, 1, 9, 15, tzinfo=UTC),
            coverage_end=end or datetime(2026, 7, 7, 15, 0, tzinfo=UTC),
            manifest_version="manifest-v1",
            manifest_uri=f"manifests/{symbol}_{contract}_{frequency.value}.json",
            manifest_digest="a" * 64,
            file_uri=f"bars/{symbol}_{contract}_{frequency.value}.parquet",
            checksum="b" * 64,
            row_count=row_count,
        ),
    )


def _seed(session: Session) -> None:
    session.add(Exchange(code="DCE", name="大连商品交易所", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Exchange(code="SHFE", name="上海期货交易所", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤指数连续", exchange_code="DCE", sector="black", category="future", is_active=True))
    session.add(Instrument(symbol="rb", name="螺纹钢", exchange_code="SHFE", sector="black", category="future", is_active=True))
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 6),
                rank=1,
                contract_code="JM2605",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-v1",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 7),
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-v2",
            ),
            MainContractMap(
                instrument_symbol="rb",
                trade_date=date(2026, 7, 7),
                rank=1,
                contract_code="RB2510",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-rb",
            ),
        ]
    )
    session.flush()
    _register_actual_coverage(session, symbol="jm", contract="JM2609")
    session.commit()


def test_validate_quote_contract_rejects_main() -> None:
    try:
        validate_quote_contract("jm.MAIN")
        raise AssertionError("expected QuoteContractError")
    except QuoteContractError as exc:
        assert "actual_contract" in str(exc)


def test_list_dominants_uses_latest_mapping_and_coverage() -> None:
    factory = _session_factory()
    with factory() as session:
        _seed(session)
        response = DominantContractReader(session).list_dominants()
        assert response.default_quote_period == "15m"
        assert len(response.items) == 2

        jm = next(item for item in response.items if item.product == "jm")
        assert jm.actual_contract == "JM2609"
        assert jm.dominant_mapping_date == date(2026, 7, 7)
        assert jm.continuous_contract == "jm.MAIN"
        assert jm.quote_ready is True
        assert jm.bars_coverage["15m"].row_count == 100
        assert jm.bars_coverage["15m"].quality_status == "passed"
        assert jm.sector == "black"
        assert jm.category == "future"
        assert jm.is_active is True
        assert jm.product_name == "焦煤"

        rb = next(item for item in response.items if item.product == "rb")
        assert rb.actual_contract == "RB2510"
        assert rb.quote_ready is False


def test_list_dominants_ignores_legacy_market_data_file_coverage() -> None:
    """Legacy MarketDataFile must not make quote_ready true without Catalog partitions."""
    from app.models.data_center import MarketDataFile

    factory = _session_factory()
    with factory() as session:
        session.add(Exchange(code="DCE", name="大连商品交易所", country="CN", timezone="Asia/Shanghai", is_active=True))
        session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2025, 8, 1),
                rank=1,
                contract_code="JM2509",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-stale",
            )
        )
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2509",
                period="15m",
                start_time=datetime(2025, 7, 22, 9, 15, tzinfo=UTC),
                end_time=datetime(2025, 8, 3, 15, 0, tzinfo=UTC),
                file_path="/tmp/jm2509_15m.parquet",
                row_count=100,
                data_version="jm2509_legacy",
                data_role="primary",
                quality_status="passed",
            )
        )
        session.commit()

        response = DominantContractReader(session).list_dominants()
        jm = next(item for item in response.items if item.product == "jm")
        assert jm.actual_contract == "JM2509"
        assert jm.quote_ready is False
        assert jm.bars_coverage == {}


def test_list_dominants_filters_quote_ready_and_search() -> None:
    factory = _session_factory()
    with factory() as session:
        _seed(session)
        ready = DominantContractReader(session).list_dominants(quote_ready=True)
        assert [item.product for item in ready.items] == ["jm"]

        search = DominantContractReader(session).list_dominants(search="螺纹")
        assert len(search.items) == 1
        assert search.items[0].product == "rb"


def test_list_dominants_dedupes_case_insensitive_product_keys() -> None:
    factory = _session_factory()
    with factory() as session:
        session.add(Exchange(code="CZCE", name="郑州商品交易所", country="CN", timezone="Asia/Shanghai", is_active=True))
        session.add(Instrument(symbol="ap", name="苹果", exchange_code="CZCE", sector="agri", category="future", is_active=True))
        session.add_all(
            [
                MainContractMap(
                    instrument_symbol="ap",
                    trade_date=date(2026, 7, 7),
                    rank=1,
                    contract_code="AP2610",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="map-ap-lower",
                ),
                MainContractMap(
                    instrument_symbol="AP",
                    trade_date=date(2026, 7, 7),
                    rank=1,
                    contract_code="AP2610",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="map-ap-upper",
                ),
            ]
        )
        session.commit()

        response = DominantContractReader(session).list_dominants()
        ap_items = [item for item in response.items if item.product == "ap"]
        assert len(ap_items) == 1
        assert ap_items[0].actual_contract == "AP2610"
        assert ap_items[0].sector == "agri"


def test_list_dominants_skips_synthetic_mapping_and_uses_previous_actual_contract() -> None:
    factory = _session_factory()
    with factory() as session:
        session.add(Exchange(code="DCE", name="大连商品交易所", country="CN", timezone="Asia/Shanghai", is_active=True))
        session.add(Instrument(symbol="a", name="豆一", exchange_code="DCE", is_active=True))
        session.add_all(
            [
                MainContractMap(
                    instrument_symbol="a",
                    trade_date=date(2026, 7, 6),
                    rank=1,
                    contract_code="A2605",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="map-a-old",
                ),
                MainContractMap(
                    instrument_symbol="a",
                    trade_date=date(2026, 7, 7),
                    rank=1,
                    contract_code="A8888",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="map-a-bad",
                ),
            ]
        )
        session.commit()

        response = DominantContractReader(session).list_dominants()
        item = next(row for row in response.items if row.product == "a")
        assert item.actual_contract == "A2605"
        assert item.dominant_mapping_date == date(2026, 7, 6)
