"""Exact-scope contract for the 2026-08 product retirement.

This module is intentionally product-specific.  It must not become a generic
retirement selector: every destructive operation is bound to the frozen set
below and to an exact inventory packet generated later in the workflow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from sqlalchemy import JSON, MetaData, Table, delete, inspect, select, tuple_
from sqlalchemy.engine import Connection


RETIRED_PRODUCTS: dict[str, str] = {
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

ACTIVE_PRODUCT_COUNT = 69
_CONTRACT_PRODUCT = re.compile(r"^([A-Z]+(?:_F)?)(?:[0-9]{2,4})?$")
_PRODUCT_COLUMNS = frozenset(
    {
        "product",
        "symbol",
        "instrument_symbol",
        "underlying_symbol",
        "underlying_order_book_id",
    }
)
_CONTRACT_COLUMNS = frozenset(
    {
        "contract",
        "contract_code",
        "contract_or_series",
        "dominant_contract",
        "instrument_id",
        "main_contract",
        "order_book_id",
    }
)
_PATH_COLUMNS = frozenset(
    {
        "file_path",
        "file_uri",
        "manifest_uri",
        "source_file",
    }
)
_STATE_COLUMNS = frozenset({"status", "binding_status", "is_active"})
_ACTIVE_TASK_TABLES = frozenset(
    {"backtest_tasks", "data_download_tasks", "signal_scan_tasks"}
)
_ACTIVE_TASK_STATUSES = frozenset({"pending", "running", "retrying"})


@dataclass(frozen=True)
class RetirementFile:
    root: str
    relative_path: str
    absolute_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class RetirementDatabaseRow:
    table: str
    primary_key: tuple[tuple[str, Any], ...]
    identity_columns: tuple[str, ...]
    identity_digest: str
    reasons: tuple[str, ...]
    status: str | None = None


class ProductRetirementError(ValueError):
    """Fail-closed product retirement contract error."""


def normalize_product(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def contract_product(value: str | None) -> str | None:
    """Return an exact product code from a concrete or continuous identity."""

    normalized = str(value or "").strip().upper()
    if not normalized:
        return None
    if normalized.endswith(".MAIN"):
        normalized = normalized[: -len(".MAIN")]
    elif "." in normalized:
        normalized = normalized.rsplit(".", maxsplit=1)[-1]
    match = _CONTRACT_PRODUCT.fullmatch(normalized)
    return match.group(1).lower() if match is not None else None


def is_retired_identity(
    *,
    product: str | None = None,
    contract: str | None = None,
) -> bool:
    product_key = normalize_product(product)
    contract_key = contract_product(contract)
    return bool(
        (product_key is not None and product_key in RETIRED_PRODUCTS)
        or (contract_key is not None and contract_key in RETIRED_PRODUCTS)
    )


def load_active_products(path: Path) -> tuple[str, ...]:
    if not path.is_file() or path.is_symlink():
        raise ProductRetirementError("PRODUCT_RETIREMENT_ACTIVE_PRODUCTS_INVALID")
    products = tuple(
        normalized
        for raw in path.read_text(encoding="utf-8").splitlines()
        if (normalized := normalize_product(raw)) is not None
    )
    if len(products) != ACTIVE_PRODUCT_COUNT or len(set(products)) != len(products):
        raise ProductRetirementError("PRODUCT_RETIREMENT_ACTIVE_PRODUCT_COUNT_MISMATCH")
    if set(products) & RETIRED_PRODUCTS.keys():
        raise ProductRetirementError("PRODUCT_RETIREMENT_ACTIVE_SET_OVERLAP")
    return products


def inventory_files(
    roots: Mapping[str, Path],
) -> tuple[tuple[RetirementFile, ...], tuple[str, ...]]:
    entries: list[RetirementFile] = []
    blockers: set[str] = set()
    for label, configured_root in sorted(roots.items()):
        root = configured_root.absolute()
        if not root.is_dir() or root.is_symlink():
            blockers.add(f"invalid_root:{label}:{root}")
            continue
        resolved_root = root.resolve(strict=True)
        for directory, directory_names, file_names in os.walk(resolved_root, followlinks=False):
            base = Path(directory)
            retained_directories: list[str] = []
            for name in sorted(directory_names):
                child = base / name
                if child.is_symlink():
                    blockers.add(f"symlink:{label}:{child}")
                else:
                    retained_directories.append(name)
            directory_names[:] = retained_directories
            for name in sorted(file_names):
                path = base / name
                if not _path_has_retired_partition(
                    path.relative_to(resolved_root),
                    root_label=label,
                ):
                    continue
                if path.is_symlink() or not path.is_file():
                    blockers.add(f"invalid_file:{label}:{path}")
                    continue
                stat_result = path.stat()
                if stat_result.st_nlink != 1:
                    blockers.add(f"shared_inode:{label}:{path}")
                    continue
                entries.append(
                    RetirementFile(
                        root=label,
                        relative_path=path.relative_to(resolved_root).as_posix(),
                        absolute_path=str(path),
                        size_bytes=stat_result.st_size,
                        sha256=_file_sha256(path),
                    )
                )
    return (
        tuple(sorted(entries, key=lambda item: (item.root, item.relative_path))),
        tuple(sorted(blockers)),
    )


def inventory_database(
    connection: Connection,
) -> tuple[tuple[RetirementDatabaseRow, ...], tuple[str, ...]]:
    inspector = inspect(connection)
    metadata = MetaData()
    table_names = tuple(sorted(inspector.get_table_names()))
    reflected = {
        name: Table(name, metadata, autoload_with=connection)
        for name in table_names
    }
    selected: dict[tuple[str, tuple[tuple[str, Any], ...]], RetirementDatabaseRow] = {}
    blockers: set[str] = set()

    for table_name, table in reflected.items():
        scalar_candidate_names = tuple(
            name
            for name in table.c.keys()
            if name in _PRODUCT_COLUMNS | _CONTRACT_COLUMNS | _PATH_COLUMNS
        )
        json_names = tuple(
            column.name for column in table.c if isinstance(column.type, JSON)
        )
        candidate_names = tuple(dict.fromkeys((*scalar_candidate_names, *json_names)))
        if not candidate_names:
            continue
        primary_names = tuple(column.name for column in table.primary_key.columns)
        if not primary_names:
            blockers.add(f"table_without_primary_key:{table_name}")
            continue
        identity_names = tuple(
            dict.fromkeys(
                (
                    *candidate_names,
                    *(name for name in table.c.keys() if name in _STATE_COLUMNS),
                )
            )
        )
        statement = select(*(table.c[name] for name in (*primary_names, *identity_names)))
        for row in connection.execute(statement).mappings():
            reasons = _database_match_reasons(
                row,
                scalar_candidate_names,
                json_names=json_names,
            )
            if reasons:
                item = _database_row(table_name, primary_names, identity_names, row, reasons)
                selected[(item.table, item.primary_key)] = item

    changed = True
    while changed:
        changed = False
        targeted_primary_keys = _targeted_primary_keys(selected)
        for table_name, table in reflected.items():
            primary_names = tuple(column.name for column in table.primary_key.columns)
            if not primary_names:
                continue
            scalar_candidate_names = tuple(
                name
                for name in table.c.keys()
                if name in _PRODUCT_COLUMNS | _CONTRACT_COLUMNS | _PATH_COLUMNS
            )
            json_names = tuple(
                column.name for column in table.c if isinstance(column.type, JSON)
            )
            candidate_names = tuple(dict.fromkeys((*scalar_candidate_names, *json_names)))
            state_names = tuple(name for name in table.c.keys() if name in _STATE_COLUMNS)
            for foreign_key in inspector.get_foreign_keys(table_name):
                parent = str(foreign_key.get("referred_table") or "")
                constrained = tuple(foreign_key.get("constrained_columns") or ())
                referred = tuple(foreign_key.get("referred_columns") or ())
                parent_keys = targeted_primary_keys.get(parent, set())
                if not parent_keys or not constrained or len(constrained) != len(referred):
                    continue
                columns = tuple(dict.fromkeys((*primary_names, *candidate_names, *state_names, *constrained)))
                statement = select(*(table.c[name] for name in columns))
                for row in connection.execute(statement).mappings():
                    parent_key = tuple((name, row[child]) for child, name in zip(constrained, referred, strict=True))
                    if parent_key not in parent_keys:
                        continue
                    reason = f"foreign_key:{table_name}->{parent}"
                    item = _database_row(
                        table_name,
                        primary_names,
                        tuple(dict.fromkeys((*candidate_names, *state_names, *constrained))),
                        row,
                        (reason,),
                    )
                    key = (item.table, item.primary_key)
                    if key not in selected:
                        selected[key] = item
                        changed = True

    for item in selected.values():
        status = str(item.status or "").strip().lower()
        if item.table in _ACTIVE_TASK_TABLES and status in _ACTIVE_TASK_STATUSES:
            primary = ",".join(f"{name}={value}" for name, value in item.primary_key)
            blockers.add(f"active_task:{item.table}:{primary}:{status}")

    return (
        tuple(sorted(selected.values(), key=_database_row_sort_key)),
        tuple(sorted(blockers)),
    )


def build_inventory_packet(
    *,
    files: Sequence[RetirementFile],
    database_rows: Sequence[RetirementDatabaseRow],
    blockers: Sequence[str],
    code_sha: str,
    runtime_sha: str,
    database_revision: str,
    generated_at: str,
) -> dict[str, Any]:
    _require_sha(code_sha, "code")
    _require_sha(runtime_sha, "runtime")
    product_rows = [
        {"code": code, "name_zh": RETIRED_PRODUCTS[code]}
        for code in sorted(RETIRED_PRODUCTS)
    ]
    product_digest = _json_sha256(product_rows)
    file_rows = [asdict(item) for item in sorted(files, key=lambda item: (item.root, item.relative_path))]
    database_payload = [asdict(item) for item in sorted(database_rows, key=_database_row_sort_key)]
    normalized_blockers = sorted(set(blockers))
    return {
        "schema_version": 1,
        "command": "product-retirement.inventory",
        "generated_at": generated_at,
        "status": "ready_for_exact_approval" if not normalized_blockers else "blocked",
        "writes_authorized": False,
        "scope": {
            "retired_product_count": len(product_rows),
            "retired_products": product_rows,
            "retired_products_digest": product_digest,
            "active_product_count": ACTIVE_PRODUCT_COUNT,
        },
        "bound_facts": {
            "code_sha": code_sha,
            "runtime_sha": runtime_sha,
            "database_revision": database_revision,
        },
        "summary": {
            "blocker_count": len(normalized_blockers),
            "database_row_count": len(database_payload),
            "database_rows_sha256": database_rows_digest(database_rows),
            "file_count": len(file_rows),
            "file_bytes": sum(item["size_bytes"] for item in file_rows),
            "files_sha256": retirement_files_digest(files),
        },
        "blockers": normalized_blockers,
        "files": file_rows,
        "database_rows": database_payload,
    }


def packet_digest(packet: Mapping[str, Any]) -> str:
    return _json_sha256(packet)


def database_rows_digest(rows: Sequence[RetirementDatabaseRow]) -> str:
    digest = sha256()
    for row in sorted(rows, key=_database_row_sort_key):
        digest.update(_canonical_json(asdict(row)))
        digest.update(b"\n")
    return digest.hexdigest()


def retirement_files_digest(files: Sequence[RetirementFile]) -> str:
    digest = sha256()
    for item in sorted(files, key=lambda row: (row.root, row.relative_path)):
        digest.update(_canonical_json(asdict(item)))
        digest.update(b"\n")
    return digest.hexdigest()


def externalize_database_rows(
    packet: Mapping[str, Any],
    *,
    packet_path: Path,
    shard_size: int = 25_000,
) -> dict[str, Any]:
    if shard_size <= 0:
        raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_SIZE_INVALID")
    raw_rows = packet.get("database_rows")
    if not isinstance(raw_rows, list):
        raise ProductRetirementError("PRODUCT_RETIREMENT_DATABASE_ROWS_INVALID")
    rows = tuple(_database_row_from_payload(raw) for raw in raw_rows)
    if not rows:
        result = dict(packet)
        result["database_row_shards"] = []
        return result
    assets_root = packet_path.absolute().parent / f"{packet_path.name}.assets"
    if assets_root.exists() or assets_root.is_symlink():
        raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_ROOT_COLLISION")
    database_root = assets_root / "database"
    database_root.mkdir(parents=True)
    descriptors: list[dict[str, Any]] = []
    try:
        by_table: dict[str, list[RetirementDatabaseRow]] = {}
        for row in rows:
            by_table.setdefault(row.table, []).append(row)
        for table, table_rows in sorted(by_table.items()):
            ordered = sorted(table_rows, key=_database_row_sort_key)
            for index, offset in enumerate(range(0, len(ordered), shard_size), start=1):
                batch = ordered[offset : offset + shard_size]
                relative = Path(f"{packet_path.name}.assets") / "database" / f"{table}-{index:05d}.jsonl"
                path = packet_path.absolute().parent / relative
                data = b"".join(_canonical_json(asdict(row)) + b"\n" for row in batch)
                with path.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                descriptors.append(
                    {
                        "table": table,
                        "relative_path": relative.as_posix(),
                        "row_count": len(batch),
                        "sha256": sha256(data).hexdigest(),
                        "first_primary_key": asdict(batch[0])["primary_key"],
                        "last_primary_key": asdict(batch[-1])["primary_key"],
                    }
                )
    except Exception:
        _remove_created_tree(assets_root)
        raise
    result = dict(packet)
    result["database_rows"] = []
    result["database_row_shards"] = descriptors
    return result


def remove_database_row_assets(packet_path: Path) -> None:
    """Remove only the exact sidecar directory created for ``packet_path``."""

    assets_root = packet_path.absolute().parent / f"{packet_path.name}.assets"
    _remove_created_tree(assets_root)


def read_database_row_shards(
    packet: Mapping[str, Any],
    *,
    packet_root: Path,
    table: str | None = None,
):
    shards = packet.get("database_row_shards")
    if not shards:
        for raw in packet.get("database_rows", []):
            row = _database_row_from_payload(raw)
            if table is None or row.table == table:
                yield row
        return
    if packet.get("database_rows"):
        raise ProductRetirementError("PRODUCT_RETIREMENT_DATABASE_MANIFEST_AMBIGUOUS")
    resolved_root = packet_root.absolute().resolve(strict=True)
    total = 0
    expected_total = 0
    for descriptor in shards:
        if table is not None and descriptor["table"] != table:
            continue
        expected_total += int(descriptor["row_count"])
        relative = Path(str(descriptor["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_PATH_INVALID")
        path = resolved_root / relative
        if path.is_symlink() or not path.is_file():
            raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_MISSING")
        data = path.read_bytes()
        if sha256(data).hexdigest() != descriptor["sha256"]:
            raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_DIGEST_MISMATCH")
        count = 0
        for line in data.splitlines():
            if not line:
                raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_EMPTY_LINE")
            payload = json.loads(line)
            row = _database_row_from_payload(payload)
            if row.table != descriptor["table"]:
                raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_TABLE_MISMATCH")
            count += 1
            total += 1
            yield row
        if count != int(descriptor["row_count"]):
            raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_ROW_COUNT_MISMATCH")
    if table is None:
        expected_total = int(packet["summary"]["database_row_count"])
    if total != expected_total:
        raise ProductRetirementError("PRODUCT_RETIREMENT_SHARD_TOTAL_COUNT_MISMATCH")


def apply_retirement_packet(
    connection: Connection,
    *,
    packet: Mapping[str, Any],
    expected_packet_digest: str,
    approval: Mapping[str, Any],
    roots: Mapping[str, Path],
    code_sha: str,
    runtime_sha: str,
    database_revision: str,
    shutdown_receipt_digest: str,
    now: str,
    packet_root: Path | None = None,
) -> dict[str, Any]:
    _validate_apply_contract(
        packet=packet,
        expected_packet_digest=expected_packet_digest,
        approval=approval,
        code_sha=code_sha,
        runtime_sha=runtime_sha,
        database_revision=database_revision,
        shutdown_receipt_digest=shutdown_receipt_digest,
        now=now,
    )
    file_pairs = _preflight_packet_files(packet, roots)
    manifest_root = (packet_root or Path.cwd()).absolute()
    target_tables = _packet_database_tables(packet)
    if connection.in_transaction():
        connection.rollback()
    connection = connection.execution_options(isolation_level="SERIALIZABLE")

    staged: list[tuple[Path, Path]] = []
    try:
        for original, staged_path in file_pairs:
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            original.replace(staged_path)
            staged.append((original, staged_path))
        with connection.begin():
            _preflight_packet_database(
                connection,
                packet,
                packet_root=manifest_root,
            )
            reflected = _reflect_tables(connection)
            for table_name in _deletion_table_order(connection, target_tables):
                table = reflected[table_name]
                _delete_database_rows(
                    connection,
                    table,
                    read_database_row_shards(
                        packet,
                        packet_root=manifest_root,
                        table=table_name,
                    ),
                )
    except Exception:
        if connection.in_transaction():
            connection.rollback()
        _restore_staged_files(staged)
        raise

    purge_errors: list[str] = []
    for _, staged_path in staged:
        try:
            staged_path.unlink()
            _remove_empty_parents(staged_path.parent, stop=Path(roots[_root_label_for_staged(staged_path, roots)]).resolve(strict=True))
        except OSError as exc:
            purge_errors.append(f"{staged_path}:{type(exc).__name__}")
    if purge_errors:
        raise ProductRetirementError(
            "PRODUCT_RETIREMENT_FILE_PURGE_INCOMPLETE:" + ",".join(sorted(purge_errors))
        )
    return {
        "schema_version": 1,
        "command": "product-retirement.apply",
        "status": "applied",
        "packet_sha256": expected_packet_digest,
        "deleted_file_count": len(file_pairs),
        "deleted_file_bytes": sum(int(item["size_bytes"]) for item in packet["files"]),
        "deleted_database_row_count": int(packet["summary"]["database_row_count"]),
        "retired_products_digest": packet["scope"]["retired_products_digest"],
    }


def verify_retirement_scope(
    connection: Connection,
    *,
    roots: Mapping[str, Path],
) -> dict[str, Any]:
    files, file_blockers = inventory_files(roots)
    rows, database_blockers = inventory_database(connection)
    blockers = tuple(sorted({*file_blockers, *database_blockers}))
    return {
        "schema_version": 1,
        "command": "product-retirement.verify",
        "status": "passed" if not files and not rows and not blockers else "failed",
        "residual_file_count": len(files),
        "residual_database_row_count": len(rows),
        "blockers": list(blockers),
        "residual_files": [asdict(item) for item in files],
        "residual_database_rows": [asdict(item) for item in rows],
    }


def _path_has_retired_partition(
    relative: Path,
    *,
    root_label: str | None = None,
) -> bool:
    parts = relative.parts
    if root_label in {"processed", "v1b"} and parts:
        if normalize_product(parts[0]) in RETIRED_PRODUCTS:
            return True
    for part in parts:
        if "=" in part:
            key, value = part.split("=", maxsplit=1)
            if key.lower() in {"product", "symbol", "instrument_symbol"} and normalize_product(value) in RETIRED_PRODUCTS:
                return True
    for index, part in enumerate(parts[:-1]):
        if part.lower() in {"v1b", "products"} and normalize_product(parts[index + 1]) in RETIRED_PRODUCTS:
            return True
    return False


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _database_match_reasons(
    row: Mapping[str, Any],
    columns: Sequence[str],
    *,
    json_names: Sequence[str] = (),
) -> tuple[str, ...]:
    reasons: list[str] = []
    for name in columns:
        value = row[name]
        if name in _PRODUCT_COLUMNS and normalize_product(value) in RETIRED_PRODUCTS:
            reasons.append(f"product:{name}")
        elif name in _CONTRACT_COLUMNS and contract_product(value) in RETIRED_PRODUCTS:
            reasons.append(f"contract:{name}")
        elif name in _PATH_COLUMNS and _text_path_has_retired_partition(value):
            reasons.append(f"path:{name}")
    for name in json_names:
        reasons.extend(_json_retired_reasons(row[name], prefix=name))
    return tuple(sorted(set(reasons)))


def _json_retired_reasons(value: Any, *, prefix: str) -> list[str]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            path = f"{prefix}.{key}"
            if key in _PRODUCT_COLUMNS and normalize_product(child) in RETIRED_PRODUCTS:
                reasons.append(f"json_product:{path}")
            elif key in _CONTRACT_COLUMNS and contract_product(child) in RETIRED_PRODUCTS:
                reasons.append(f"json_contract:{path}")
            elif key in _PATH_COLUMNS and _text_path_has_retired_partition(child):
                reasons.append(f"json_path:{path}")
            reasons.extend(_json_retired_reasons(child, prefix=path))
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            reasons.extend(_json_retired_reasons(child, prefix=f"{prefix}[{index}]"))
    return reasons


def _text_path_has_retired_partition(value: Any) -> bool:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return False
    return _path_has_retired_partition(Path(text.lstrip("/")))


def _database_row(
    table: str,
    primary_names: Sequence[str],
    identity_names: Sequence[str],
    row: Mapping[str, Any],
    reasons: Sequence[str],
) -> RetirementDatabaseRow:
    primary_key = tuple((name, row[name]) for name in primary_names)
    identity = {name: _json_value(row[name]) for name in identity_names}
    return RetirementDatabaseRow(
        table=table,
        primary_key=primary_key,
        identity_columns=tuple(identity),
        identity_digest=_json_sha256(identity),
        reasons=tuple(sorted(set(reasons))),
        status=(
            str(identity["status"]).strip().lower()
            if identity.get("status") is not None
            else None
        ),
    )


def _targeted_primary_keys(
    selected: Mapping[tuple[str, tuple[tuple[str, Any], ...]], RetirementDatabaseRow],
) -> dict[str, set[tuple[tuple[str, Any], ...]]]:
    result: dict[str, set[tuple[tuple[str, Any], ...]]] = {}
    for row in selected.values():
        result.setdefault(row.table, set()).add(row.primary_key)
    return result


def _database_row_sort_key(row: RetirementDatabaseRow) -> tuple[str, str]:
    return row.table, json.dumps(row.primary_key, ensure_ascii=False, sort_keys=True, default=str)


def _database_row_from_payload(raw: Mapping[str, Any]) -> RetirementDatabaseRow:
    return RetirementDatabaseRow(
        table=str(raw["table"]),
        primary_key=tuple((str(name), value) for name, value in raw["primary_key"]),
        identity_columns=tuple(str(name) for name in raw["identity_columns"]),
        identity_digest=str(raw["identity_digest"]),
        reasons=tuple(str(reason) for reason in raw["reasons"]),
        status=(
            str(raw["status"]).strip().lower()
            if raw.get("status") is not None
            else None
        ),
    )


def _remove_created_tree(root: Path) -> None:
    if not root.exists() or root.is_symlink():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    root.rmdir()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(child) for child in value]
    method = getattr(value, "isoformat", None)
    return method() if callable(method) else str(value)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_value,
    ).encode("utf-8")


def _json_sha256(value: Any) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _require_sha(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ProductRetirementError(f"PRODUCT_RETIREMENT_{label.upper()}_SHA_INVALID")


def _validate_apply_contract(
    *,
    packet: Mapping[str, Any],
    expected_packet_digest: str,
    approval: Mapping[str, Any],
    code_sha: str,
    runtime_sha: str,
    database_revision: str,
    shutdown_receipt_digest: str,
    now: str,
) -> None:
    if packet_digest(packet) != expected_packet_digest:
        raise ProductRetirementError("PRODUCT_RETIREMENT_PACKET_DIGEST_MISMATCH")
    if packet.get("status") != "ready_for_exact_approval" or packet.get("blockers"):
        raise ProductRetirementError("PRODUCT_RETIREMENT_PACKET_NOT_APPROVABLE")
    expected = {
        "command": "product-retirement.apply",
        "decision": "approved",
        "packet_sha256": expected_packet_digest,
        "code_sha": code_sha,
        "runtime_sha": runtime_sha,
        "database_revision": database_revision,
        "retired_products_digest": packet["scope"]["retired_products_digest"],
        "shutdown_receipt_sha256": shutdown_receipt_digest,
    }
    for name, value in expected.items():
        if approval.get(name) != value:
            raise ProductRetirementError(f"PRODUCT_RETIREMENT_APPROVAL_{name.upper()}_MISMATCH")
    if packet.get("bound_facts") != {
        "code_sha": code_sha,
        "runtime_sha": runtime_sha,
        "database_revision": database_revision,
    }:
        raise ProductRetirementError("PRODUCT_RETIREMENT_BOUND_FACT_DRIFT")
    if re.fullmatch(r"[0-9a-f]{64}", shutdown_receipt_digest) is None:
        raise ProductRetirementError("PRODUCT_RETIREMENT_SHUTDOWN_RECEIPT_DIGEST_INVALID")
    try:
        expires_at = datetime.fromisoformat(str(approval["expires_at"]))
        current = datetime.fromisoformat(now)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductRetirementError("PRODUCT_RETIREMENT_APPROVAL_EXPIRY_INVALID") from exc
    if expires_at.tzinfo is None or current.tzinfo is None or current >= expires_at:
        raise ProductRetirementError("PRODUCT_RETIREMENT_APPROVAL_EXPIRED")


def _preflight_packet_files(
    packet: Mapping[str, Any],
    roots: Mapping[str, Path],
) -> list[tuple[Path, Path]]:
    current_files, current_blockers = inventory_files(roots)
    if current_blockers:
        raise ProductRetirementError(
            "PRODUCT_RETIREMENT_CURRENT_FILE_INVENTORY_BLOCKED:"
            + ",".join(current_blockers)
        )
    summary = packet.get("summary", {})
    if (
        len(current_files) != int(summary.get("file_count", -1))
        or retirement_files_digest(current_files) != summary.get("files_sha256")
    ):
        raise ProductRetirementError("PRODUCT_RETIREMENT_FILE_SCOPE_DRIFT")
    result: list[tuple[Path, Path]] = []
    digest = packet_digest(packet)
    for raw in packet.get("files", []):
        label = str(raw["root"])
        if label not in roots:
            raise ProductRetirementError(f"PRODUCT_RETIREMENT_FILE_ROOT_UNKNOWN:{label}")
        root = roots[label].absolute()
        if not root.is_dir() or root.is_symlink():
            raise ProductRetirementError(f"PRODUCT_RETIREMENT_FILE_ROOT_INVALID:{label}")
        resolved_root = root.resolve(strict=True)
        relative = Path(str(raw["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ProductRetirementError("PRODUCT_RETIREMENT_FILE_PATH_INVALID")
        original = resolved_root / relative
        if str(original) != str(raw["absolute_path"]):
            raise ProductRetirementError("PRODUCT_RETIREMENT_FILE_ROOT_DRIFT")
        if original.is_symlink() or not original.is_file():
            raise ProductRetirementError("PRODUCT_RETIREMENT_FILE_MISSING")
        stat_result = original.stat()
        if stat_result.st_nlink != 1:
            raise ProductRetirementError("PRODUCT_RETIREMENT_FILE_SHARED_INODE")
        if stat_result.st_size != int(raw["size_bytes"]) or _file_sha256(original) != raw["sha256"]:
            raise ProductRetirementError("PRODUCT_RETIREMENT_FILE_DRIFT")
        staged = resolved_root / ".product-retirement-staging" / digest / relative
        if staged.exists() or staged.is_symlink():
            raise ProductRetirementError("PRODUCT_RETIREMENT_STAGING_COLLISION")
        result.append((original, staged))
    return result


def _preflight_packet_database(
    connection: Connection,
    packet: Mapping[str, Any],
    *,
    packet_root: Path,
) -> None:
    reflected = _reflect_tables(connection)
    current_rows, current_blockers = inventory_database(connection)
    if current_blockers:
        raise ProductRetirementError(
            "PRODUCT_RETIREMENT_CURRENT_DATABASE_INVENTORY_BLOCKED:"
            + ",".join(current_blockers)
        )
    summary = packet.get("summary", {})
    if (
        len(current_rows) != int(summary.get("database_row_count", -1))
        or database_rows_digest(current_rows) != summary.get("database_rows_sha256")
    ):
        raise ProductRetirementError("PRODUCT_RETIREMENT_DATABASE_SCOPE_DRIFT")
    count = 0
    manifest_digest = sha256()
    for row in read_database_row_shards(packet, packet_root=packet_root):
        table_name = row.table
        table = reflected.get(table_name)
        if table is None:
            raise ProductRetirementError(f"PRODUCT_RETIREMENT_DATABASE_TABLE_MISSING:{table_name}")
        primary_key = row.primary_key
        identity_columns = row.identity_columns
        if any(name not in table.c for name, _ in primary_key) or any(
            name not in table.c for name in identity_columns
        ):
            raise ProductRetirementError(f"PRODUCT_RETIREMENT_DATABASE_COLUMN_DRIFT:{table_name}")
        manifest_digest.update(_canonical_json(asdict(row)))
        manifest_digest.update(b"\n")
        count += 1
    if count != int(packet["summary"]["database_row_count"]):
        raise ProductRetirementError("PRODUCT_RETIREMENT_DATABASE_MANIFEST_COUNT_MISMATCH")
    if manifest_digest.hexdigest() != packet["summary"]["database_rows_sha256"]:
        raise ProductRetirementError("PRODUCT_RETIREMENT_DATABASE_MANIFEST_DIGEST_MISMATCH")


def _delete_database_rows(
    connection: Connection,
    table: Table,
    rows,
    *,
    batch_size: int = 500,
) -> None:
    primary_names = tuple(column.name for column in table.primary_key.columns)
    if not primary_names:
        raise ProductRetirementError(
            f"PRODUCT_RETIREMENT_DATABASE_TABLE_WITHOUT_PRIMARY_KEY:{table.name}"
        )
    batch: list[tuple[Any, ...]] = []

    def flush() -> None:
        if not batch:
            return
        if len(primary_names) == 1:
            predicate = table.c[primary_names[0]].in_([values[0] for values in batch])
        else:
            predicate = tuple_(*(table.c[name] for name in primary_names)).in_(batch)
        result = connection.execute(delete(table).where(predicate))
        if result.rowcount != len(batch):
            raise ProductRetirementError(
                f"PRODUCT_RETIREMENT_DATABASE_DELETE_COUNT_MISMATCH:{table.name}:"
                f"expected={len(batch)}:actual={result.rowcount}"
            )
        batch.clear()

    for row in rows:
        row_names = tuple(name for name, _ in row.primary_key)
        if row.table != table.name or row_names != primary_names:
            raise ProductRetirementError(
                f"PRODUCT_RETIREMENT_DATABASE_PRIMARY_KEY_DRIFT:{table.name}"
            )
        batch.append(tuple(value for _, value in row.primary_key))
        if len(batch) >= batch_size:
            flush()
    flush()


def _packet_database_tables(packet: Mapping[str, Any]) -> set[str]:
    shards = packet.get("database_row_shards") or []
    if shards:
        return {str(item["table"]) for item in shards}
    return {str(item["table"]) for item in packet.get("database_rows", [])}


def _reflect_tables(connection: Connection) -> dict[str, Table]:
    metadata = MetaData()
    return {
        name: Table(name, metadata, autoload_with=connection)
        for name in sorted(inspect(connection).get_table_names())
    }


def _deletion_table_order(connection: Connection, targets: set[str]) -> tuple[str, ...]:
    inspector = inspect(connection)
    parents: dict[str, set[str]] = {name: set() for name in targets}
    for child in targets:
        for foreign_key in inspector.get_foreign_keys(child):
            parent = str(foreign_key.get("referred_table") or "")
            if parent in targets and parent != child:
                parents[child].add(parent)
    order: list[str] = []
    remaining = {name: set(values) for name, values in parents.items()}
    while remaining:
        children = {parent for values in remaining.values() for parent in values}
        ready = sorted(name for name in remaining if name not in children)
        if not ready:
            raise ProductRetirementError("PRODUCT_RETIREMENT_DATABASE_FK_CYCLE")
        order.extend(ready)
        for name in ready:
            remaining.pop(name)
        for values in remaining.values():
            values.difference_update(ready)
    return tuple(order)


def _restore_staged_files(staged: Sequence[tuple[Path, Path]]) -> None:
    errors: list[str] = []
    for original, staged_path in reversed(staged):
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            staged_path.replace(original)
        except OSError as exc:
            errors.append(f"{original}:{type(exc).__name__}")
    if errors:
        raise ProductRetirementError(
            "PRODUCT_RETIREMENT_FILE_RESTORE_FAILED:" + ",".join(sorted(errors))
        )


def _root_label_for_staged(path: Path, roots: Mapping[str, Path]) -> str:
    matches = [
        label
        for label, root in roots.items()
        if path.is_relative_to(root.absolute().resolve(strict=True))
    ]
    if len(matches) != 1:
        raise ProductRetirementError("PRODUCT_RETIREMENT_STAGING_ROOT_AMBIGUOUS")
    return matches[0]


def _remove_empty_parents(path: Path, *, stop: Path) -> None:
    current = path
    while current != stop and current.is_relative_to(stop):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


__all__ = [
    "ACTIVE_PRODUCT_COUNT",
    "RETIRED_PRODUCTS",
    "ProductRetirementError",
    "RetirementDatabaseRow",
    "RetirementFile",
    "apply_retirement_packet",
    "build_inventory_packet",
    "contract_product",
    "database_rows_digest",
    "externalize_database_rows",
    "inventory_database",
    "inventory_files",
    "is_retired_identity",
    "load_active_products",
    "normalize_product",
    "packet_digest",
    "read_database_row_shards",
    "remove_database_row_assets",
    "retirement_files_digest",
    "verify_retirement_scope",
]
