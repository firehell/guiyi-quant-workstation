from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MainContractMap


PARENT_HASH = "a" * 64
TRADING_DAY = date(2026, 7, 27)
COUNTS = {
    "strategy_signals": 10,
    "signal_events": 20,
    "signal_notifications": 0,
    "signal_scan_tasks": 0,
    "orders": 0,
    "trades": 0,
    "review_notes": 2,
    "backtest_tasks": 3,
    "profile_bindings": 4,
    "canonical_assets": 5,
}
HASHES = {
    "backtest_state_sha256": "a" * 64,
    "profile_bindings_sha256": "b" * 64,
    "canonical_assets_sha256": "c" * 64,
    "forbidden_tables_sha256": "d" * 64,
}


def _bindings(tmp_path):
    return {
        "deployment_packet_sha256": "1" * 64,
        "s6_07_rebind_packet_sha256": "2" * 64,
        "s6_07_final_receipt": {
            "path": str(tmp_path / "completion_receipt.json"),
            "sha256": "3" * 64,
        },
        "database_recovery_receipt": {
            "path": str(tmp_path / "recovery_receipt.json"),
            "sha256": "0" * 64,
            "receipt_hash": "1" * 64,
        },
        "parent_mapping": {
            "trade_date": "2026-07-24",
            "contract_code": "JM2609",
            "sha256": "2" * 64,
        },
        "service_bundle_sha256": "4" * 64,
        "runtime": {
            "root": str(tmp_path / "runtime"),
            "commit": "5" * 40,
            "tree_sha256": "6" * 64,
            "tracked_clean": True,
        },
        "database_revision": "20260721_0025",
        "actual_contract_resolver_sha256": "7" * 64,
        "profile": {
            "profile_id": "live_observation_v1",
            "market_data_file_id": 7,
            "data_version": "jm-live-v1",
            "checksum": "8" * 64,
        },
        "source_sha256": "9" * 64,
        "policy_sha256": "a" * 64,
        "writer_sha256": "b" * 64,
        "web": {
            "source_sha256": "c" * 64,
            "bundle_sha256": "d" * 64,
        },
        "feature_flags": {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        },
        "baseline": {"counts": COUNTS, "hashes": HASHES},
        "output": {
            "root": str(tmp_path),
            "device": tmp_path.stat().st_dev,
            "mount": str(tmp_path),
        },
        "launchd": {
            "label": "com.guiyi.quant-runtime-scheduler",
            "plist_sha256": "e" * 64,
        },
        "no_migration": True,
    }


def _state():
    return {
        "trading_day": TRADING_DAY,
        "actual_contract": "JM2609",
        "mapping_sha256": "f" * 64,
        "source_facts": {
            "profile_sha256": "1" * 64,
            "source_sha256": "2" * 64,
            "policy_sha256": "3" * 64,
            "runtime_heartbeat_sha256": "4" * 64,
            "autosend_enabled": False,
        },
        "counts": COUNTS,
        "hashes": HASHES,
        "events": [],
    }


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


def test_daily_mapping_is_create_only_from_exact_rqdata_rank1() -> None:
    from app.services.htdy_s6_08_daily_mapping import (
        resolve_or_create_daily_mapping,
    )

    SessionLocal = _session_factory()
    client = DominantClient()
    with SessionLocal() as session:
        result = resolve_or_create_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            parent_hash=PARENT_HASH,
            client=client,
            now=datetime(2026, 7, 27, 0, 20, tzinfo=UTC),
        )
        session.commit()
        row = session.scalar(select(MainContractMap))

    assert client.calls == [("jm", TRADING_DAY, TRADING_DAY, 1)]
    assert result.status == "created"
    assert result.actual_contract == "JM2609"
    assert result.mapping_id == row.id
    assert result.mapping_sha256
    assert result.receipt["source"] == "rqdatac.futures.get_dominant"
    assert row.instrument_symbol == "jm"
    assert row.trade_date == TRADING_DAY
    assert row.rank == 1
    assert row.rule == "volume_open_interest"
    assert row.provider == "rqdata"
    assert row.data_version.startswith("htdy_s608_20260727_")
    assert row.raw_payload["parent_packet_hash"] == PARENT_HASH


