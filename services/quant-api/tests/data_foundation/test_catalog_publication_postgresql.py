"""Real PostgreSQL visibility checks; only an explicitly isolated target is allowed."""

from __future__ import annotations

import os
import multiprocessing
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey, SeriesQuery
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import MarketDataset, MarketPartition


pytestmark = pytest.mark.isolated_postgresql


@pytest.fixture
def isolated_postgresql():
    # Never load application configuration, .env, or probe DATABASE_URL.
    target = os.environ.get("GUIYI_ISOLATED_PUBLICATION_DATABASE_URL", "")
    if not target:
        pytest.skip("GUIYI_ISOLATED_PUBLICATION_DATABASE_URL is required")
    url = make_url(target)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert url.database == "guiyi_canonical_isolated_test"
    assert url.port and url.port != 5432
    schema = "publication_test_" + uuid4().hex
    engine = create_engine(url, isolation_level="READ COMMITTED")
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_database()")) == url.database
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        MarketDataset.__table__.create(scoped)
        MarketPartition.__table__.create(scoped)
        yield scoped
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _bar(day: int, close: int) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        datetime(2025, 1, day, 7, tzinfo=UTC), date(2025, 1, day),
        value, value, value, value, Decimal(1), Decimal(10), Decimal(20),
    )


def _query(session, root):
    return MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root)).query(
        SeriesQuery("continuous", "jm", "1d",
                    datetime(2025, 1, 1, 7, tzinfo=UTC),
                    datetime(2025, 1, 2, 7, tzinfo=UTC))
    ).bars


@pytest.mark.parametrize("commit", [False, True], ids=["rollback", "commit"])
def test_postgresql_pointer_visibility_and_retained_reader(
    isolated_postgresql, tmp_path, commit,
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    store = CanonicalMonthlyStore(tmp_path)
    old_bars = (_bar(2, 100),)
    new_bars = (_bar(2, 200), _bar(3, 210))

    def publish(bars):
        return store.publish(PublishRequest(
            key, 2025, 1, bars, tuple(bar.bar_end for bar in bars),
        ))

    old = publish(old_bars)
    with Session(isolated_postgresql) as seed:
        MarketCatalog(seed, tmp_path).register_partition(old)
        seed.commit()

    with Session(isolated_postgresql) as reader, Session(isolated_postgresql) as writer:
        reader_catalog = MarketCatalog(reader, tmp_path)
        retained = reader_catalog.all_partitions(key)[0]
        original_bytes = retained.file_path.read_bytes()
        new = publish(new_bars)
        assert new.parquet_path != retained.file_path
        MarketCatalog(writer, tmp_path).register_partition(new)
        # register_partition flushes SQL; another connection must still see old facts.
        pending = reader_catalog.all_partitions(key)[0]
        assert pending == retained
        assert store.read_catalog_partition(pending) == old_bars
        assert _query(reader, tmp_path) == old_bars
        if commit:
            writer.commit()
        else:
            writer.rollback()
        reader.expire_all()
        visible = reader_catalog.all_partitions(key)[0]
        assert visible.file_path == (new.parquet_path if commit else old.parquet_path)
        assert visible.row_count == (len(new_bars) if commit else len(old_bars))
        assert visible.coverage_end == (new.coverage_end if commit else old.coverage_end)
        assert store.read_catalog_partition(visible) == (new_bars if commit else old_bars)
        assert _query(reader, tmp_path) == (new_bars[:1] if commit else old_bars)
        # A consumer that resolved before commit remains valid after either outcome.
        assert retained.file_path.read_bytes() == original_bytes
        assert store.read_catalog_partition(retained) == old_bars


def _crash_publisher(target, schema, root, commit):
    """Abrupt exit leaves no context-manager rollback or application cleanup."""
    engine = create_engine(target).execution_options(schema_translate_map={None: schema})
    session = Session(engine)
    bars = (_bar(2, 200),)
    partition = CanonicalMonthlyStore(root).publish(PublishRequest(
        DatasetKey("continuous", "jm", "MAIN", "1d"), 2025, 1,
        bars, tuple(bar.bar_end for bar in bars),
    ))
    MarketCatalog(session, root).register_partition(partition)
    if commit:
        session.commit()
    os._exit(73)


@pytest.mark.parametrize("commit", [False, True], ids=["before_commit", "after_commit"])
@pytest.mark.parametrize("existing", [False, True], ids=["first_partition", "replacement"])
def test_postgresql_process_crash_has_only_committed_mds_visibility(
    isolated_postgresql, tmp_path, commit, existing,
) -> None:
    key = DatasetKey("continuous", "jm", "MAIN", "1d")
    retained = None
    if existing:
        bars = (_bar(2, 100),)
        partition = CanonicalMonthlyStore(tmp_path).publish(PublishRequest(
            key, 2025, 1, bars, tuple(bar.bar_end for bar in bars),
        ))
        with Session(isolated_postgresql) as seed:
            catalog = MarketCatalog(seed, tmp_path)
            catalog.register_partition(partition)
            seed.commit()
            retained = catalog.all_partitions(key)[0]

    schema = isolated_postgresql.get_execution_options()["schema_translate_map"][None]
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_publisher,
        args=(os.environ["GUIYI_ISOLATED_PUBLICATION_DATABASE_URL"], schema, tmp_path, commit),
    )
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        pytest.fail("isolated publication child did not reach its crash boundary")
    assert process.exitcode == 73
    with Session(isolated_postgresql) as reader:
        if not existing and not commit:
            assert MarketCatalog(reader, tmp_path).all_partitions(key) == ()
            with pytest.raises(MarketDataError, match="DATASET_OR_PARTITION_MISSING"):
                _query(reader, tmp_path)
        else:
            assert _query(reader, tmp_path) == (_bar(2, 200 if commit else 100),)
    if retained is not None:
        assert CanonicalMonthlyStore(tmp_path).read_catalog_partition(retained) == (_bar(2, 100),)
