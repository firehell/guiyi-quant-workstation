from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    select,
    text,
)

from app.data_core.product_retirement import (
    RETIRED_PRODUCTS,
    ProductRetirementError,
    apply_retirement_packet,
    build_inventory_packet,
    build_runtime_gate_attestation,
    contract_product,
    database_rows_digest,
    externalize_database_rows,
    finalize_retirement_files,
    inventory_database,
    inventory_files,
    is_retired_identity,
    load_active_products,
    packet_digest,
    read_database_row_shards,
    verify_retirement_scope,
)


EXPECTED_RETIRED_PRODUCTS = {
    "ad": "铸造铝合金",
    "bb": "胶合板",
    "bc": "国际铜",
    "cy": "棉纱",
    "fb": "纤维板",
    "jr": "粳稻",
    "l_f": "聚乙烯月均价",
    "lg": "原木",
    "op": "胶版印刷纸",
    "pm": "普麦",
    "pp_f": "聚丙烯月均价",
    "ri": "早籼稻",
    "rr": "粳米",
    "t": "10年期国债",
    "tf": "5年期国债",
    "tl": "30年期国债",
    "ts": "2年期国债",
    "v_f": "聚氯乙烯月均价",
    "wh": "强麦",
    "wr": "线材",
    "zc": "动力煤",
}


def test_retirement_contract_uses_exact_21_product_chinese_mapping() -> None:
    assert RETIRED_PRODUCTS == EXPECTED_RETIRED_PRODUCTS


def test_contract_product_parses_exact_product_without_prefix_matching() -> None:
    assert contract_product("PP_F.MAIN") == "pp_f"
    assert contract_product("PP2609") == "pp"
    assert contract_product("T2609") == "t"
    assert contract_product("TA609") == "ta"
    assert contract_product("CFFEX.TF2609") == "tf"

    assert is_retired_identity(product="PP_F") is True
    assert is_retired_identity(product="PP") is False
    assert is_retired_identity(contract="T2609") is True
    assert is_retired_identity(contract="TA609") is False


def test_active_universe_contains_69_products_disjoint_from_retired_set() -> None:
    project_root = Path(__file__).resolve().parents[4]
    products = load_active_products(project_root / "data/universe/active_products.txt")

    assert len(products) == 69
    assert len(set(products)) == 69
    assert set(products).isdisjoint(RETIRED_PRODUCTS)
    assert "pp" in products
    assert "l" in products
    assert "v" in products
    assert "ta" in products


def test_file_inventory_matches_structured_target_paths_without_prefix_false_positives(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    target_paths = [
        data_root / "raw/rqdata/contract_universe/product=pp_f/pp_f_2025.parquet",
        data_root / "parquet/canonical/bars/period=1m/symbol=t/T2609.parquet",
        data_root / "processed/v1b/jr/jr.MAIN_5m.parquet",
    ]
    retained_paths = [
        data_root / "raw/rqdata/contract_universe/product=pp/pp_2025.parquet",
        data_root / "parquet/canonical/bars/period=1m/symbol=ta/TA609.parquet",
        data_root / "processed/v1b/l/l.MAIN_5m.parquet",
    ]
    for path in [*target_paths, *retained_paths]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode("utf-8"))

    entries, blockers = inventory_files({"data": data_root})

    assert blockers == ()
    assert {Path(entry.absolute_path) for entry in entries} == set(target_paths)
    assert all(entry.sha256 for entry in entries)


def test_file_inventory_accepts_v1b_directory_as_the_explicit_processed_root(
    tmp_path: Path,
) -> None:
    processed_root = tmp_path / "v1b"
    target = processed_root / "jr/jr.MAIN_5m.parquet"
    retained = processed_root / "pp/pp.MAIN_5m.parquet"
    for path in (target, retained):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bars")

    entries, blockers = inventory_files({"processed": processed_root})

    assert blockers == ()
    assert [entry.absolute_path for entry in entries] == [str(target)]


