"""Business-specific Runtime Gate for the fixed 21-product retirement."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


_REQUIRED_ROOTS = frozenset({"raw", "canonical", "processed"})


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
