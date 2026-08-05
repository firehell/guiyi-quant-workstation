"""Business-specific Runtime Gate for the fixed 21-product retirement."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


_REQUIRED_ROOTS = frozenset({"raw", "canonical", "processed"})
REQUIRED_WRITER_SERVICES = (
    "com.guiyi.quant-api",
    "com.guiyi.quant-worker-backtests",
    "com.guiyi.quant-worker-signals",
    "com.guiyi.quant-worker-notifications",
    "com.guiyi.quant-notification-worker",
    "com.guiyi.quant-runtime-scheduler",
    "com.guiyi.quant-after-market-scheduler",
    "com.guiyi.quant-htdy-s610-one-day-observer",
    "com.guiyi.quant-htdy-s610-one-day-dispatcher",
    "com.guiyi.quant-htdy-s610-observer",
)


class ProductRetirementRuntimeGateError(ValueError):
    """Raised when the retirement Runtime Gate cannot establish its scope."""


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


class ProductRetirementRuntimeGate:
    """Coordinates the reversible Runtime phase before retirement DML."""

    def __init__(
        self,
        *,
        inventory: Callable[[RetirementRuntimeRequest, str], Mapping[str, Any]],
    ) -> None:
        self._inventory = inventory

    def execute_precommit(
        self,
        request: RetirementRuntimeRequest,
        *,
        operator: RuntimeOperator,
    ) -> Mapping[str, Any]:
        validate_runtime_request(request)
        operator.stop_writer_services()
        _require_all_stopped(operator.writer_states())
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
                "error": {"code": "PRODUCT_RETIREMENT_PRECOMMIT_FAILED", "type": type(exc).__name__},
            }
        return {
            "command": "runtime.product-retirement.execute",
            "status": "inventory_ready",
            "phase": "precommit",
            "previous_runtime_sha": previous_sha,
            "runtime_sha": runtime_sha,
            "inventory": dict(inventory),
        }


def validate_runtime_request(request: RetirementRuntimeRequest) -> None:
    """Validate bounded, real paths before any Runtime or data operation."""

    if set(request.roots) != _REQUIRED_ROOTS:
        raise ProductRetirementRuntimeGateError("PRODUCT_RETIREMENT_REQUIRED_ROOTS_MISMATCH")
    runtime_root = _validated_directory(request.runtime_root, "RUNTIME_ROOT")
    protected_root = _validated_directory(request.protected_root, "PROTECTED_ROOT")
    if _contains(runtime_root, protected_root) or _contains(protected_root, runtime_root):
        raise ProductRetirementRuntimeGateError("PRODUCT_RETIREMENT_PROTECTED_ROOT_OVERLAP")
    if not request.active_products_path.is_file() or request.active_products_path.is_symlink():
        raise ProductRetirementRuntimeGateError("PRODUCT_RETIREMENT_ACTIVE_PRODUCTS_INVALID")
    for label, configured_root in request.roots.items():
        root = _validated_directory(configured_root, f"{label.upper()}_ROOT")
        if _contains(root, protected_root) or _contains(protected_root, root):
            raise ProductRetirementRuntimeGateError("PRODUCT_RETIREMENT_PROTECTED_ROOT_OVERLAP")


def append_journal(protected_root: Path, payload: Mapping[str, Any]) -> Path:
    """Persist a single deterministic Gate state record without overwriting history."""

    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ProductRetirementRuntimeGateError("PRODUCT_RETIREMENT_JOURNAL_RUN_ID_INVALID")
    root = _validated_directory(protected_root, "PROTECTED_ROOT")
    target = root / f"product-retirement-{run_id}.jsonl"
    with target.open("x", encoding="utf-8") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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