def test_daily_mapping_reuses_one_exact_row_but_rejects_rqdata_drift() -> None:
    from app.services.htdy_s6_08_daily_mapping import (
        HtDyDailyMappingError,
        resolve_or_create_daily_mapping,
    )

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=TRADING_DAY,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="existing",
                raw_payload={},
            )
        )
        session.commit()

        reused = resolve_or_create_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            parent_hash=PARENT_HASH,
            client=DominantClient(),
            now=datetime(2026, 7, 27, 0, 20, tzinfo=UTC),
        )
        assert reused.status == "existing_verified"

        with pytest.raises(
            HtDyDailyMappingError,
            match="daily_mapping_rqdata_drift",
        ):
            resolve_or_create_daily_mapping(
                session,
                trading_day=TRADING_DAY,
                parent_hash=PARENT_HASH,
                client=DominantClient("JM2701"),
                now=datetime(2026, 7, 27, 0, 21, tzinfo=UTC),
            )


def test_daily_mapping_receipt_rebinds_exact_database_state() -> None:
    from app.services.htdy_s6_08_daily_mapping import (
        HtDyDailyMappingError,
        resolve_or_create_daily_mapping,
        verify_daily_mapping_receipt,
    )

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        created = resolve_or_create_daily_mapping(
            session,
            trading_day=TRADING_DAY,
            parent_hash=PARENT_HASH,
            client=DominantClient(),
            now=datetime(2026, 7, 27, 0, 20, tzinfo=UTC),
        )
        session.commit()
        verified = verify_daily_mapping_receipt(
            session,
            receipt=created.receipt,
            trading_day=TRADING_DAY,
            parent_hash=PARENT_HASH,
        )
        assert verified.mapping_sha256 == created.mapping_sha256

        row = session.get(MainContractMap, created.mapping_id)
        assert row is not None
        row.data_version = "drifted"
        session.flush()
        with pytest.raises(
            HtDyDailyMappingError,
            match="daily_mapping_receipt_database_drift",
        ):
            verify_daily_mapping_receipt(
                session,
                receipt=created.receipt,
                trading_day=TRADING_DAY,
                parent_hash=PARENT_HASH,
            )


def test_daily_mapping_rejects_duplicate_conflict_and_non_actual_contract() -> None:
    from app.services.htdy_s6_08_daily_mapping import (
        HtDyDailyMappingError,
        resolve_or_create_daily_mapping,
    )

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add_all(
            [
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=TRADING_DAY,
                    rank=1,
                    contract_code=contract,
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version=f"v{index}",
                    raw_payload={},
                )
                for index, contract in enumerate(("JM2609", "JM2701"))
            ]
        )
        session.commit()
        with pytest.raises(
            HtDyDailyMappingError,
            match="daily_mapping_database_conflict",
        ):
            resolve_or_create_daily_mapping(
                session,
                trading_day=TRADING_DAY,
                parent_hash=PARENT_HASH,
                client=DominantClient(),
                now=datetime(2026, 7, 27, 0, 20, tzinfo=UTC),
            )

    with SessionLocal() as session:
        with pytest.raises(
            HtDyDailyMappingError,
            match="daily_mapping_rqdata_invalid",
        ):
            resolve_or_create_daily_mapping(
                session,
                trading_day=TRADING_DAY,
                parent_hash=PARENT_HASH,
                client=DominantClient("JM.MAIN"),
                now=datetime(2026, 7, 27, 0, 20, tzinfo=UTC),
            )


