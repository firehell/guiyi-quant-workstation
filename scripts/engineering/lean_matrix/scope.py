"""Shared exact-file and recursive ``/**`` repository scope semantics."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import LeanMatrixError


def validate_scope_patterns(
    allowed_paths: Iterable[str],
    forbidden_paths: Iterable[str],
) -> None:
    """Reject wildcard forms other than a terminal ``/**``."""
    for entry in allowed_paths:
        if "*" in entry and (not entry.endswith("/**") or "*" in entry[:-3]):
            raise LeanMatrixError(
                "unsupported_allowlist_pattern",
                f"unsupported allowlist pattern: {entry}",
            )
    for entry in forbidden_paths:
        if "*" in entry and (not entry.endswith("/**") or "*" in entry[:-3]):
            raise LeanMatrixError(
                "unsupported_forbidden_pattern",
                f"unsupported forbidden pattern: {entry}",
            )


def scope_matches(path: str, entry: str) -> bool:
    """Match one repository path against one validated exact or recursive entry."""
    if entry.endswith("/**"):
        return path.startswith(entry.removesuffix("**"))
    return path == entry


def scope_allows(path: str, entries: Iterable[str]) -> bool:
    return any(scope_matches(path, entry) for entry in entries)


def scope_entry_is_subset(child: str, parent: str) -> bool:
    """Return whether every path authorized by child is authorized by parent."""
    if parent.endswith("/**"):
        parent_prefix = parent.removesuffix("**")
        if child.endswith("/**"):
            return child.removesuffix("**").startswith(parent_prefix)
        return child.startswith(parent_prefix)
    return not child.endswith("/**") and child == parent


def scope_is_subset(children: Iterable[str], parents: Iterable[str]) -> bool:
    parent_entries = tuple(parents)
    return all(
        any(scope_entry_is_subset(child, parent) for parent in parent_entries)
        for child in children
    )
