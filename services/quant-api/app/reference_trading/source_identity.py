"""Verify that a bounded page read is an exact prefix of saved P4 inputs."""

from __future__ import annotations

from datetime import date

from app.reference_trading.query import QueryConflict


def verify_saved_input_prefix(
    saved: dict[str, object], current: dict[str, object], through: date,
    observed_owner_keys: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    for key in ("input_fingerprints", "calendar_session_effective_fingerprints"):
        stored = saved.get(key)
        observed = current.get(key)
        if (
            not isinstance(stored, list) or not isinstance(observed, list)
            or not observed or len(observed) > len(stored)
            or stored[:len(observed)] != observed
        ):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
    for key in ("reader", "market_source_identity", "quality_policy_version",
                "quality_policy", "input_policy_version", "formula_versions",
                "reference_model_version"):
        if key in saved and key in current and saved[key] != current[key]:
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
    if "calendar_session_source_evidence" in saved or "calendar_session_source_evidence" in current:
        stored_metadata = saved.get("calendar_session_source_evidence")
        observed_metadata = current.get("calendar_session_source_evidence")
        if not isinstance(stored_metadata, dict) or not isinstance(observed_metadata, dict):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        for key in ("schema_version", "exchange", "symbol", "since"):
            if stored_metadata.get(key) != observed_metadata.get(key):
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        for key in ("calendar", "sessions"):
            stored_rows = stored_metadata.get(key)
            observed_rows = observed_metadata.get(key)
            if (
                not isinstance(stored_rows, list) or not isinstance(observed_rows, list)
                or stored_rows[:len(observed_rows)] != observed_rows
            ):
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
    for key in ("boundaries", "data_interruptions", "quality_interruptions"):
        if key not in saved or key not in current:
            continue
        stored = saved[key]
        observed = current[key]
        if (
            not isinstance(stored, list) or not isinstance(observed, list)
            or stored[:len(observed)] != observed
        ):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
    if "lifecycle_owners" in saved or "lifecycle_owners" in current:
        stored_owners = saved.get("lifecycle_owners")
        observed_owners = current.get("lifecycle_owners")
        if (
            not isinstance(stored_owners, list) or not isinstance(observed_owners, list)
            or not observed_owner_keys
        ):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        for owner in observed_owner_keys:
            if (list(owner) in stored_owners) != (list(owner) in observed_owners):
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
    if "rank1" in saved or "rank1" in current:
        stored_rank = saved.get("rank1")
        observed_rank = current.get("rank1")
        if (
            not isinstance(stored_rank, list) or not isinstance(observed_rank, list)
            or len(observed_rank) > len(stored_rank)
            or observed_rank[:-1] != stored_rank[:max(0, len(observed_rank) - 1)]
        ):
            raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
        if observed_rank:
            observed_last = observed_rank[-1]
            stored_last = stored_rank[len(observed_rank) - 1]
            if (
                not isinstance(observed_last, list) or not isinstance(stored_last, list)
                or len(observed_last) != 3 or len(stored_last) != 3
                or observed_last[:2] != stored_last[:2]
                or observed_last[2] != min(stored_last[2], through.isoformat())
            ):
                raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