def test_runtime_gate_materializes_mapping_before_daily_state_and_receipts_after_commit(
    tmp_path,
) -> None:
    from app.services.htdy_s6_08_runtime_gate import HtDySchemaV3RuntimeGate
    from app.services.htdy_s6_08_schema_v3 import build_parent_authorization

    bindings = _bindings(tmp_path)
    parent = build_parent_authorization(
        trading_days=[TRADING_DAY],
        bindings=bindings,
    )
    parent_path = tmp_path / "service_parent_packet.json"
    parent_path.write_text(__import__("json").dumps(parent), encoding="utf-8")
    calls: list[str] = []

    def materialize(session, trading_day, directory):
        calls.append("mapping")
        return {
            "status": "created",
            "receipt": {
                "schema_version": 1,
                "status": "created",
                "trading_day": trading_day.isoformat(),
                "actual_contract": "JM2609",
                "mapping_sha256": "f" * 64,
            },
        }

    def current_state(session, trading_day):
        calls.append("state")
        return _state()

    gate = HtDySchemaV3RuntimeGate(
        parent_packet_path=parent_path,
        approval_hash=parent["packet_hash"],
        current_bindings=lambda session: bindings,
        current_daily_state=current_state,
        handler_factory=lambda session: "handler",
        daily_mapping_resolver=materialize,
        now=lambda: datetime(2026, 7, 27, 1, 5, tzinfo=UTC),
    )

    gate(object(), phase="pre_write")
    assert calls == ["mapping", "state"]
    assert not (
        tmp_path
        / "daily"
        / "2026-07-27"
        / "mapping_receipt.json"
    ).exists()

    gate(
        object(),
        phase="post_write",
        result={
            "trading_day": "2026-07-27",
            "signal_events": {
                "created": 0,
                "changed": 0,
                "unchanged": 0,
                "blocked": 0,
                "event_ids": [],
            },
        },
    )
    gate(object(), phase="after_commit")
    assert (
        tmp_path
        / "daily"
        / "2026-07-27"
        / "mapping_receipt.json"
    ).is_file()


def test_runtime_gate_discards_staged_mapping_from_aborted_cycle(
    tmp_path,
) -> None:
    from app.services.htdy_s6_08_runtime_gate import HtDySchemaV3RuntimeGate
    from app.services.htdy_s6_08_schema_v3 import build_parent_authorization

    bindings = _bindings(tmp_path)
    parent = build_parent_authorization(
        trading_days=[TRADING_DAY],
        bindings=bindings,
    )
    parent_path = tmp_path / "service_parent_packet.json"
    parent_path.write_text(__import__("json").dumps(parent), encoding="utf-8")
    generation = 0

    def materialize(session, trading_day, directory):
        nonlocal generation
        del session, directory
        generation += 1
        return {
            "receipt": {
                "schema_version": 1,
                "status": "created",
                "trading_day": trading_day.isoformat(),
                "actual_contract": "JM2609",
                "mapping_sha256": "f" * 64,
                "generation": generation,
            }
        }

    gate = HtDySchemaV3RuntimeGate(
        parent_packet_path=parent_path,
        approval_hash=parent["packet_hash"],
        current_bindings=lambda session: bindings,
        current_daily_state=lambda session, trading_day: _state(),
        handler_factory=lambda session: "handler",
        daily_mapping_resolver=materialize,
        now=lambda: datetime(2026, 7, 27, 1, 5, tzinfo=UTC),
    )

    gate(object(), phase="pre_write")
    gate(object(), phase="pre_write")
    gate(
        object(),
        phase="post_write",
        result={
            "trading_day": "2026-07-27",
            "signal_events": {
                "created": 0,
                "changed": 0,
                "unchanged": 0,
                "blocked": 0,
                "event_ids": [],
            },
        },
    )
    gate(object(), phase="after_commit")

    receipt = __import__("json").loads(
        (
            tmp_path
            / "daily"
            / "2026-07-27"
            / "mapping_receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["generation"] == 2
