from __future__ import annotations

import csv
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, MainContractMap, MarketDataFile


TASK_ID = "ACTUAL-DOMINANT-ROLL-V2-006"
MAPPING_BATCH = "jm-rank1-mapping-006-001"
MANIFEST_BATCH = "actual-manifest-repair-006-001"
LOCAL_BATCH = "jm-actual-local-rebuild-006-001"
MAPPING_VERSION = "actual_dominant_roll_006_local_evidence_v1"
MAPPING_DATES = tuple(
    date.fromisoformat(value)
    for value in (
        "2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30",
        "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06",
        "2026-07-08", "2026-07-09", "2026-07-10",
    )
)
WINNER_MANIFEST_IDS = (86646, 42430, 42432, 42434, 42436, 42438, 42440, 42442, 42444, 86666)
SUPERSEDE_PAIRS = ((42428, 86646), (47880, 99695), (42446, 34104))


def build_local_rebuild_operations() -> list[dict[str, Any]]:
    return [
        {
            "operation": "local_rebuild_and_promote",
            "product": "jm",
            "contract_code": "JM2609",
            "period": period,
            "start_date": "2026-07-08",
            "end_date": "2026-07-10",
            "data_version": f"actual_dominant_roll_006_JM2609_{period}_20260708_20260710_v1",
        }
        for period in ("1d", "1m")
    ]


def build_local_rebuild_plan(*, project_root: Path) -> dict[str, Any]:
    root = project_root.resolve(strict=False)
    operations = build_local_rebuild_operations()
    raw_by_period = {
        "1m": root / "data/raw/rqdata/dominant_contract_bars/product=jm/frequency=1m/version=v2/jm_1m_incremental_raw_20260707_20260711.parquet",
        "1d": root / "data/raw/rqdata/dominant_contract_bars/product=jm/frequency=1d/version=v2/jm_1d_incremental_raw_20260705_20260711.parquet",
    }
    for operation in operations:
        raw = raw_by_period[operation["period"]]
        operation["source_path"] = str(raw)
        operation["source_sha256"] = _sha256(raw)
        operation["output_path"] = str(
            root / "data/parquet/canonical/bars/provider=rqdata" / f"period={operation['period']}" /
            "exchange=DCE/symbol=jm/contract=JM2609" /
            f"JM2609_{operation['period']}_20260708_20260710_actual_roll_006_v1.parquet"
        )
    return {
        "task_id": TASK_ID,
        "batch_id": LOCAL_BATCH,
        "operations": operations,
        "ledger_sha256": ledger_sha256(operations),
        "calls_rqdata": False,
    }


