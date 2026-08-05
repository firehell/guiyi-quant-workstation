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
    def preflight(
        self, *, root: Path, release_tag: str, rollback_tag: str
    ) -> Mapping[str, Any]: ...

    def stop_writer_services(self) -> Mapping[str, str]: ...

    def writer_states(self) -> Mapping[str, str]: ...

    def runtime_identity(self, root: Path) -> str: ...

    def checkout_detached(self, root: Path, ref: str) -> str: ...

    def restart_services(
        self, target_states: Mapping[str, str]
    ) -> Mapping[str, str]: ...


class RetirementDataOperator(Protocol):
    def preflight(self, request: RetirementRuntimeRequest) -> Mapping[str, Any]: ...

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
    ) -> Mapping[str, Any]: ...

    def aggregate(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> Mapping[str, Any]: ...


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
        prior_service_states: Mapping[str, str] | None = None,
        preflight: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        validate_runtime_request(request)
        prior_states = _validated_service_states(
            prior_service_states or operator.writer_states()
        )
        previous_sha = operator.runtime_identity(request.runtime_root)
        operator.stop_writer_services()
        stopped_states = operator.writer_states()
        _require_all_stopped(stopped_states)
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
            "prior_service_states": dict(prior_states),
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
            "prior_service_states": dict(prior_states),
            "preflight": dict(preflight or {}),
            "inventory": dict(inventory),
        }

    def execute(
        self,
        request: RetirementRuntimeRequest,
        *,
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> Mapping[str, Any]:
        try:
            runtime_preflight = dict(
                runtime_operator.preflight(
                    root=request.runtime_root,
                    release_tag=request.release_tag,
                    rollback_tag=request.rollback_tag,
                )
            )
            prior_states = _validated_service_states(
                runtime_preflight.get("writer_states", {})
            )
            data_preflight = dict(data_operator.preflight(request))
            if data_preflight.get("status") != "passed":
                raise ProductRetirementRuntimeGateError(
                    "PRODUCT_RETIREMENT_DATA_PREFLIGHT_FAILED"
                )
        except Exception as exc:  # noqa: BLE001 - pre-stop fail closed
            return _rejected_preflight(exc)
        precommit = self.execute_precommit(
            request,
            operator=runtime_operator,
            prior_service_states=prior_states,
            preflight={"runtime": runtime_preflight, "data": data_preflight},
        )
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
            _write_pending_journal(
                request,
                precommit=precommit,
                receipt=receipt,
                phase="postcommit_purge",
            )
            return {
                "command": "runtime.product-retirement.execute",
                "status": "db_committed_purge_pending",
                "phase": "postcommit",
                "receipt": dict(receipt),
            }
        return self._complete_after_database_commit(
            request,
            receipt,
            target_service_states=prior_states,
            precommit=precommit,
            write_journal=True,
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
        try:
            runtime_preflight = dict(
                runtime_operator.preflight(
                    root=request.runtime_root,
                    release_tag=request.release_tag,
                    rollback_tag=request.rollback_tag,
                )
            )
            journal_runtime_sha = _required_journal_text(journal, "runtime_sha")
            journal_release_tag = _required_journal_text(journal, "release_tag")
            current_runtime_sha = runtime_preflight.get("runtime_sha")
            release_sha = runtime_preflight.get("release_sha")
            matches_journal = current_runtime_sha == journal_runtime_sha
            already_promoted = (
                current_runtime_sha == release_sha
                and journal_release_tag != request.release_tag
            )
            if not (matches_journal or already_promoted):
                raise ProductRetirementRuntimeGateError(
                    "PRODUCT_RETIREMENT_RESUME_RUNTIME_DRIFT"
                )
            data_preflight = dict(data_operator.preflight(request))
            if data_preflight.get("status") != "passed":
                raise ProductRetirementRuntimeGateError(
                    "PRODUCT_RETIREMENT_DATA_PREFLIGHT_FAILED"
                )
        except Exception as exc:  # noqa: BLE001 - pre-stop fail closed
            return _rejected_preflight(exc, command="runtime.product-retirement.resume")
        target_states = _validated_service_states(journal["prior_service_states"])
        runtime_operator.stop_writer_services()
        _require_all_stopped(runtime_operator.writer_states())
        if current_runtime_sha != release_sha:
            try:
                promoted_sha = runtime_operator.checkout_detached(
                    request.runtime_root,
                    request.release_tag,
                )
                if promoted_sha != release_sha:
                    raise ProductRetirementRuntimeGateError(
                        "PRODUCT_RETIREMENT_RESUME_PROMOTION_MISMATCH"
                    )
                _require_all_stopped(runtime_operator.writer_states())
            except Exception as exc:  # noqa: BLE001 - DB is already committed
                return {
                    "command": "runtime.product-retirement.resume",
                    "status": "db_committed_purge_pending",
                    "phase": "postcommit_runtime_promotion",
                    "receipt": dict(journal["receipt"]),
                    "error": {
                        "code": "PRODUCT_RETIREMENT_RESUME_PROMOTION_FAILED",
                        "type": type(exc).__name__,
                    },
                }
        if journal["receipt"].get("status") == "applied":
            receipt = journal["receipt"]
        else:
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
            target_service_states=target_states,
            precommit=journal,
            write_journal=False,
            runtime_operator=runtime_operator,
            data_operator=data_operator,
        )
        return {**completed, "command": "runtime.product-retirement.resume"}

    def _complete_after_database_commit(
        self,
        request: RetirementRuntimeRequest,
        receipt: Mapping[str, Any],
        *,
        target_service_states: Mapping[str, str],
        precommit: Mapping[str, Any],
        write_journal: bool,
        runtime_operator: RuntimeOperator,
        data_operator: RetirementDataOperator,
    ) -> Mapping[str, Any]:
        verification = data_operator.verify()
        if verification.get("status") != "passed":
            if write_journal:
                _write_pending_journal(
                    request,
                    precommit=precommit,
                    receipt=receipt,
                    phase="postcommit_verify",
                )
            return {
                "command": "runtime.product-retirement.execute",
                "status": "db_committed_purge_pending",
                "phase": "postcommit",
                "receipt": dict(receipt),
                "verification": dict(verification),
            }
        from app.data_core.product_retirement import load_active_products

        products = load_active_products(request.active_products_path)
        try:
            direct_receipt = dict(
                data_operator.sync_direct(products, ("1m", "1d", "1w"))
            )
            if direct_receipt.get("status") != "passed":
                raise ProductRetirementRuntimeGateError(
                    "PRODUCT_RETIREMENT_DIRECT_REFRESH_FAILED"
                )
            aggregate_receipt = dict(
                data_operator.aggregate(products, ("5m", "15m", "30m", "60m"))
            )
            if aggregate_receipt.get("status") != "passed":
                raise ProductRetirementRuntimeGateError(
                    "PRODUCT_RETIREMENT_AGGREGATE_REFRESH_FAILED"
                )
            service_states = dict(
                runtime_operator.restart_services(target_service_states)
            )
            _require_exact_service_states(service_states, target_service_states)
        except Exception as exc:  # noqa: BLE001 - keep Runtime stopped/pending
            if write_journal:
                _write_pending_journal(
                    request,
                    precommit=precommit,
                    receipt=receipt,
                    phase="postcommit_refresh",
                )
            return {
                "command": "runtime.product-retirement.execute",
                "status": "db_committed_purge_pending",
                "phase": "postcommit_refresh",
                "receipt": dict(receipt),
                "verification": dict(verification),
                "error": {
                    "code": "PRODUCT_RETIREMENT_POSTCOMMIT_REFRESH_FAILED",
                    "type": type(exc).__name__,
                },
            }
        return {
            "command": "runtime.product-retirement.execute",
            "status": "completed",
            "phase": "restarted",
            "receipt": dict(receipt),
            "verification": dict(verification),
            "direct_refresh": direct_receipt,
            "aggregate_refresh": aggregate_receipt,
            "service_states": service_states,
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


def _write_pending_journal(
    request: RetirementRuntimeRequest,
    *,
    precommit: Mapping[str, Any],
    receipt: Mapping[str, Any],
    phase: str,
) -> Path:
    return append_journal(
        request.protected_root,
        {
            "schema_version": 1,
            "status": "db_committed_purge_pending",
            "phase": phase,
            "run_id": _required_journal_text(precommit, "run_id"),
            "release_tag": _required_journal_text(precommit, "release_tag"),
            "runtime_sha": _required_journal_text(precommit, "runtime_sha"),
            "shutdown_receipt_sha256": _required_journal_text(
                precommit, "shutdown_receipt_sha256"
            ),
            "prior_service_states": _validated_service_states(
                precommit["prior_service_states"]
            ),
            "inventory": dict(precommit["inventory"]),
            "receipt": dict(receipt),
        },
    )


def _required_journal_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductRetirementRuntimeGateError(
            f"PRODUCT_RETIREMENT_JOURNAL_{key.upper()}_INVALID"
        )
    return value.strip()


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


def _validated_service_states(states: object) -> dict[str, str]:
    if not isinstance(states, Mapping) or set(states) != set(REQUIRED_WRITER_SERVICES):
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_SERVICE_STATES_INVALID"
        )
    normalized = {str(key): str(value) for key, value in states.items()}
    if any(value not in {"running", "stopped"} for value in normalized.values()):
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_SERVICE_STATES_INVALID"
        )
    return normalized


def _require_exact_service_states(
    actual: Mapping[str, str], expected: Mapping[str, str]
) -> None:
    if _validated_service_states(actual) != _validated_service_states(expected):
        raise ProductRetirementRuntimeGateError(
            "PRODUCT_RETIREMENT_SERVICE_RESTORE_MISMATCH"
        )


def _rejected_preflight(
    exc: Exception,
    *,
    command: str = "runtime.product-retirement.execute",
) -> dict[str, Any]:
    return {
        "command": command,
        "status": "rejected",
        "phase": "preflight",
        "services_stopped": False,
        "error": {
            "code": "PRODUCT_RETIREMENT_PREFLIGHT_FAILED",
            "type": type(exc).__name__,
        },
    }


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
        or not isinstance(payload.get("prior_service_states"), dict)
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
