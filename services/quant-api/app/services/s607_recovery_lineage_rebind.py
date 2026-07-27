"""Read-only lineage replacement for an unavailable S6-07 recovery receipt."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ORIGINAL_RECOVERY_APPROVAL_PACKET_HASH = (
    "443adda6d2b3f0e82edaeff1d72e9ff4"
    "a6d194b0f1d78928a034f175f513c2f3"
)
ORIGINAL_RECOVERY_RECEIPT_HASH = (
    "3d916810629a34f48cbdd488e6ace7ac5"
    "954fa16089362284d85db790f07f75d"
)
ORIGINAL_RECOVERY_RECEIPT_SHA256 = (
    "9aaf631703fcbbe93073ebb1161e4fe25"
    "c276c72668578787bf12630a243bf00"
)
FINAL_DEPLOYMENT_PACKET_HASH = (
    "63745f53a126718b02826ab8ae1d3a29"
    "d15bccf88a005563264ceb761ef35d94"
)
FINAL_REBIND_PACKET_HASH = (
    "00e604796e93e5fe49c2d0918730b093"
    "247b6a03aa747a60fac243aa17bb4360"
)
FINAL_REBIND_RECEIPT_HASH = (
    "9cf139cdbf41a7e22358498bda408b96"
    "dc5cbc45ae18af68049fa1e5bf4ca883"
)
FINAL_SERVICE_PARENT_HASH = (
    "f0316f262d207502b2d176dee68099830"
    "8ff1158bfd51559437643c889438b8b"
)
TRACKED_EVIDENCE_SHA256 = {
    "recovery_document": (
        "58c94e769f9f3b3514145778f9c1c25c"
        "a7500076ed43f5a640512f0f7d7259fb"
    ),
    "final_deployment_packet": (
        "6e6196c871a317cc13ee25b576031e96f"
        "67d9bb587182243d04e12a68ef0b495"
    ),
    "final_deployment_receipt": (
        "f59d00e1eb38702dcefa78a43bf839aaf"
        "568cb1d8b3cae58f81269465ae4fa85"
    ),
    "final_rebind_packet": (
        "1b977b6f4ab5acf13ed6f1b95768ad94"
        "633d4703ee82a6619387ca90dad9325e"
    ),
    "final_rebind_receipt": (
        "cbf710980cfb869a2a85d92ed4dfa697"
        "f44edc641a5d47be62e07508a65bfbf9"
    ),
    "final_service_parent": (
        "f772d483247ba0b2ee140c4ca282abe55"
        "f80f3f9b4e9b433bf9c7ebee3f16ff5"
    ),
}
RECOVERY_DOCUMENT_RELATIVE = Path(
    "docs/tasks/S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md"
)
FINAL_EVIDENCE_DIRECTORY_RELATIVE = Path(
    "data/reports/jm_live_signal_event_s6_08/htdy_schema_v3/"
    "20260726-f63b36365394"
)
TRACKED_EVIDENCE_PATHS = {
    "recovery_document": RECOVERY_DOCUMENT_RELATIVE,
    "final_deployment_packet": (
        FINAL_EVIDENCE_DIRECTORY_RELATIVE / "deployment_packet.json"
    ),
    "final_deployment_receipt": (
        FINAL_EVIDENCE_DIRECTORY_RELATIVE / "deployment_receipt.json"
    ),
    "final_rebind_packet": (
        FINAL_EVIDENCE_DIRECTORY_RELATIVE / "s6_07_rebind_packet.json"
    ),
    "final_rebind_receipt": (
        FINAL_EVIDENCE_DIRECTORY_RELATIVE / "s6_07_rebind_receipt.json"
    ),
    "final_service_parent": (
        FINAL_EVIDENCE_DIRECTORY_RELATIVE / "service_parent_packet.json"
    ),
}
FINAL_DATABASE_STATE_SHA256 = (
    "925bcfddfc7162ad14d0f92f775e8f6b"
    "b55df63d46411c8cc9a9c9afb4bb0369"
)
RECEIPT_FILENAME = "recovery_lineage_rebind_receipt.json"


class S607RecoveryLineageRebindError(RuntimeError):
    """Raised when tracked recovery lineage is incomplete or drifted."""


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = {
        str(key): deepcopy(item)
        for key, item in value.items()
        if key != "receipt_hash"
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def build_recovery_lineage_rebind_receipt(
    *,
    source: Mapping[str, Any],
    tracked_evidence: Mapping[str, Any],
    current_database_state: Mapping[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    _validate_source(source)
    _validate_tracked_evidence(tracked_evidence)
    _validate_database_state(current_database_state)
    if created_at.tzinfo is None:
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "task_id": "S6-07-DATABASE-RECOVERY-LINEAGE-REBIND",
        "status": "completed",
        "gate": "S6_07_RECOVERY_LINEAGE_REBIND_PASSED",
        "evidence_mode": "tracked_read_only_lineage_rebind_v1",
        "original_recovery": {
            "approval_packet_hash": (
                ORIGINAL_RECOVERY_APPROVAL_PACKET_HASH
            ),
            "receipt_hash": ORIGINAL_RECOVERY_RECEIPT_HASH,
            "sha256": ORIGINAL_RECOVERY_RECEIPT_SHA256,
            "original_file_available": False,
        },
        "source": deepcopy(dict(source)),
        "tracked_evidence": deepcopy(dict(tracked_evidence)),
        "database_state": deepcopy(dict(current_database_state)),
        "database_state_sha256": FINAL_DATABASE_STATE_SHA256,
        "migration_performed": False,
        "database_write_performed": False,
        "approval_r_rerun": False,
        "runtime_modified": False,
        "created_at": created_at.isoformat(),
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    return receipt


def verify_recovery_lineage_rebind_receipt(
    receipt: Mapping[str, Any],
    *,
    current_source: Mapping[str, Any],
    current_tracked_evidence: Mapping[str, Any],
    current_database_state: Mapping[str, Any],
) -> None:
    try:
        created_at = datetime.fromisoformat(
            str(receipt.get("created_at") or "")
        )
    except ValueError as exc:
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        ) from exc
    try:
        _validate_source(current_source)
        _validate_tracked_evidence(current_tracked_evidence)
        _validate_database_state(current_database_state)
    except S607RecoveryLineageRebindError:
        raise
    if (
        receipt.get("schema_version") != 1
        or receipt.get("task_id")
        != "S6-07-DATABASE-RECOVERY-LINEAGE-REBIND"
        or receipt.get("status") != "completed"
        or receipt.get("gate")
        != "S6_07_RECOVERY_LINEAGE_REBIND_PASSED"
        or receipt.get("evidence_mode")
        != "tracked_read_only_lineage_rebind_v1"
        or receipt.get("original_recovery")
        != {
            "approval_packet_hash": (
                ORIGINAL_RECOVERY_APPROVAL_PACKET_HASH
            ),
            "receipt_hash": ORIGINAL_RECOVERY_RECEIPT_HASH,
            "sha256": ORIGINAL_RECOVERY_RECEIPT_SHA256,
            "original_file_available": False,
        }
        or receipt.get("source") != dict(current_source)
        or receipt.get("tracked_evidence")
        != dict(current_tracked_evidence)
        or receipt.get("database_state")
        != dict(current_database_state)
        or receipt.get("database_state_sha256")
        != FINAL_DATABASE_STATE_SHA256
        or receipt.get("migration_performed") is not False
        or receipt.get("database_write_performed") is not False
        or receipt.get("approval_r_rerun") is not False
        or receipt.get("runtime_modified") is not False
        or created_at.tzinfo is None
        or receipt.get("receipt_hash") != canonical_hash(receipt)
    ):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )


def write_recovery_lineage_receipt_create_only(
    path: Path,
    receipt: Mapping[str, Any],
) -> None:
    if path.name != RECEIPT_FILENAME or path.is_symlink():
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise S607RecoveryLineageRebindError(
            "create_only_path_exists"
        ) from exc
    try:
        payload = json.dumps(
            dict(receipt),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_recovery_lineage_rebind_identity(
    path: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    if (
        path.name != RECEIPT_FILENAME
        or path.is_symlink()
        or sha256_file(path) != expected_sha256
    ):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        ) from exc
    if not isinstance(value, Mapping):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    source = value.get("source")
    evidence = value.get("tracked_evidence")
    database_state = value.get("database_state")
    if not all(
        isinstance(item, Mapping)
        for item in (source, evidence, database_state)
    ):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    verify_recovery_lineage_rebind_receipt(
        value,
        current_source=source,
        current_tracked_evidence=evidence,
        current_database_state=database_state,
    )
    return {
        "path": str(path.resolve(strict=True)),
        "sha256": expected_sha256,
        "receipt_hash": value["receipt_hash"],
        "evidence_mode": value["evidence_mode"],
        "source_commit": source["commit"],
        "original_receipt_hash": ORIGINAL_RECOVERY_RECEIPT_HASH,
        "original_receipt_sha256": ORIGINAL_RECOVERY_RECEIPT_SHA256,
    }


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        ) from exc


def validate_recovery_evidence_identity(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    path = Path(str(value.get("path") or ""))
    if (
        not path.is_absolute()
        or not _hex(value.get("sha256"), 64)
        or not _hex(value.get("receipt_hash"), 64)
    ):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    if (
        path.name == "recovery_receipt.json"
        and value.get("evidence_mode") in {None, "original_receipt_v1"}
    ):
        return
    if (
        path.name == RECEIPT_FILENAME
        and value.get("evidence_mode")
        == "tracked_read_only_lineage_rebind_v1"
        and _hex(value.get("source_commit"), 40)
        and value.get("original_receipt_hash")
        == ORIGINAL_RECOVERY_RECEIPT_HASH
        and value.get("original_receipt_sha256")
        == ORIGINAL_RECOVERY_RECEIPT_SHA256
    ):
        return
    raise S607RecoveryLineageRebindError(
        "recovery_lineage_rebind_invalid"
    )


def collect_tracked_recovery_evidence(
    source_root: Path,
) -> dict[str, dict[str, Any]]:
    root = source_root.resolve(strict=True)
    values: dict[str, dict[str, Any]] = {}
    payloads: dict[str, Mapping[str, Any]] = {}
    for name, relative in TRACKED_EVIDENCE_PATHS.items():
        path = root / relative
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != TRACKED_EVIDENCE_SHA256[name]
        ):
            raise S607RecoveryLineageRebindError(
                "recovery_lineage_rebind_invalid"
            )
        identity: dict[str, Any] = {
            "path": str(path.resolve(strict=True)),
            "sha256": TRACKED_EVIDENCE_SHA256[name],
        }
        if name != "recovery_document":
            payload = _read_json_mapping(path)
            payloads[name] = payload
        values[name] = identity
    deployment_packet = payloads["final_deployment_packet"]
    deployment_receipt = payloads["final_deployment_receipt"]
    rebind_packet = payloads["final_rebind_packet"]
    rebind_receipt = payloads["final_rebind_receipt"]
    service_parent = payloads["final_service_parent"]
    if (
        deployment_packet.get("packet_hash")
        != FINAL_DEPLOYMENT_PACKET_HASH
        or deployment_receipt.get("approval_packet_hash")
        != FINAL_DEPLOYMENT_PACKET_HASH
        or deployment_receipt.get("status") != "completed"
        or deployment_receipt.get("target_commit")
        != "f63b3636539435ac9c6849e2dcf478800adf44e9"
        or deployment_receipt.get("database_unchanged") is not True
        or deployment_receipt.get("flags_safe") is not True
        or deployment_receipt.get("health_verified") is not True
        or deployment_receipt.get("rollback") is not False
        or rebind_packet.get("packet_hash") != FINAL_REBIND_PACKET_HASH
        or rebind_packet.get("deployment_packet_sha256")
        != FINAL_DEPLOYMENT_PACKET_HASH
        or rebind_packet.get("target_runtime_commit")
        != "f63b3636539435ac9c6849e2dcf478800adf44e9"
        or rebind_receipt.get("receipt_hash")
        != FINAL_REBIND_RECEIPT_HASH
        or service_parent.get("packet_hash") != FINAL_SERVICE_PARENT_HASH
    ):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    for container in (rebind_packet, service_parent.get("bindings")):
        if not isinstance(container, Mapping):
            raise S607RecoveryLineageRebindError(
                "recovery_lineage_rebind_invalid"
            )
        recovery = container.get("database_recovery_receipt")
        if (
            not isinstance(recovery, Mapping)
            or recovery.get("receipt_hash")
            != ORIGINAL_RECOVERY_RECEIPT_HASH
            or recovery.get("sha256")
            != ORIGINAL_RECOVERY_RECEIPT_SHA256
        ):
            raise S607RecoveryLineageRebindError(
                "recovery_lineage_rebind_invalid"
            )
    bindings = service_parent.get("bindings")
    if (
        not isinstance(bindings, Mapping)
        or bindings.get("deployment_packet_sha256")
        != FINAL_DEPLOYMENT_PACKET_HASH
        or bindings.get("s6_07_rebind_packet_sha256")
        != FINAL_REBIND_PACKET_HASH
        or not isinstance(rebind_receipt.get("database_state"), Mapping)
        or _mapping_hash(rebind_receipt["database_state"])
        != FINAL_DATABASE_STATE_SHA256
    ):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    values["final_deployment_packet"]["packet_hash"] = (
        FINAL_DEPLOYMENT_PACKET_HASH
    )
    values["final_deployment_receipt"]["approval_packet_hash"] = (
        FINAL_DEPLOYMENT_PACKET_HASH
    )
    values["final_rebind_packet"]["packet_hash"] = (
        FINAL_REBIND_PACKET_HASH
    )
    values["final_rebind_receipt"]["receipt_hash"] = (
        FINAL_REBIND_RECEIPT_HASH
    )
    values["final_service_parent"]["packet_hash"] = (
        FINAL_SERVICE_PARENT_HASH
    )
    _validate_tracked_evidence(values)
    return values


def collect_database_state_read_only(
    database_url: str,
    *,
    session_factory: Any | None = None,
    text_factory: Any | None = None,
    state_probe: Any | None = None,
    checkpoint_probe: Any | None = None,
) -> dict[str, Any]:
    if not isinstance(database_url, str) or not database_url.strip():
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    owned_engine = None
    if session_factory is None:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from app.db.url import normalize_database_url

        owned_engine = create_engine(
            normalize_database_url(database_url),
            pool_pre_ping=True,
        )
        factory = sessionmaker(
            bind=owned_engine,
            autoflush=False,
            autocommit=False,
        )

        def create_session(_database_url: str) -> Any:
            return factory()

        session_factory = create_session
        text_factory = text
    if text_factory is None:
        from sqlalchemy import text

        text_factory = text
    if state_probe is None:
        from app.services.htdy_s6_08_runtime_gate import _database_state

        state_probe = _database_state
    if checkpoint_probe is None:
        from app.services.s607_code_rebind import _checkpoint_state

        checkpoint_probe = _checkpoint_state
    session = session_factory(database_url)
    try:
        bind = session.get_bind()
        if (
            str(bind.dialect.name or "") != "postgresql"
            or not str(bind.url.drivername or "").startswith("postgresql")
        ):
            raise S607RecoveryLineageRebindError(
                "recovery_lineage_rebind_invalid"
            )
        session.execute(text_factory("SET TRANSACTION READ ONLY"))
        read_only = str(
            session.execute(
                text_factory("SHOW transaction_read_only")
            ).scalar_one()
        ).lower() in {"on", "true", "1"}
        if not read_only:
            raise S607RecoveryLineageRebindError(
                "recovery_lineage_rebind_invalid"
            )
        revision = str(
            session.execute(
                text_factory("SELECT version_num FROM alembic_version")
            ).scalar_one()
        )
        counts, hashes = state_probe(session)
        checkpoint = checkpoint_probe(session)
        value = {
            "database_revision": revision,
            "counts": counts,
            "hashes": hashes,
            "checkpoint_count": checkpoint["count"],
            "checkpoint_sha256": checkpoint["sha256"],
        }
        _validate_database_state(value)
        return value
    finally:
        try:
            session.rollback()
        finally:
            session.close()
            if owned_engine is not None:
                owned_engine.dispose()


def _read_json_mapping(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        ) from exc
    if not isinstance(value, Mapping):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    return value


def _validate_source(value: Mapping[str, Any]) -> None:
    if (
        set(value) != {"root", "commit", "tree", "tracked_clean"}
        or not Path(str(value.get("root") or "")).is_absolute()
        or not _hex(value.get("commit"), 40)
        or not _hex(value.get("tree"), 40)
        or value.get("tracked_clean") is not True
    ):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )


def _validate_tracked_evidence(value: Mapping[str, Any]) -> None:
    if set(value) != set(TRACKED_EVIDENCE_SHA256):
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )
    expected_packet_hashes = {
        "final_deployment_packet": (
            "packet_hash",
            FINAL_DEPLOYMENT_PACKET_HASH,
        ),
        "final_deployment_receipt": (
            "approval_packet_hash",
            FINAL_DEPLOYMENT_PACKET_HASH,
        ),
        "final_rebind_packet": (
            "packet_hash",
            FINAL_REBIND_PACKET_HASH,
        ),
        "final_rebind_receipt": (
            "receipt_hash",
            FINAL_REBIND_RECEIPT_HASH,
        ),
        "final_service_parent": (
            "packet_hash",
            FINAL_SERVICE_PARENT_HASH,
        ),
    }
    for name, expected_sha256 in TRACKED_EVIDENCE_SHA256.items():
        item = value.get(name)
        expected_keys = {"path", "sha256"}
        if name in expected_packet_hashes:
            expected_keys.add(expected_packet_hashes[name][0])
        if (
            not isinstance(item, Mapping)
            or set(item) != expected_keys
            or not Path(str(item.get("path") or "")).is_absolute()
            or item.get("sha256") != expected_sha256
        ):
            raise S607RecoveryLineageRebindError(
                "recovery_lineage_rebind_invalid"
            )
        if name in expected_packet_hashes:
            field, expected = expected_packet_hashes[name]
            if item.get(field) != expected:
                raise S607RecoveryLineageRebindError(
                    "recovery_lineage_rebind_invalid"
                )


def _validate_database_state(value: Mapping[str, Any]) -> None:
    if _mapping_hash(value) != FINAL_DATABASE_STATE_SHA256:
        raise S607RecoveryLineageRebindError(
            "recovery_lineage_rebind_invalid"
        )


def _mapping_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )
