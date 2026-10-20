"""Bounded read-only experiment transport; never computes strategy or returns fills."""

from copy import deepcopy
from hashlib import sha256
import json
from .product_reader import NewowProductReadError
from .snapshot_cache import SnapshotCache


def experiment_response(
    result: dict,
    cache: SnapshotCache,
    *,
    snapshot_token: str | None = None,
    part: str = "panel",
    mode: str = "ordinary",
    segment_id: str | None = None,
    before: str | None = None,
    limit: int = 50,
) -> dict:
    if (
        part not in {"panel", "history"}
        or mode not in {"ordinary", "theoretical"}
        or type(limit) is not int
        or not 1 <= limit <= 200
    ):
        raise NewowProductReadError("NEWOW_INVALID_QUERY")
    if part == "history" and (not snapshot_token or not segment_id):
        raise NewowProductReadError("NEWOW_INVALID_QUERY")
    if part == "panel" and (segment_id is not None or before is not None):
        raise NewowProductReadError("NEWOW_INVALID_QUERY")
    # Include the complete result, including gap/rollover states and both models.
    fingerprint = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    identity = {
        key: result[key]
        for key in (
            "product",
            "frequency",
            "kind",
            "as_of",
            "formula_version",
            "profile_id",
            "input_policy_version",
        )
    }
    fact_key = (
        "experiment:"
        + sha256(
            json.dumps([identity, result["window"]], sort_keys=True).encode()
        ).hexdigest()
    )
    proof = {
        "canonical-source|experiment": result["input_snapshot_hash"],
        "result_hash": fingerprint,
    }
    if snapshot_token is not None and not cache.token_is_compatible(
        snapshot_token, fact_key, proof
    ):
        raise NewowProductReadError("NEWOW_SNAPSHOT_GENERATION_CONFLICT")
    token = cache.put(
        fact_key, ("experiment",), None, token=snapshot_token, proof=proof
    )
    if token is None:
        raise NewowProductReadError("NEWOW_RESOURCE_BUSY")
    bars = result["bars"]
    output = deepcopy(result)
    output["schema_version"] = "newow_experiment_detail_v2"
    output["meta"] = {
        "identity": {
            **identity,
            "series_kind": "actual_dominant",
            "strategy": result["kind"],
        },
        "as_of": result["as_of"],
        "input_content_sha256": result["input_snapshot_hash"],
        "snapshot_token": token,
        "result_hash": fingerprint,
        "completed_only": True,
        "executable": False,
        "auto_order": False,
        "data_revision_identity": result.get("data_revision_identity"),
        "last_completed_bar_end": bars[-1]["bar_end"] if bars else None,
        "last_trading_day": bars[-1]["trading_day"] if bars else None,
    }
    if part == "history":
        from .product_service import _cursor, _decode_cursor, NewowProductServiceError

        segment = next(
            (s for s in result["segments"] if s["segment_id"] == segment_id), None
        )
        if segment is None:
            raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
        page_identity = json.dumps([segment_id, mode], separators=(",", ":"))
        offset = 0
        if before:
            try:
                raw = _decode_cursor(
                    before, "experiment_history", fingerprint, page_identity
                )
                offset = int(raw)
                if str(offset) != raw or offset <= 0:
                    raise ValueError
            except NewowProductServiceError as exc:
                raise NewowProductReadError(exc.code) from None
            except ValueError:
                raise NewowProductReadError("NEWOW_CURSOR_INVALID") from None
        rows = list(reversed((segment[mode] or {}).get("trades", [])))
        if offset > len(rows):
            raise NewowProductReadError("NEWOW_CURSOR_INVALID")
        items = rows[offset : offset + limit]
        next_offset = offset + len(items)
        cursor = (
            _cursor(
                {
                    "v": 1,
                    "kind": "experiment_history",
                    "fingerprint": fingerprint,
                    "page_identity": page_identity,
                    "before": str(next_offset),
                }
            )
            if next_offset < len(rows)
            else None
        )
        return {
            "schema_version": "newow_experiment_history_v1",
            "meta": output["meta"],
            "segment_id": segment_id,
            "physical_contract": segment["physical_contract"],
            "reference_mode": mode,
            "items": items,
            "total_count": len(rows),
            "next_before": cursor,
        }
    for segment in output["segments"]:
        for name in ("ordinary", "theoretical"):
            model = segment[name]
            if model is not None:
                rows = model["trades"]
                model["total_count"] = len(rows)
                model["trades"] = rows[-3:]
    return output