def test_database_inventory_expands_only_reverse_foreign_key_dependents() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    profiles = Table(
        "data_profiles", metadata, Column("profile_id", String, primary_key=True)
    )
    files = Table(
        "market_data_files",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("instrument_symbol", String),
        Column("contract_code", String),
        Column("file_path", String),
    )
    quality = Table(
        "data_quality_reports",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("file_id", ForeignKey("market_data_files.id")),
    )
    bindings = Table(
        "profile_active_bindings",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("profile_id", ForeignKey("data_profiles.profile_id")),
        Column("market_data_file_id", ForeignKey("market_data_files.id")),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(profiles.insert(), [{"profile_id": "mixed"}])
        connection.execute(
            files.insert(),
            [
                {
                    "id": 10,
                    "instrument_symbol": "PP_F",
                    "contract_code": "PP_F.MAIN",
                    "file_path": "/data/product=pp_f/a.parquet",
                },
                {
                    "id": 11,
                    "instrument_symbol": "PP",
                    "contract_code": "PP2609",
                    "file_path": "/data/product=pp/b.parquet",
                },
            ],
        )
        connection.execute(
            quality.insert(), [{"id": 20, "file_id": 10}, {"id": 21, "file_id": 11}]
        )
        connection.execute(
            bindings.insert(),
            [
                {"id": 30, "profile_id": "mixed", "market_data_file_id": 10},
                {"id": 31, "profile_id": "mixed", "market_data_file_id": 11},
            ],
        )

        rows, blockers = inventory_database(connection)

    assert blockers == ()
    assert {(row.table, row.primary_key[0][1]) for row in rows} == {
        ("market_data_files", 10),
        ("data_quality_reports", 20),
        ("profile_active_bindings", 30),
    }


def test_database_inventory_blocks_active_target_task() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    tasks = Table(
        "data_download_tasks",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("instrument_symbol", String),
        Column("contract_code", String),
        Column("status", String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            tasks.insert(),
            [
                {
                    "id": 1,
                    "instrument_symbol": "JR",
                    "contract_code": "JR.MAIN",
                    "status": "running",
                },
                {
                    "id": 2,
                    "instrument_symbol": "PP",
                    "contract_code": "PP.MAIN",
                    "status": "running",
                },
            ],
        )
    with engine.connect() as connection:
        rows, blockers = inventory_database(connection)

    assert [(row.table, row.primary_key[0][1]) for row in rows] == [
        ("data_download_tasks", 1)
    ]
    assert blockers == ("active_task:data_download_tasks:id=1:running",)


def test_database_inventory_blocks_queued_target_task() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    tasks = Table(
        "backtest_tasks",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("binding_snapshot", JSON),
        Column("status", String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            tasks.insert(),
            {"id": 1, "binding_snapshot": {"symbol": "JR"}, "status": "queued"},
        )
    with engine.connect() as connection:
        _, blockers = inventory_database(connection)

    assert blockers == ("active_task:backtest_tasks:id=1:queued",)


def test_database_inventory_expands_explicit_logical_dependencies_without_foreign_keys() -> (
    None
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    signals = Table(
        "strategy_signals",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("product", String),
    )
    decisions = Table(
        "signal_decisions",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("decision_key", String),
        Column("actual_contract", String),
    )
    events = Table(
        "signal_events",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("signal_id", Integer),
        Column("decision_id", Integer),
    )
    notifications = Table(
        "signal_notifications",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("event_id", Integer),
        Column("signal_id", Integer),
    )
    reconciliations = Table(
        "signal_decision_reconciliations",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("decision_id", Integer),
        Column("provider_final_snapshot", JSON),
    )
    reviews = Table(
        "review_notes",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("source_type", String),
        Column("source_id", Integer),
    )
    samples = Table(
        "research_samples",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("decision_key", String),
        Column("review_id", Integer),
    )
    attachments = Table(
        "review_attachments",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("review_id", Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(signals.insert(), {"id": 1, "product": "JR"})
        connection.execute(
            decisions.insert(),
            {"id": 2, "decision_key": "decision-jr", "actual_contract": "JR2609"},
        )
        connection.execute(events.insert(), {"id": 3, "signal_id": 1, "decision_id": 2})
        connection.execute(
            notifications.insert(), {"id": 4, "event_id": 3, "signal_id": 1}
        )
        connection.execute(
            reconciliations.insert(),
            {"id": 5, "decision_id": 2, "provider_final_snapshot": {}},
        )
        connection.execute(
            reviews.insert(),
            {"id": 6, "source_type": "signal_decision", "source_id": 2},
        )
        connection.execute(
            samples.insert(), {"id": 7, "decision_key": "decision-jr", "review_id": 6}
        )
        connection.execute(attachments.insert(), {"id": 8, "review_id": 6})
    with engine.connect() as connection:
        rows, blockers = inventory_database(connection)

    assert blockers == ()
    assert {(row.table, row.primary_key[0][1]) for row in rows} == {
        ("strategy_signals", 1),
        ("signal_decisions", 2),
        ("signal_events", 3),
        ("signal_notifications", 4),
        ("signal_decision_reconciliations", 5),
        ("review_notes", 6),
        ("research_samples", 7),
        ("review_attachments", 8),
    }


def test_database_inventory_finds_retired_identity_in_json_without_exposing_payload() -> (
    None
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    signals = Table(
        "strategy_signals",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("binding_snapshot", JSON),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            signals.insert(),
            [
                {
                    "id": 1,
                    "binding_snapshot": {
                        "dataset": {"symbol": "JR", "contract_or_series": "JR.MAIN"},
                        "secret": "do-not-copy",
                    },
                },
                {
                    "id": 2,
                    "binding_snapshot": {
                        "dataset": {"symbol": "TA", "contract_or_series": "TA.MAIN"}
                    },
                },
            ],
        )
    with engine.connect() as connection:
        rows, blockers = inventory_database(connection)

    assert blockers == ()
    assert [(row.table, row.primary_key[0][1]) for row in rows] == [
        ("strategy_signals", 1)
    ]
    assert rows[0].identity_columns == ("binding_snapshot",)
    assert "do-not-copy" not in json.dumps(
        rows[0].__dict__, ensure_ascii=False, default=str
    )


def test_inventory_packet_digest_is_repeatable_and_bound_to_scope(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data/raw/rqdata/product=jr/jr.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"jr")
    files, blockers = inventory_files({"data": tmp_path / "data"})

    first = build_inventory_packet(
        files=files,
        database_rows=(),
        blockers=blockers,
        code_sha="a" * 40,
        runtime_sha="b" * 40,
        database_revision="20260803_0032",
        generated_at="2026-08-05T12:00:00+08:00",
        roots={"data": tmp_path / "data"},
    )
    second = build_inventory_packet(
        files=files,
        database_rows=(),
        blockers=blockers,
        code_sha="a" * 40,
        runtime_sha="b" * 40,
        database_revision="20260803_0032",
        generated_at="2026-08-05T12:00:00+08:00",
        roots={"data": tmp_path / "data"},
    )

    assert first == second
    assert packet_digest(first) == packet_digest(second)
    assert first["scope"]["retired_product_count"] == 21
    assert first["summary"]["blocker_count"] == 0
    assert first["summary"]["database_row_count"] == 0
    assert first["summary"]["file_count"] == 1
    assert first["summary"]["file_bytes"] == 2
    assert first["summary"]["database_rows_sha256"] == database_rows_digest(())
    assert len(first["summary"]["files_sha256"]) == 64


def test_runtime_gate_attestation_is_bound_to_one_packet_and_run(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    packet = build_inventory_packet(
        files=(),
        database_rows=(),
        blockers=(),
        code_sha="a" * 40,
        runtime_sha="b" * 40,
        database_revision="revision-1",
        generated_at="2026-08-05T12:00:00+08:00",
        roots={"data": data_root},
    )

    attestation = build_runtime_gate_attestation(
        packet,
        shutdown_receipt_digest="c" * 64,
        run_id="retire-001",
        release_tag="runtime-20260805-c9de1cdf",
        expires_at="2026-08-05T13:00:00+08:00",
    )

    assert attestation["decision"] == "runtime_gate_attested"
    assert attestation["packet_sha256"] == packet_digest(packet)
    assert attestation["run_id"] == "retire-001"
    assert (
        attestation["retired_products_digest"]
        == packet["scope"]["retired_products_digest"]
    )


def test_apply_accepts_only_a_matching_runtime_gate_attestation(tmp_path: Path) -> None:
    engine, tables = _retirement_database(include_dependents=False)
    data_root = tmp_path / "data"
    data_root.mkdir()
    with engine.connect() as connection:
        rows, blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=(),
            database_rows=rows,
            blockers=blockers,
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        digest = packet_digest(packet)
        attestation = build_runtime_gate_attestation(
            packet,
            shutdown_receipt_digest="c" * 64,
            run_id="retire-001",
            release_tag="runtime-20260805-c9de1cdf",
            expires_at="2026-08-05T13:00:00+08:00",
        )

        receipt = apply_retirement_packet(
            connection,
            packet=packet,
            expected_packet_digest=digest,
            approval=attestation,
            roots={"data": data_root},
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            shutdown_receipt_digest="c" * 64,
            now="2026-08-05T12:30:00+08:00",
            approval_digest=packet_digest(attestation),
        )

        assert receipt["status"] == "applied"
        assert (
            connection.scalar(
                select(func.count()).select_from(tables["market_data_files"])
            )
            == 1
        )


def test_large_database_manifest_is_sharded_by_table_and_digest_bound(
    tmp_path: Path,
) -> None:
    engine, _ = _retirement_database()
    with engine.connect() as connection:
        rows, blockers = inventory_database(connection)
    packet = build_inventory_packet(
        files=(),
        database_rows=rows,
        blockers=blockers,
        code_sha="a" * 40,
        runtime_sha="b" * 40,
        database_revision="revision-1",
        generated_at="2026-08-05T12:00:00+08:00",
    )
    packet_path = tmp_path / "packet.json"

    sharded = externalize_database_rows(
        packet,
        packet_path=packet_path,
        shard_size=1,
    )

    assert sharded["database_rows"] == []
    assert len(sharded["database_row_shards"]) == 3
    assert {item["table"] for item in sharded["database_row_shards"]} == {
        "data_quality_reports",
        "market_data_files",
        "profile_active_bindings",
    }
    assert list(read_database_row_shards(sharded, packet_root=tmp_path)) == list(rows)

    first_shard = tmp_path / sharded["database_row_shards"][0]["relative_path"]
    first_shard.write_bytes(first_shard.read_bytes() + b"\n")
    with pytest.raises(ProductRetirementError, match="SHARD_DIGEST"):
        list(read_database_row_shards(sharded, packet_root=tmp_path))


def test_apply_requires_exact_approval_and_deletes_only_packet_objects(
    tmp_path: Path,
) -> None:
    engine, tables = _retirement_database()
    data_root = tmp_path / "data"
    target = data_root / "raw/rqdata/contract_universe/product=jr/jr.parquet"
    retained = data_root / "raw/rqdata/contract_universe/product=pp/pp.parquet"
    for path in (target, retained):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode("utf-8"))

    with engine.connect() as connection:
        files, file_blockers = inventory_files({"data": data_root})
        rows, database_blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=files,
            database_rows=rows,
            blockers=(*file_blockers, *database_blockers),
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        digest = packet_digest(packet)
        approval = _approval(packet, digest)

        receipt = apply_retirement_packet(
            connection,
            packet=packet,
            expected_packet_digest=digest,
            approval=approval,
            roots={"data": data_root},
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            shutdown_receipt_digest="c" * 64,
            now="2026-08-05T12:30:00+08:00",
            approval_digest="d" * 64,
        )

        assert receipt["status"] == "applied"
        assert receipt["deleted_file_count"] == 1
        assert receipt["deleted_database_row_count"] == 3
        assert (
            connection.scalar(
                select(func.count()).select_from(tables["market_data_files"])
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(tables["data_quality_reports"])
            )
            == 1
        )
        assert (
            connection.scalar(
                select(func.count()).select_from(tables["profile_active_bindings"])
            )
            == 1
        )
        assert (
            connection.scalar(select(func.count()).select_from(tables["data_profiles"]))
            == 1
        )
        verification = verify_retirement_scope(connection, roots={"data": data_root})

    assert not target.exists()
    assert retained.exists()
    assert verification["status"] == "passed"


def test_externalized_database_manifest_can_be_applied(tmp_path: Path) -> None:
    engine, tables = _retirement_database()
    (tmp_path / "data").mkdir()
    with engine.connect() as connection:
        rows, blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=(),
            database_rows=rows,
            blockers=blockers,
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": tmp_path / "data"},
        )
        packet = externalize_database_rows(
            packet,
            packet_path=tmp_path / "packet.json",
            shard_size=1,
        )
        digest = packet_digest(packet)

        receipt = apply_retirement_packet(
            connection,
            packet=packet,
            expected_packet_digest=digest,
            approval=_approval(packet, digest),
            roots={"data": tmp_path / "data"},
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            shutdown_receipt_digest="c" * 64,
            now="2026-08-05T12:30:00+08:00",
            approval_digest="d" * 64,
            packet_root=tmp_path,
        )

        assert receipt["deleted_database_row_count"] == 3
        assert (
            connection.scalar(
                select(func.count()).select_from(tables["market_data_files"])
            )
            == 1
        )


def test_apply_rejects_new_target_database_row_not_in_approved_packet(
    tmp_path: Path,
) -> None:
    engine, tables = _retirement_database(include_dependents=False)
    data_root = tmp_path / "data"
    data_root.mkdir()
    with engine.connect() as connection:
        rows, blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=(),
            database_rows=rows,
            blockers=blockers,
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        digest = packet_digest(packet)
        connection.execute(
            tables["market_data_files"].insert(),
            {
                "id": 12,
                "instrument_symbol": "JR",
                "contract_code": "JR2609",
                "file_path": "/data/product=jr/new.parquet",
            },
        )
        connection.commit()

        with pytest.raises(ProductRetirementError, match="DATABASE_SCOPE_DRIFT"):
            apply_retirement_packet(
                connection,
                packet=packet,
                expected_packet_digest=digest,
                approval=_approval(packet, digest),
                roots={"data": data_root},
                code_sha="a" * 40,
                runtime_sha="b" * 40,
                database_revision="revision-1",
                shutdown_receipt_digest="c" * 64,
                now="2026-08-05T12:30:00+08:00",
                approval_digest="d" * 64,
            )

        assert (
            connection.scalar(
                select(func.count()).select_from(tables["market_data_files"])
            )
            == 3
        )


def test_apply_rejects_new_target_file_not_in_approved_packet(tmp_path: Path) -> None:
    engine, _ = _retirement_database(include_dependents=False)
    data_root = tmp_path / "data"
    target = data_root / "raw/rqdata/product=jr/original.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    with engine.connect() as connection:
        files, file_blockers = inventory_files({"data": data_root})
        rows, database_blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=files,
            database_rows=rows,
            blockers=(*file_blockers, *database_blockers),
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        digest = packet_digest(packet)
        added = target.parent / "added.parquet"
        added.write_bytes(b"added")

        with pytest.raises(ProductRetirementError, match="FILE_SCOPE_DRIFT"):
            apply_retirement_packet(
                connection,
                packet=packet,
                expected_packet_digest=digest,
                approval=_approval(packet, digest),
                roots={"data": data_root},
                code_sha="a" * 40,
                runtime_sha="b" * 40,
                database_revision="revision-1",
                shutdown_receipt_digest="c" * 64,
                now="2026-08-05T12:30:00+08:00",
                approval_digest="d" * 64,
            )

    assert target.exists()
    assert added.exists()


def test_apply_rejects_packet_file_list_not_matching_its_summary(
    tmp_path: Path,
) -> None:
    engine, _ = _retirement_database(include_dependents=False)
    data_root = tmp_path / "data"
    target = data_root / "raw/rqdata/product=jr/target.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"target")
    with engine.connect() as connection:
        files, file_blockers = inventory_files({"data": data_root})
        rows, database_blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=files,
            database_rows=rows,
            blockers=(*file_blockers, *database_blockers),
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        packet["files"] = []
        digest = packet_digest(packet)

        with pytest.raises(
            ProductRetirementError, match="FILE_MANIFEST_DIGEST_MISMATCH"
        ):
            apply_retirement_packet(
                connection,
                packet=packet,
                expected_packet_digest=digest,
                approval=_approval(packet, digest),
                roots={"data": data_root},
                code_sha="a" * 40,
                runtime_sha="b" * 40,
                database_revision="revision-1",
                shutdown_receipt_digest="c" * 64,
                now="2026-08-05T12:30:00+08:00",
                approval_digest="d" * 64,
            )

    assert target.exists()


def test_apply_restores_staged_file_when_database_transaction_fails(
    tmp_path: Path,
) -> None:
    engine, _ = _retirement_database(include_dependents=False)
    data_root = tmp_path / "data"
    target = data_root / "raw/rqdata/contract_universe/product=jr/jr.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"jr")

    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER reject_retirement BEFORE DELETE ON market_data_files "
                "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
            )
        )
        connection.commit()
        files, file_blockers = inventory_files({"data": data_root})
        rows, database_blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=files,
            database_rows=rows,
            blockers=(*file_blockers, *database_blockers),
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        digest = packet_digest(packet)

        with pytest.raises(Exception, match="blocked"):
            apply_retirement_packet(
                connection,
                packet=packet,
                expected_packet_digest=digest,
                approval=_approval(packet, digest),
                roots={"data": data_root},
                code_sha="a" * 40,
                runtime_sha="b" * 40,
                database_revision="revision-1",
                shutdown_receipt_digest="c" * 64,
                now="2026-08-05T12:30:00+08:00",
                approval_digest="d" * 64,
            )

        assert target.exists()
        assert (
            connection.scalar(
                select(func.count()).select_from(
                    Table("market_data_files", MetaData(), autoload_with=connection)
                )
            )
            == 2
        )


def test_finalize_resumes_file_purge_after_database_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, tables = _retirement_database(include_dependents=False)
    data_root = tmp_path / "data"
    target = data_root / "raw/rqdata/product=jr/jr.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"jr")
    original_unlink = Path.unlink
    failed_once = False

    def fail_staging_unlink(path: Path, *args, **kwargs):
        nonlocal failed_once
        if ".product-retirement-staging" in path.parts and not failed_once:
            failed_once = True
            raise PermissionError("fault injection")
        return original_unlink(path, *args, **kwargs)

    with engine.connect() as connection:
        files, file_blockers = inventory_files({"data": data_root})
        rows, database_blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=files,
            database_rows=rows,
            blockers=(*file_blockers, *database_blockers),
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        digest = packet_digest(packet)
        monkeypatch.setattr(Path, "unlink", fail_staging_unlink)
        partial = apply_retirement_packet(
            connection,
            packet=packet,
            expected_packet_digest=digest,
            approval=_approval(packet, digest),
            roots={"data": data_root},
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            shutdown_receipt_digest="c" * 64,
            now="2026-08-05T12:30:00+08:00",
            approval_digest="d" * 64,
        )
        monkeypatch.setattr(Path, "unlink", original_unlink)

        assert partial["status"] == "db_committed_purge_pending"
        assert partial["remaining_staged_files"]
        assert (
            connection.scalar(
                select(func.count()).select_from(tables["market_data_files"])
            )
            == 1
        )
        finalized = finalize_retirement_files(
            connection,
            packet=packet,
            expected_packet_digest=digest,
            prior_receipt=partial,
            roots={"data": data_root},
        )

    assert finalized["status"] == "applied"
    assert finalized["verification"]["status"] == "passed"
    assert not target.exists()


def test_apply_rejects_file_drift_before_database_write(tmp_path: Path) -> None:
    engine, tables = _retirement_database(include_dependents=False)
    data_root = tmp_path / "data"
    target = data_root / "raw/rqdata/contract_universe/product=jr/jr.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"jr")

    with engine.connect() as connection:
        files, blockers = inventory_files({"data": data_root})
        rows, database_blockers = inventory_database(connection)
        packet = build_inventory_packet(
            files=files,
            database_rows=rows,
            blockers=(*blockers, *database_blockers),
            code_sha="a" * 40,
            runtime_sha="b" * 40,
            database_revision="revision-1",
            generated_at="2026-08-05T12:00:00+08:00",
            roots={"data": data_root},
        )
        digest = packet_digest(packet)
        target.write_bytes(b"changed")

        with pytest.raises(ProductRetirementError, match="FILE_SCOPE_DRIFT"):
            apply_retirement_packet(
                connection,
                packet=packet,
                expected_packet_digest=digest,
                approval=_approval(packet, digest),
                roots={"data": data_root},
                code_sha="a" * 40,
                runtime_sha="b" * 40,
                database_revision="revision-1",
                shutdown_receipt_digest="c" * 64,
                now="2026-08-05T12:30:00+08:00",
                approval_digest="d" * 64,
            )

        assert (
            connection.scalar(
                select(func.count()).select_from(tables["market_data_files"])
            )
            == 2
        )


def _retirement_database(*, include_dependents: bool = True):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    profiles = Table(
        "data_profiles", metadata, Column("profile_id", String, primary_key=True)
    )
    files = Table(
        "market_data_files",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("instrument_symbol", String),
        Column("contract_code", String),
        Column("file_path", String),
    )
    quality = Table(
        "data_quality_reports",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("file_id", ForeignKey("market_data_files.id")),
    )
    bindings = Table(
        "profile_active_bindings",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("profile_id", ForeignKey("data_profiles.profile_id")),
        Column("market_data_file_id", ForeignKey("market_data_files.id")),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(profiles.insert(), [{"profile_id": "mixed"}])
        connection.execute(
            files.insert(),
            [
                {
                    "id": 10,
                    "instrument_symbol": "JR",
                    "contract_code": "JR.MAIN",
                    "file_path": "/data/product=jr/a.parquet",
                },
                {
                    "id": 11,
                    "instrument_symbol": "PP",
                    "contract_code": "PP2609",
                    "file_path": "/data/product=pp/b.parquet",
                },
            ],
        )
        if include_dependents:
            connection.execute(
                quality.insert(), [{"id": 20, "file_id": 10}, {"id": 21, "file_id": 11}]
            )
            connection.execute(
                bindings.insert(),
                [
                    {"id": 30, "profile_id": "mixed", "market_data_file_id": 10},
                    {"id": 31, "profile_id": "mixed", "market_data_file_id": 11},
                ],
            )
    return engine, {
        "data_profiles": profiles,
        "market_data_files": files,
        "data_quality_reports": quality,
        "profile_active_bindings": bindings,
    }


def _approval(packet: dict, digest: str) -> dict:
    return {
        "schema_version": 1,
        "command": "product-retirement.apply",
        "decision": "approved",
        "packet_sha256": digest,
        "code_sha": packet["bound_facts"]["code_sha"],
        "runtime_sha": packet["bound_facts"]["runtime_sha"],
        "database_revision": packet["bound_facts"]["database_revision"],
        "retired_products_digest": packet["scope"]["retired_products_digest"],
        "shutdown_receipt_sha256": "c" * 64,
        "expires_at": "2026-08-05T13:00:00+08:00",
    }
