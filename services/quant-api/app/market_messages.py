"""Stateless, query-bound pagination over bounded authoritative message readers."""

from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import json


class MessageCursorError(ValueError):
    pass


def decode_cursor(value: str) -> dict:
    try:
        if len(value) > 4096:
            raise ValueError
        result = json.loads(
            base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            )
        )
        if (
            not isinstance(result, dict)
            or set(result) != {"v", "query", "snapshot", "digest", "offset"}
            or result["v"] != 1
            or not isinstance(result["query"], dict)
            or not isinstance(result["snapshot"], dict)
            or not isinstance(result["digest"], str)
            or len(result["digest"]) != 64
            or any(
                character not in "0123456789abcdef" for character in result["digest"]
            )
            or type(result["offset"]) is not int
            or not 0 <= result["offset"] <= 10000
        ):
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError):
        raise MessageCursorError from None


def paginate_messages(
    rows: list[dict],
    sources: dict,
    query: dict,
    snapshot: dict,
    cursor: str | None,
    *,
    limit: int = 50,
) -> dict:
    # Parse timestamps: lexical ISO sorting is incorrect across timezone offsets.
    rows = sorted(
        rows,
        key=lambda row: (
            datetime.fromisoformat(row["bar_end"].replace("Z", "+00:00")).timestamp(),
            row["source"],
            str(row["id"]).zfill(24),
        ),
        reverse=True,
    )
    digest = hashlib.sha256(
        json.dumps([rows, sources], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    offset = 0
    if cursor:
        previous = decode_cursor(cursor)
        if (
            previous["query"] != query
            or previous["snapshot"] != snapshot
            or previous["digest"] != digest
        ):
            raise MessageCursorError
        offset = previous["offset"]
        if offset >= len(rows):
            raise MessageCursorError
    next_cursor = None
    if offset + limit < len(rows):
        payload = {
            "v": 1,
            "query": query,
            "snapshot": snapshot,
            "digest": digest,
            "offset": offset + limit,
        }
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
    return {
        "items": rows[offset : offset + limit],
        "dataset_hash": digest,
        "next_cursor": next_cursor,
        "available_count": len(rows),
        "sources": sources,
        "snapshot": snapshot,
        "coverage": "partial"
        if any(
            s.get("status") != "ready"
            or s.get("truncated")
            or s.get("excluded_streams", 0)
            for s in sources.values()
        )
        else "complete",
    }