def write_local_rebuild_plan(plan: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite {output_dir}")
    output_dir.mkdir(parents=True)
    json_path = output_dir / "local_rebuild_plan.json"
    json_path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    csv_path = output_dir / "local_rebuild_operations.csv"
    _write_operations_csv(csv_path, plan["operations"])
    hash_path = output_dir / "ledger_sha256.txt"
    hash_path.write_text(plan["ledger_sha256"] + "\n", encoding="utf-8")
    return {"plan": json_path, "operations": csv_path, "sha256": hash_path}


def apply_local_rebuild_plan(*, project_root: Path, session: Session, plan: dict[str, Any]) -> dict[str, Any]:
    _validate_plan(plan, LOCAL_BATCH)
    root = project_root.resolve(strict=False)
    operations = plan["operations"]
    if [(row["contract_code"], row["period"], row["start_date"], row["end_date"]) for row in operations] != [
        ("JM2609", "1d", "2026-07-08", "2026-07-10"),
        ("JM2609", "1m", "2026-07-08", "2026-07-10"),
    ]:
        raise ValueError("local rebuild scope drift")
    created_paths: list[Path] = []
    registered: list[int] = []
    quality_ids: list[int] = []
    manifest_rows: list[dict[str, Any]] = []
    manifest = root / "data/manifests/actual_dominant_roll_006_local_rebuild_001.csv"
    if manifest.exists():
        raise FileExistsError(f"refusing to overwrite {manifest}")
    try:
        for operation in operations:
            source = Path(operation["source_path"])
            output = Path(operation["output_path"])
            if _sha256(source) != operation["source_sha256"] or output.exists():
                raise ValueError(f"source checksum drift or output exists for {operation['period']}")
            output.parent.mkdir(parents=True, exist_ok=True)
            _build_local_parquet(source=source, output=output, period=operation["period"], data_version=operation["data_version"])
            created_paths.append(output)
            facts = _parquet_facts(output)
            if facts["min_trading_day"] != date(2026, 7, 8) or facts["max_trading_day"] != date(2026, 7, 10):
                raise ValueError(f"rebuilt boundary failed for {operation['period']}: {facts}")
            if facts["duplicate_count"] or facts["invalid_ohlc_count"] or facts["row_count"] <= 0:
                raise ValueError(f"rebuilt quality failed for {operation['period']}: {facts}")
            main_source = session.scalar(
                select(MarketDataFile)
                .where(
                    MarketDataFile.provider == "rqdata",
                    MarketDataFile.data_type == "bars",
                    MarketDataFile.instrument_symbol == "jm",
                    MarketDataFile.contract_code == "jm.MAIN",
                    MarketDataFile.period == operation["period"],
                    MarketDataFile.data_role == "primary",
                    MarketDataFile.quality_status == "passed",
                    MarketDataFile.start_time <= facts["min_datetime"],
                    MarketDataFile.end_time >= facts["max_datetime"],
                    MarketDataFile.file_path.contains("/canonical/bars/"),
                )
                .order_by(MarketDataFile.start_time.asc(), MarketDataFile.id.desc())
            )
            if main_source is None or not _matches_passed_main(output, _resolve(root, main_source.file_path)):
                raise ValueError(f"passed jm.MAIN cross-check failed for {operation['period']}")
            checksum = _sha256(output)
            file_row = MarketDataFile(
                task_id=None, provider="rqdata", data_type="bars", instrument_symbol="jm",
                contract_code="JM2609", period=operation["period"],
                start_time=facts["min_datetime"], end_time=facts["max_datetime"],
                file_path=str(output), row_count=facts["row_count"], file_size_bytes=output.stat().st_size,
                checksum=checksum, data_version=operation["data_version"], data_role="candidate", quality_status="passed",
            )
            session.add(file_row)
            session.flush()
            report = DataQualityReport(
                file_id=file_row.id, task_id=None, provider="rqdata", data_type="bars",
                instrument_symbol="jm", contract_code="JM2609", period=operation["period"],
                start_time=facts["min_datetime"], end_time=facts["max_datetime"], status="passed",
                missing_bars=0, duplicated_bars=0, abnormal_price_count=0, abnormal_volume_count=0,
                details={"task_id": TASK_ID, "batch_id": LOCAL_BATCH, "source_path": str(source), "source_sha256": operation["source_sha256"], "calls_rqdata": False},
            )
            session.add(report)
            session.flush()
            file_row.data_role = "primary"
            registered.append(file_row.id)
            quality_ids.append(report.id)
            manifest_rows.append({
                **operation, "market_data_file_id": file_row.id, "quality_report_ids": [report.id],
                "checksum": checksum, "standard_path": str(output),
                "start_time": facts["min_datetime"].isoformat(), "end_time": facts["max_datetime"].isoformat(),
                "data_role": "primary", "quality_status": "passed",
            })
        staged = manifest.with_suffix(".csv.staging")
        _write_manifest_csv(staged, manifest_rows)
        session.flush()
        staged.replace(manifest)
        session.commit()
    except Exception:
        session.rollback()
        manifest.unlink(missing_ok=True)
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    return {"market_data_file_ids": registered, "quality_report_ids": quality_ids, "manifest_path": str(manifest), "parquet_paths": [str(path) for path in created_paths]}


def ledger_sha256(operations: list[dict[str, Any]]) -> str:
    payload = json.dumps(operations, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_mapping_operations(*, existing_dates: set[date]) -> list[dict[str, Any]]:
    overlap = sorted(existing_dates & set(MAPPING_DATES))
    if overlap:
        raise ValueError(f"mapping before-state drift: existing frozen dates={overlap}")
    return [
        {
            "operation": "insert_main_contract_map",
            "instrument_symbol": "jm",
            "trade_date": day.isoformat(),
            "contract_code": "JM2609",
            "rank": 1,
            "rule": "volume_open_interest",
            "provider": "rqdata",
            "data_version": MAPPING_VERSION,
        }
        for day in MAPPING_DATES
    ]


def build_repair_plans(*, project_root: Path, session: Session) -> dict[str, dict[str, Any]]:
    root = project_root.resolve(strict=False)
    report = root / "data/reports/full_history_audit_v2_20260710/actual_dominant_roll_006"
    residual_path = report / "actual_residuals.csv"
    coverage_path = report / "actual_target_coverage.csv"
    residual_hash = _sha256(residual_path)
    coverage_rows = list(csv.DictReader(coverage_path.open(encoding="utf-8")))
    source_residuals = [row for row in coverage_rows if row.get("status") == "residual"]
    if len(source_residuals) != 24:
        raise ValueError(f"manifest residual scope drift: expected 24, found {len(source_residuals)}")

    existing = set(
        session.scalars(
            select(MainContractMap.trade_date).where(
                MainContractMap.instrument_symbol == "jm",
                MainContractMap.trade_date.in_(MAPPING_DATES),
                MainContractMap.rank == 1,
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.provider == "rqdata",
            )
        )
    )
    mapping_ops = build_mapping_operations(existing_dates=existing)
    raw_sources = [
        root / "data/raw/rqdata/dominant_contract_bars/product=jm/frequency=1m/version=v2/jm_1m_dominant_raw_20230103_20260710_v2.parquet",
        root / "data/raw/rqdata/dominant_contract_bars/product=jm/frequency=1d/version=v2/jm_1d_incremental_raw_20260705_20260711.parquet",
    ]
    source_evidence = [{"path": str(path), "sha256": _sha256(path)} for path in raw_sources]
    for operation in mapping_ops:
        operation["source_evidence"] = source_evidence

    files = {
        row.id: row
        for row in session.scalars(select(MarketDataFile).where(MarketDataFile.id.in_(WINNER_MANIFEST_IDS)))
    }
    if set(files) != set(WINNER_MANIFEST_IDS):
        raise ValueError("manifest winner before-state drift")
    manifest_ops: list[dict[str, Any]] = []
    for file_id in WINNER_MANIFEST_IDS:
        row = files[file_id]
        path = _resolve(root, row.file_path)
        actual = _sha256(path)
        reports = list(session.scalars(select(DataQualityReport).where(DataQualityReport.file_id == file_id)))
        if row.data_role != "primary" or row.quality_status != "passed" or row.checksum != actual:
            raise ValueError(f"manifest winner {file_id} failed role/quality/checksum precondition")
        if not reports or any(report.status != "passed" for report in reports):
            raise ValueError(f"manifest winner {file_id} lacks passed quality report")
        manifest_ops.append(
            {
                "operation": "add_manifest_row",
                "market_data_file_id": file_id,
                "quality_report_ids": sorted(report.id for report in reports),
                "product": row.instrument_symbol,
                "contract": row.contract_code,
                "period": row.period,
                "start_time": row.start_time.isoformat(),
                "end_time": row.end_time.isoformat(),
                "data_version": row.data_version,
                "data_role": row.data_role,
                "quality_status": row.quality_status,
                "checksum": actual,
                "standard_path": str(path),
            }
        )
    for loser, winner in SUPERSEDE_PAIRS:
        manifest_ops.append({"operation": "mark_superseded", "market_data_file_id": loser, "winner_id": winner})

    resolver_ops = [
        {"operation": name}
        for name in (
            "shared_rank1_mapping_resolver", "shared_parameter_precedence",
            "confirmed_live_bar_filter", "confirmed_trigger_evidence",
            "active_db_manifest_exact_association",
        )
    ]
    common = {"task_id": TASK_ID, "stage1_residual_sha256": residual_hash}
    return {
        "resolver": {**common, "batch_id": "resolver-semantics-006-001", "operations": resolver_ops, "ledger_sha256": ledger_sha256(resolver_ops)},
        "mapping": {**common, "batch_id": MAPPING_BATCH, "operations": mapping_ops, "ledger_sha256": ledger_sha256(mapping_ops)},
        "manifest": {**common, "batch_id": MANIFEST_BATCH, "source_residual_count": 24, "operations": manifest_ops, "ledger_sha256": ledger_sha256(manifest_ops)},
    }


def write_repair_plans(plans: dict[str, dict[str, Any]], output_dir: Path) -> dict[str, Path]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite {output_dir}")
    output_dir.mkdir(parents=True)
    outputs: dict[str, Path] = {}
    for name, plan in plans.items():
        directory = output_dir / name
        directory.mkdir()
        json_path = directory / f"{name}_repair_plan.json"
        json_path.write_text(json.dumps(plan, indent=2, sort_keys=True, default=str), encoding="utf-8")
        csv_path = directory / f"{name}_repair_operations.csv"
        _write_operations_csv(csv_path, plan["operations"])
        hash_path = directory / "ledger_sha256.txt"
        hash_path.write_text(plan["ledger_sha256"] + "\n", encoding="utf-8")
        outputs[name] = json_path
    return outputs


def apply_mapping_plan(*, session: Session, plan: dict[str, Any]) -> dict[str, Any]:
    _validate_plan(plan, MAPPING_BATCH)
    existing_rows = list(session.scalars(select(MainContractMap).where(
        MainContractMap.instrument_symbol == "jm",
        MainContractMap.trade_date.in_(MAPPING_DATES),
        MainContractMap.rank == 1,
    )))
    existing_by_date: dict[date, list[MainContractMap]] = {}
    for row in existing_rows:
        existing_by_date.setdefault(row.trade_date, []).append(row)
    inserted: list[int] = []
    unchanged: list[int] = []
    for operation in plan["operations"]:
        trade_date = date.fromisoformat(operation["trade_date"])
        state, existing_id = _mapping_operation_state(
            existing_by_date.get(trade_date, []), operation
        )
        if state == "noop":
            assert existing_id is not None
            unchanged.append(existing_id)
            continue
        row = MainContractMap(
            instrument_symbol="jm", trade_date=trade_date, rank=1,
            contract_code="JM2609", rule="volume_open_interest", provider="rqdata", data_version=MAPPING_VERSION,
            raw_payload={"task_id": TASK_ID, "batch_id": MAPPING_BATCH, "source_evidence": operation["source_evidence"]},
        )
        session.add(row)
        session.flush()
        inserted.append(row.id)
    session.commit()
    return {
        "inserted_ids": inserted,
        "inserted_count": len(inserted),
        "unchanged_ids": unchanged,
        "unchanged_count": len(unchanged),
    }


def _mapping_operation_state(
    existing_rows: list[Any], operation: dict[str, Any]
) -> tuple[str, int | None]:
    if not existing_rows:
        return "insert", None
    exact = [
        row
        for row in existing_rows
        if row.contract_code == operation["contract_code"]
        and row.provider == operation["provider"]
        and row.rule == operation["rule"]
        and row.rank == operation["rank"]
        and row.data_version == operation["data_version"]
    ]
    if len(existing_rows) == 1 and len(exact) == 1:
        return "noop", exact[0].id
    raise ValueError(
        f"mapping before-state drift for {operation['trade_date']}: "
        f"existing_ids={[row.id for row in existing_rows]}"
    )


def apply_manifest_plan(*, project_root: Path, session: Session, plan: dict[str, Any]) -> dict[str, Any]:
    _validate_plan(plan, MANIFEST_BATCH)
    root = project_root.resolve(strict=False)
    manifest = root / "data/manifests/actual_dominant_roll_006_manifest_repair_001.csv"
    if manifest.exists():
        raise FileExistsError(f"refusing to overwrite {manifest}")
    manifest_rows = [row for row in plan["operations"] if row["operation"] == "add_manifest_row"]
    supersedes = [row for row in plan["operations"] if row["operation"] == "mark_superseded"]
    if len(manifest_rows) != 10 or len(supersedes) != 3:
        raise ValueError("manifest operation count drift")
    for operation in supersedes:
        loser = session.get(MarketDataFile, operation["market_data_file_id"])
        winner = session.get(MarketDataFile, operation["winner_id"])
        if loser is None or winner is None or loser.data_role != "primary" or winner.data_role != "primary":
            raise ValueError("supersede before-state drift")
        loser.data_role = "superseded"
    staged = manifest.with_suffix(".csv.staging")
    _write_manifest_csv(staged, manifest_rows)
    session.flush()
    staged.replace(manifest)
    try:
        session.commit()
    except Exception:
        manifest.unlink(missing_ok=True)
        session.rollback()
        raise
    return {"manifest_path": str(manifest), "manifest_rows": 10, "superseded_ids": [row["market_data_file_id"] for row in supersedes]}


def load_plan(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_plan(plan: dict[str, Any], batch_id: str) -> None:
    if plan.get("task_id") != TASK_ID or plan.get("batch_id") != batch_id:
        raise ValueError("task or batch mismatch")
    if ledger_sha256(plan.get("operations", [])) != plan.get("ledger_sha256"):
        raise ValueError("ledger sha256 mismatch")


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_operations_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value for key, value in row.items()})


def _write_manifest_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ("period", "provider", "product", "actual_contract", "data_role", "quality_status", "status", "min_datetime", "max_datetime", "checksum", "standard_path", "market_data_file_id", "quality_report_ids", "data_version")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "period": row["period"], "provider": "rqdata", "product": row["product"],
                "actual_contract": row.get("contract") or row["contract_code"], "data_role": "primary", "quality_status": "passed",
                "status": "success", "min_datetime": row["start_time"], "max_datetime": row["end_time"],
                "checksum": row["checksum"], "standard_path": row["standard_path"],
                "market_data_file_id": row["market_data_file_id"],
                "quality_report_ids": json.dumps(row["quality_report_ids"]), "data_version": row["data_version"],
            })


