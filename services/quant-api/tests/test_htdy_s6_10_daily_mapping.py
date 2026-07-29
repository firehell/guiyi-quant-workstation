from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MainContractMap


APPROVAL_D_HASH = "d" * 64
APPROVAL_C2_PARENT_HASH = "c" * 64
TRADING_DAY = date(2026, 7, 30)


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class DominantClient:
    def __init__(self, contract: str = "JM2609") -> None:
        self.contract = contract
        self.calls: list[tuple[str, date, date, int]] = []

    def dominant_contracts(
        self,
        product: str,
        start_date: date,
        end_date: date,
        rank: int,
    ) -> pd.DataFrame:
        self.calls.append((product, start_date, end_date, rank))
        return pd.DataFrame(
            [{"date": start_date.isoformat(), "dominant": self.contract}]
        )


def test_s610_daily_mapping_materializes_exact_rqdata_row_without_committing() -> None:
    from app.services.htdy_s6_10_daily_mapping import (
        resolve_or_create_s610_daily_mapping,
    )

    factory = _session_factory()
    client = DominantClient()
    with factory() as session:
        result = resolve_or_create_s610_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            approval_d_hash=APPROVAL_D_HASH,
            client=client,
            now=datetime(2026, 7, 29, 10, tzinfo=UTC),
        )
        row = session.scalar(select(MainContractMap))

        assert result.status == "created"
        assert result.actual_contract == "JM2609"
        assert row is not None
        assert row.data_version == (
            "htdy_s610_20260730_dddddddddddd_v1"
        )
        assert result.receipt["mapping_id_independent"] is True
        assert "mapping_id" not in result.receipt
        assert result.receipt["receipt_hash"]
        assert client.calls == [
            ("jm", TRADING_DAY, TRADING_DAY, 1)
        ]
        session.rollback()

    with factory() as session:
        assert session.scalar(select(MainContractMap)) is None


def test_s610_daily_mapping_accepts_same_contract_version_supersession() -> None:
    from app.services.htdy_s6_10_daily_mapping import (
        resolve_or_create_s610_daily_mapping,
    )

    factory = _session_factory()
    with factory() as session:
        session.add_all(
            [
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=TRADING_DAY,
                    rank=1,
                    contract_code="JM2609",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="rqdata_structured_v1",
                    created_at=datetime(2026, 7, 29, 8, tzinfo=UTC),
                ),
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=TRADING_DAY,
                    rank=1,
                    contract_code=" jm2609 ",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="s607_reference_v1",
                    created_at=datetime(2026, 7, 29, 9, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

        result = resolve_or_create_s610_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            approval_d_hash=APPROVAL_D_HASH,
            client=DominantClient(),
            now=datetime(2026, 7, 29, 10, tzinfo=UTC),
        )

        assert result.status == "existing_verified"
        assert result.actual_contract == "JM2609"
        assert (
            result.receipt["mapping_identity"]["data_version"]
            == "s607_reference_v1"
        )
        assert session.query(MainContractMap).count() == 2


def test_s610_daily_mapping_rejects_database_or_rqdata_contract_drift() -> None:
    from app.services.htdy_s6_10_daily_mapping import (
        HtDyS610DailyMappingError,
        resolve_or_create_s610_daily_mapping,
    )

    factory = _session_factory()
    with factory() as session:
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=TRADING_DAY,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="existing_v1",
            )
        )
        session.commit()

        with pytest.raises(
            HtDyS610DailyMappingError,
            match="s610_daily_mapping_rqdata_drift",
        ):
            resolve_or_create_s610_daily_mapping(
                session,
                trading_day=TRADING_DAY,
                approval_d_hash=APPROVAL_D_HASH,
                client=DominantClient("JM2509"),
                now=datetime(2026, 7, 29, 10, tzinfo=UTC),
            )


def test_s610_daily_mapping_receipt_rebinds_without_database_sequence_id() -> None:
    from app.services.htdy_s6_10_daily_mapping import (
        HtDyS610DailyMappingError,
        resolve_or_create_s610_daily_mapping,
        verify_s610_daily_mapping_receipt,
    )

    factory = _session_factory()
    with factory() as session:
        created = resolve_or_create_s610_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            approval_d_hash=APPROVAL_D_HASH,
            client=DominantClient(),
            now=datetime(2026, 7, 29, 10, tzinfo=UTC),
        )
        session.commit()

        verified = verify_s610_daily_mapping_receipt(
            session,
            receipt=created.receipt,
            trading_day=TRADING_DAY,
            approval_d_hash=APPROVAL_D_HASH,
        )
        assert verified.mapping_sha256 == created.mapping_sha256

        drifted = dict(created.receipt)
        drifted["actual_contract"] = "JM2509"
        with pytest.raises(
            HtDyS610DailyMappingError,
            match="s610_daily_mapping_receipt_invalid",
        ):
            verify_s610_daily_mapping_receipt(
                session,
                receipt=drifted,
                trading_day=TRADING_DAY,
                approval_d_hash=APPROVAL_D_HASH,
            )


