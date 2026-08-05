"""Business-specific Runtime Gate for the fixed 21-product retirement."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4


_REQUIRED_ROOTS = frozenset({"raw", "canonical", "processed"})
REQUIRED_WRITER_SERVICES = (
    "com.guiyi.quant-api",
    "com.guiyi.quant-worker-backtests",
    "com.guiyi.quant-worker-signals",
    "com.guiyi.quant-runtime-scheduler",
    "com.guiyi.quant-after-market-scheduler",
    "com.guiyi.quant-htdy-s610-one-day-observer",
    "com.guiyi.quant-htdy-s610-one-day-dispatcher",
    "com.guiyi.quant-htdy-s610-observer",
)


class ProductRetirementRuntimeGateError(ValueError):
    """Raised when the retirement Runtime Gate cannot establish its scope."""


class ProductRetirementPrecommitError(ProductRetirementRuntimeGateError):
    """A data operator proved that its database transaction never committed."""


@dataclass(frozen=True)
class RetirementRuntimeRequest:
    release_tag: str
    rollback_tag: str
    runtime_root: Path
    protected_root: Path
    active_products_path: Path
    roots: Mapping[str, Path]


class RuntimeOperator(Protocol):
    def stop_writer_services(self) -> Mapping[str, str]: ...

    def writer_states(self) -> Mapping[str, str]: ...

    def runtime_identity(self, root: Path) -> str: ...

    def checkout_detached(self, root: Path, ref: str) -> str: ...

    def restart_services(self) -> Mapping[str, str]: ...


class RetirementDataOperator(Protocol):
    def apply(
        self,
        inventory: Mapping[str, Any],
        precommit: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def finalize(
        self,
        inventory: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def verify(self) -> Mapping[str, Any]: ...

    def sync_direct(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None: ...

    def aggregate(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None: ...


class ProductRetirementRuntimeGate:
    """Coordinates the reversible Runtime phase before retirement DML."""

    def __init__(
        self,
        *,
        inventory: Callable[[RetirementRuntimeRequest, str], Mapping[str, Any]],
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._inventory = inventory
        self._run_id_factory = run_id_factory or (lambda: uuid4().hex)

    def execute_precommit(
        self,
        request: RetirementRuntimeRequest,
        *,
        operator: RuntimeOperator,
    ) -> Mapping[str, Any]:
        validate_runtime_request(request)
        operator.stop_writer_services()
        stopped_states = operator.writer_states()
        _require_all_stopped(stopped_states)
        previous_sha = operator.runtime_identity(request.runtime_root)
        try:
            runtime_sha = operator.checkout_detached(
                request.runtime_root,
                request.release_tag,
            )
            inventory = self._inventory(request, runtime_sha)
        except Exception as exc:  # noqa: BLE001 - return a bounded Gate result
            rollback_sha = operator.checkout_detached(
                request.runtime_root,
                request.rollback_tag,
            )
            _require_all_stopped(operator.writer_states())
            return {
                "command": "runtime.product-retirement.execute",
                "status": "rejected",
                "phase": "precommit",
                "previous_runtime_sha": previous_sha,
                "rollback_runtime_sha": rollback_sha,
                "error": {
                    "code": "PRODUCT_RETIREMENT_PRECOMMIT_FAILED",
                    "type": type(exc).__name__,
                },
            }
        run_id = self._run_id_factory()
        if not isinstance(run_id, str) or not run_id.strip():
            raise ProductRetirementRuntimeGateError("PRODUCT_RETIREMENT_RUN_ID_INVALID")
        shutdown_receipt = {
            "schema_version": 1,
            "command": "runtime.product-retirement.shutdown",
            "run_id": run_id.strip(),
            "release_tag": request.release_tag,
            "runtime_sha": runtime_sha,
            "writer_states": {
                key: stopped_states[key] for key in REQUIRED_WRITER_SERVICES
            },
        }
        return {
            "command": "runtime.product-retirement.execute",
            "status": "inventory_ready",
            "phase": "precommit",
            "previous_runtime_sha": previous_sha,
            "runtime_sha": runtime_sha,
            "run_id": run_id.strip(),
            "release_tag": request.release_tag,
            "shutdown_receipt_sha256": _json_sha256(shutdown_receipt),
            "inventory": dict(inventory),
        }

    def execute(
        self,
        request: RetirementRuntimeRequest,
        *,
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> Mapping[str, Any]:
        precommit = self.execute_precommit(request, operator=runtime_operator)
        if precommit["status"] == "rejected":
            return precommit
        try:
            receipt = data_operator.apply(precommit["inventory"], precommit)
        except ProductRetirementPrecommitError as exc:
            rollback_sha = runtime_operator.checkout_detached(
                request.runtime_root,
                request.rollback_tag,
            )
            _require_all_stopped(runtime_operator.writer_states())
            return {
                "command": "runtime.product-retirement.execute",
                "status": "rejected",
                "phase": "precommit",
                "rollback_runtime_sha": rollback_sha,
                "error": {
                    "code": "PRODUCT_RETIREMENT_DATABASE_PRECOMMIT_FAILED",
                    "type": type(exc).__name__,
                },
            }
        if receipt.get("status") == "db_committed_purge_pending":
            return {
                "command": "runtime.product-retirement.execute",
                "status": "db_committed_purge_pending",
                "phase": "postcommit",
                "receipt": dict(receipt),
            }
        return self._complete_after_database_commit(
            request,
            receipt,
            runtime_operator=runtime_operator,
            data_operator=data_operator,
        )

    def resume(
        self,
        request: RetirementRuntimeRequest,
        *,
        journal_path: Path,
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> Mapping[str, Any]:
        validate_runtime_request(request)
        journal = _read_pending_journal(journal_path, request.protected_root)
        runtime_operator.stop_writer_services()
        _require_all_stopped(runtime_operator.writer_states())
        receipt = data_operator.finalize(journal["inventory"], journal["receipt"])
        if receipt.get("status") == "db_committed_purge_pending":
            return {
                "command": "runtime.product-retirement.resume",
                "status": "db_committed_purge_pending",
                "phase": "postcommit",
                "receipt": dict(receipt),
            }
        completed = self._complete_after_database_commit(
            request,
            receipt,
            runtime_operator=runtime_operator,
            data_operator=data_operator,
        )
        return {**completed, "command": "runtime.product-retirement.resume"}

    def _complete_after_database_commit(
        self,
        request: RetirementRuntimeRequest,
        receipt: Mapping[str, Any],
        *,
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> Mapping[str, Any]:
        verification = data_operator.verify()
        if verification.get("status") != "passed":
            return {
                "command": "runtime.product-retirement.execute",
                "status": "db_committed_purge_pending",
                "phase": "postcommit",
                "receipt": dict(receipt),
                "verification": dict(verification),
            }
        from app.data_core.product_retirement import load_active_products

        products = load_active_products(request.active_products_path)
        data_operator.sync_direct(products, ("1m", "1d", "1w"))
        data_operator.aggregate(products, ("5m", "15m", "30m", "60m"))
        runtime_operator.restart_services()
        return {
            "command": "runtime.product-retirement.execute",
            "status": "completed",
            "phase": "restarted",
            "receipt": dict(receipt),
            "verification": dict(verification),
        }


class ProductRetirementExecutionService:
    """The single business orchestrator for this retirement run."""

    def __init__(
        self,
        *,
        inventory: Callable[[RetirementRuntimeRequest, str], Mapping[str, Any]],
    ) -> None:
        self._gate = ProductRetirementRuntimeGate(inventory=inventory)

    def plan(self, request: RetirementRuntimeRequest) -> Mapping[str, Any]:
        validate_runtime_request(request)
        from app.data_core.product_retirement import load_active_products

        products = load_active_products(request.active_products_path)
        return {
            "command": "runtime.product-retirement.plan",
            "status": "planned",
            "readonly": True,
            "active_product_count": len(products),
            "direct_frequencies": ["1m", "1d", "1w"],
            "derived_frequencies": ["5m", "15m", "30m", "60m"],
            "mapping_overlap_trading_days": 10,
            "effects": {
                "calls_rqdata": False,
                "writes_historical_active": False,
                "writes_postgresql": False,
                "auto_order": False,
            },
        }

    def execute(
        self,
        request: RetirementRuntimeRequest,
        *,
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> Mapping[str, Any]:
        return self._gate.execute(
            request,
            runtime_operator=runtime_operator,
            data_operator=data_operator,
        )

    def resume(
        self,
        request: RetirementRuntimeRequest,
        *,
        journal_path: Path,
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> Mapping[str, Any]:
        return self._gate.resume(
            request,
            journal_path=journal_path,
            runtime_operator=runtime_operator,
            data_operator=data_operator,
        )


class BoundProductRetirementCommandExecutor:
    """Bind the two real operators once, leaving the CLI free of infra details."""

    def __init__(
        self,
        *,
        inventory: Callable[[RetirementRuntimeRequest, str], Mapping[str, Any]],
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> None:
        self._service = ProductRetirementExecutionService(inventory=inventory)
        self._runtime_operator = runtime_operator
        self._data_operator = data_operator

    def plan(self, request: RetirementRuntimeRequest) -> Mapping[str, Any]:
        return self._service.plan(request)

    def execute(self, request: RetirementRuntimeRequest) -> Mapping[str, Any]:
        return self._service.execute(
            request,
            runtime_operator=self._runtime_operator,
            data_operator=self._data_operator,
        )

    def resume(
        self,
        request: RetirementRuntimeRequest,
        *,
        journal_path: Path,
    ) -> Mapping[str, Any]:
        return self._service.resume(
            request,
            journal_path=journal_path,
            runtime_operator=self._runtime_operator,
            data_operator=self._data_operator,
        )


def validate_runtime_request(request: RetirementRuntimeRequest) -> None:
    """Validate bounded, real paths before any Runtime or data operation."""

    if set(request.roots) != _REQUIRED_ROOTS:
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_REQUIRED_ROOTS_MISMATCH"
        )
    runtime_root = _validated_directory(request.runtime_root, "RUNTIME_ROOT")
    protected_root = _validated_directory(request.protected_root, "PROTECTED_ROOT")
    if _contains(runtime_root, protected_root) or _contains(
        protected_root, runtime_root
    ):
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_PROTECTED_ROOT_OVERLAP"
        )
    if (
        not request.active_products_path.is_file()
        or request.active_products_path.is_symlink()
    ):
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_ACTIVE_PRODUCTS_INVALID"
        )
    for label, configured_root in request.roots.items():
        root = _validated_directory(configured_root, f"{label.upper()}_ROOT")
        if _contains(root, protected_root) or _contains(protected_root, root):
            raise ProductRetirementRuntimeGateError(
                "PRODUCT_RETIREMENT_PROTECTED_ROOT_OVERLAP"
            )


def append_journal(protected_root: Path, payload: Mapping[str, Any]) -> Path:
    """Persist a single deterministic Gate state record without overwriting history."""

    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_JOURNAL_RUN_ID_INVALID"
        )
    root = _validated_directory(protected_root, "PROTECTED_ROOT")
    target = root / f"product-retirement-{run_id}.jsonl"
    with target.open("x", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        )
    return target


def _validated_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ProductRetirementRuntimeGateError(f"PRODUCT_RETIREMENT_{label}_INVALID")
    return path.resolve(strict=True)


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _require_all_stopped(states: Mapping[str, str]) -> None:
    for service in REQUIRED_WRITER_SERVICES:
        if states.get(service) != "stopped":
            raise ProductRetirementRuntimeGateError(
                f"PRODUCT_RETIREMENT_SERVICE_NOT_STOPPED:{service}"
            )


def _read_pending_journal(path: Path, protected_root: Path) -> Mapping[str, Any]:
    root = _validated_directory(protected_root, "PROTECTED_ROOT")
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ProductRetirementRuntimeGateError("PRODUCT_RETIREMENT_JOURNAL_INVALID")
    resolved = path.resolve(strict=True)
    if not _contains(root, resolved):
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_JOURNAL_OUTSIDE_PROTECTED_ROOT"
        )
    lines = resolved.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_JOURNAL_FORMAT_INVALID"
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_JOURNAL_FORMAT_INVALID"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "db_committed_purge_pending"
        or not isinstance(payload.get("inventory"), dict)
        or not isinstance(payload.get("receipt"), dict)
    ):
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_JOURNAL_PENDING_INVALID"
        )
    return payload


def _json_sha256(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