def _build_local_parquet(*, source: Path, output: Path, period: str, data_version: str) -> None:
    temporary = output.with_suffix(".parquet.staging")
    source_sql = str(source).replace("'", "''")
    output_sql = str(temporary).replace("'", "''")
    created = "2026-07-18T00:00:00+08:00"
    if period == "1m":
        query = f"""
            SELECT 'jm' AS symbol, 'JM2609' AS contract, 'DCE' AS exchange, 'JM2609.DCE' AS vt_symbol,
                   datetime, CAST(trading_date AS DATE) AS trading_day, '1m' AS "interval", '1m' AS period,
                   open, high, low, close, volume, total_turnover AS turnover, open_interest,
                   'rqdata' AS "source", 'rqdata' AS provider, 'primary' AS data_role, 'passed' AS quality_status,
                   '{data_version}' AS data_version, 'JM2609' AS source_contract,
                   TIMESTAMPTZ '{created}' AS created_at
            FROM read_parquet('{source_sql}')
            WHERE order_book_id='JM2609' AND CAST(trading_date AS DATE) BETWEEN DATE '2026-07-08' AND DATE '2026-07-10'
            ORDER BY datetime
        """
    else:
        query = f"""
            SELECT 'jm' AS symbol, 'JM2609' AS contract, 'DCE' AS exchange, 'JM2609.DCE' AS vt_symbol,
                   datetime, CAST(date AS DATE) AS trading_day, '1d' AS "interval", '1d' AS period,
                   open, high, low, close, volume, total_turnover AS turnover, open_interest,
                   'rqdata' AS "source", 'rqdata' AS provider, 'primary' AS data_role, 'passed' AS quality_status,
                   '{data_version}' AS data_version, 'JM2609' AS source_contract,
                   TIMESTAMPTZ '{created}' AS created_at, '1d' AS source_interval, 1::BIGINT AS source_bar_count
            FROM read_parquet('{source_sql}')
            WHERE order_book_id='JM2609' AND CAST(date AS DATE) BETWEEN DATE '2026-07-08' AND DATE '2026-07-10'
            ORDER BY datetime
        """
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(f"COPY ({query}) TO '{output_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    temporary.replace(output)


def _parquet_facts(path: Path) -> dict[str, Any]:
    with duckdb.connect(database=":memory:") as connection:
        row = connection.execute(
            """SELECT count(*), min(datetime), max(datetime), min(trading_day), max(trading_day),
                      count(*)-count(DISTINCT datetime),
                      sum(CASE WHEN high < greatest(open,close,low) OR low > least(open,close,high) THEN 1 ELSE 0 END)
               FROM read_parquet(?)""",
            [str(path)],
        ).fetchone()
    assert row is not None
    return {
        "row_count": int(row[0]), "min_datetime": row[1], "max_datetime": row[2],
        "min_trading_day": row[3], "max_trading_day": row[4],
        "duplicate_count": int(row[5]), "invalid_ohlc_count": int(row[6] or 0),
    }


def _matches_passed_main(actual: Path, main: Path) -> bool:
    columns = "datetime,trading_day,open,high,low,close,volume,turnover,open_interest"
    with duckdb.connect(database=":memory:") as connection:
        left = connection.execute(
            f"SELECT count(*) FROM (SELECT {columns} FROM read_parquet(?) EXCEPT ALL SELECT {columns} FROM read_parquet(?) WHERE trading_day BETWEEN DATE '2026-07-08' AND DATE '2026-07-10')",
            [str(actual), str(main)],
        ).fetchone()[0]
        right = connection.execute(
            f"SELECT count(*) FROM (SELECT {columns} FROM read_parquet(?) WHERE trading_day BETWEEN DATE '2026-07-08' AND DATE '2026-07-10' EXCEPT ALL SELECT {columns} FROM read_parquet(?))",
            [str(main), str(actual)],
        ).fetchone()[0]
    return left == 0 and right == 0