def test_s610_c2_daily_mapping_uses_c2_parent_authorization() -> None:
    from app.services.htdy_s6_10_daily_mapping import (
        resolve_or_create_s610_c2_daily_mapping,
        verify_s610_c2_daily_mapping_receipt,
    )

    factory = _session_factory()
    with factory() as session:
        created = resolve_or_create_s610_c2_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            approval_c2_parent_hash=APPROVAL_C2_PARENT_HASH,
            client=DominantClient(),
            now=datetime(2026, 7, 29, 10, tzinfo=UTC),
        )
        session.commit()

        assert created.receipt["authorization_type"] == (
            "approval_c2_parent"
        )
        assert created.receipt["authorization_hash"] == (
            APPROVAL_C2_PARENT_HASH
        )
        assert "approval_d_hash" not in created.receipt
        assert created.receipt["mapping_identity"]["data_version"] == (
            "htdy_s610_c2_20260730_cccccccccccc_v1"
        )

        verified = verify_s610_c2_daily_mapping_receipt(
            session,
            receipt=created.receipt,
            trading_day=TRADING_DAY,
            approval_c2_parent_hash=APPROVAL_C2_PARENT_HASH,
        )
        assert verified.mapping_sha256 == created.mapping_sha256


def test_runtime_mapping_queries_rqdata_only_in_write_phase(tmp_path) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
    )
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        _runtime_daily_mapping,
        publish_daily_mapping_receipt_create_only,
    )

    factory = _session_factory()
    daily_root = tmp_path / "daily"
    daily_root.mkdir()
    client = DominantClient()

    with factory() as session:
        with pytest.raises(
            HtDyS610LongRunningError,
            match="daily_mapping_receipt_missing",
        ):
            _runtime_daily_mapping(
                session,
                trading_day=TRADING_DAY,
                daily_root=daily_root,
                approval_d_hash=APPROVAL_D_HASH,
                allow_create=False,
                client_factory=lambda: pytest.fail(
                    "metadata path must not call RQData"
                ),
                now=lambda: datetime(
                    2026, 7, 29, 10, tzinfo=UTC
                ),
            )

        created = _runtime_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            daily_root=daily_root,
            approval_d_hash=APPROVAL_D_HASH,
            allow_create=True,
            client_factory=lambda: client,
            now=lambda: datetime(2026, 7, 29, 10, tzinfo=UTC),
        )
        assert created["actual_contract"] == "JM2609"
        assert created["mapping_receipt"]["status"] == "created"
        assert not (
            daily_root
            / TRADING_DAY.isoformat()
            / "mapping_receipt.json"
        ).exists()
        session.commit()

        publish_daily_mapping_receipt_create_only(
            created["mapping_receipt"],
            root=daily_root,
            trading_day=TRADING_DAY,
            create=True,
        )
        verified = _runtime_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            daily_root=daily_root,
            approval_d_hash=APPROVAL_D_HASH,
            allow_create=False,
            client_factory=lambda: pytest.fail(
                "metadata path must not call RQData"
            ),
            now=lambda: datetime(2026, 7, 29, 10, tzinfo=UTC),
        )

        assert verified["mapping_receipt"] == created["mapping_receipt"]
        assert client.calls == [
            ("jm", TRADING_DAY, TRADING_DAY, 1)
        ]


def test_runtime_mapping_rejects_symlinked_day_root(tmp_path) -> None:
    from app.services.htdy_s6_10_long_running import (
        HtDyS610LongRunningError,
    )
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        _runtime_daily_mapping,
    )

    factory = _session_factory()
    daily_root = tmp_path / "daily"
    outside = tmp_path / "outside"
    daily_root.mkdir()
    outside.mkdir()
    (daily_root / TRADING_DAY.isoformat()).symlink_to(
        outside,
        target_is_directory=True,
    )

    with factory() as session, pytest.raises(
        HtDyS610LongRunningError,
        match="daily_mapping_root_invalid",
    ):
        _runtime_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            daily_root=daily_root,
            approval_d_hash=APPROVAL_D_HASH,
            allow_create=False,
            client_factory=lambda: pytest.fail(
                "invalid root must stop before RQData"
            ),
        )


def test_runtime_mapping_recovers_after_commit_before_receipt_publish(
    tmp_path,
) -> None:
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        _runtime_daily_mapping,
        publish_daily_mapping_receipt_create_only,
    )

    factory = _session_factory()
    daily_root = tmp_path / "daily"
    daily_root.mkdir()
    client = DominantClient()

    with factory() as session:
        first = _runtime_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            daily_root=daily_root,
            approval_d_hash=APPROVAL_D_HASH,
            allow_create=True,
            client_factory=lambda: client,
        )
        assert first["mapping_receipt"]["status"] == "created"
        session.commit()

    with factory() as session:
        recovered = _runtime_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            daily_root=daily_root,
            approval_d_hash=APPROVAL_D_HASH,
            allow_create=True,
            client_factory=lambda: client,
        )
        assert recovered["mapping_receipt"]["status"] == (
            "existing_verified"
        )
        session.commit()
        publish_daily_mapping_receipt_create_only(
            recovered["mapping_receipt"],
            root=daily_root,
            trading_day=TRADING_DAY,
            create=True,
        )

        verified = _runtime_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            daily_root=daily_root,
            approval_d_hash=APPROVAL_D_HASH,
            allow_create=False,
            client_factory=lambda: pytest.fail(
                "published receipt recovery must be read-only"
            ),
        )
        assert verified == recovered
        assert client.calls == [
            ("jm", TRADING_DAY, TRADING_DAY, 1),
            ("jm", TRADING_DAY, TRADING_DAY, 1),
        ]
