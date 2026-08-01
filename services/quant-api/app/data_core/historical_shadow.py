"""Bounded, source-lineage-aware historical Shadow execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.data_core.historical_migration import (
    HistoricalShadowQuery,
    ShadowException,
    build_jm_shadow_query_set,
    compare_shadow_bars,
)
from app.data_core.aggregation import AggregationSession


@dataclass(frozen=True, slots=True)
class ShadowReadResult:
    rows: tuple[Mapping[str, Any], ...]
    lineage: Mapping[str, Any]


def filter_initial_partial_week_sessions(
    sessions: Sequence[AggregationSession],
    *,
    first_approved_trading_day: date,
) -> tuple[AggregationSession, ...]:
    normalized = tuple(sessions)
    if first_approved_trading_day.weekday() == 0:
        return normalized
    initial_week = first_approved_trading_day.isocalendar()[:2]
    return tuple(
        session
        for session in normalized
        if session.trading_day.isocalendar()[:2] != initial_week
    )


def expected_shadow_bar_keys(
    query: HistoricalShadowQuery,
    sessions: Sequence[AggregationSession],
) -> tuple[str, ...]:
    """Build calendar/session keys without consulting either Shadow dataset."""
    start = datetime.fromisoformat(query.start).astimezone(UTC)
    end = datetime.fromisoformat(query.end).astimezone(UTC)
    ordered = tuple(sorted(sessions, key=lambda item: (item.start, item.end)))
    if not ordered:
        return ()
    if query.frequency == "1m":
        keys = {
            bar_end
            for session in ordered
            for bar_end in _minute_ends(session)
            if start < bar_end <= end
        }
    elif query.frequency in {"5m", "15m", "30m", "60m"}:
        minutes = int(query.frequency.removesuffix("m"))
        keys = {
            bucket[-1]
            for session in ordered
            for bucket in _buckets(_minute_ends(session), minutes)
            if bucket and start < bucket[-1] <= end
        }
    elif query.frequency == "1d":
        keys = {
            datetime.combine(session.trading_day, datetime.min.time(), tzinfo=UTC)
            for session in ordered
        }
        keys = {item for item in keys if start < item <= end}
    elif query.frequency == "1w":
        by_week: dict[tuple[int, int], set[object]] = {}
        for session in ordered:
            iso = session.trading_day.isocalendar()
            by_week.setdefault((iso.year, iso.week), set()).add(
                session.trading_day
            )
        keys = {
            datetime.combine(max(days), datetime.min.time(), tzinfo=UTC)
            for days in by_week.values()
        }
        keys = {item for item in keys if start < item <= end}
    else:
        raise ValueError("shadow frequency unsupported")
    return tuple(item.isoformat() for item in sorted(keys))


def run_chunked_historical_shadow_query_set(
    queries: Sequence[HistoricalShadowQuery],
    *,
    legacy_reader: Callable[[HistoricalShadowQuery], ShadowReadResult],
    canonical_reader: Callable[[HistoricalShadowQuery], ShadowReadResult],
    expected_keys_reader: Callable[[HistoricalShadowQuery], Sequence[str]],
    allowed_exceptions: Mapping[str, Sequence[ShadowException]] | None = None,
    expected_actual_contract_by_day: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    query_tuple = tuple(queries)
    if not query_tuple:
        raise ValueError("shadow query set must contain exact JM matrix")
    expected_queries = build_jm_shadow_query_set(
        start=datetime.fromisoformat(query_tuple[0].start),
        end=datetime.fromisoformat(query_tuple[0].end),
    )
    if query_tuple != expected_queries:
        raise ValueError("shadow query set must contain exact JM matrix")
    query_ids = [f"{item.dataset_kind}:{item.frequency}" for item in query_tuple]
    if len(set(query_ids)) != 13:
        raise ValueError("shadow query set must contain exact JM matrix")
    exceptions = dict(allowed_exceptions or {})
    if set(exceptions) - set(query_ids):
        raise ValueError("shadow exception query outside frozen matrix")
    mapping = dict(expected_actual_contract_by_day or {})
    consumed_exceptions: dict[str, set[str]] = {item: set() for item in query_ids}
    results: list[dict[str, Any]] = []
    legacy_lineages: list[Mapping[str, Any]] = []
    canonical_lineages: list[Mapping[str, Any]] = []
    chunk_count = 0
    for base_query in query_tuple:
        query_id = f"{base_query.dataset_kind}:{base_query.frequency}"
        query_chunks: list[dict[str, Any]] = []
        for chunk in _monthly_chunks(base_query):
            expected_keys = tuple(sorted({_bar_key(item) for item in expected_keys_reader(chunk)}))
            if not expected_keys:
                continue
            chunk_count += 1
            legacy = legacy_reader(chunk)
            canonical = canonical_reader(chunk)
            if not isinstance(legacy, ShadowReadResult) or not isinstance(
                canonical, ShadowReadResult
            ):
                raise ValueError("shadow reader result invalid")
            legacy_lineages.append(dict(legacy.lineage))
            canonical_lineages.append(dict(canonical.lineage))
            chunk_exceptions = tuple(
                item
                for item in exceptions.get(query_id, ())
                if chunk.start < item.bar_end <= chunk.end
            )
            compared = compare_shadow_bars(
                legacy.rows,
                canonical.rows,
                allowed_exceptions=chunk_exceptions,
                expected_identity={
                    "provider": "rqdata",
                    "dataset_kind": chunk.dataset_kind,
                    "symbol": "jm",
                    "contract_or_series": chunk.contract_or_series,
                    "frequency": chunk.frequency,
                    "adjustment": "none",
                    "schema_version": "canonical-bar-v1",
                },
                expected_actual_contract_by_day=(
                    mapping if chunk.dataset_kind == "actual_dominant" else None
                ),
            )
            consumed_exceptions[query_id].update(
                compared["explained_boundary_keys"]
            )
            expected_set = set(expected_keys)
            for side, rows in (("legacy", legacy.rows), ("canonical", canonical.rows)):
                actual = {_bar_key_from_row(item) for item in rows}
                if actual != expected_set:
                    compared["differences"].append(
                        {
                            "bar_end": None,
                            "reason": "chunk_coverage_mismatch",
                            "fields": [side],
                            "missing_count": len(expected_set - actual),
                            "unexpected_count": len(actual - expected_set),
                        }
                    )
            if compared["differences"]:
                compared["status"] = "blocked"
            chunk_body = {
                "query": asdict(chunk),
                "expected_bar_count": len(expected_keys),
                "expected_keys_digest": _digest({"keys": list(expected_keys)}),
                "legacy_rows_digest": _rows_digest(legacy.rows),
                "canonical_rows_digest": _rows_digest(canonical.rows),
                **compared,
            }
            query_chunks.append(
                {**chunk_body, "chunk_digest": _digest(chunk_body)}
            )
        if not query_chunks:
            raise ValueError("shadow expected chunk coverage missing")
        results.append(
            {
                "query_id": query_id,
                "status": (
                    "blocked"
                    if any(item["status"] == "blocked" for item in query_chunks)
                    else "passed"
                ),
                "chunk_count": len(query_chunks),
                "chunks": query_chunks,
            }
        )
    for query_id, declared in exceptions.items():
        unused = {item.bar_end for item in declared} - consumed_exceptions[query_id]
        if unused:
            target = next(item for item in results if item["query_id"] == query_id)
            target["status"] = "blocked"
            target["unused_declared_exception_keys"] = sorted(unused)
    blocked = sum(item["status"] == "blocked" for item in results)
    body = {
        "schema_version": 2,
        "status": "blocked" if blocked else "passed",
        "query_count": len(results),
        "chunk_count": chunk_count,
        "blocked_query_count": blocked,
        "query_set_digest": _digest(
            {"queries": [asdict(item) for item in query_tuple]}
        ),
        "mapping_evidence_digest": _digest({"mapping": mapping}),
        "exception_digest": _digest(
            {
                "exceptions": {
                    key: [asdict(item) for item in value]
                    for key, value in sorted(exceptions.items())
                }
            }
        ),
        "legacy_source_lineage_digest": _digest(
            {"lineages": _unique_mappings(legacy_lineages)}
        ),
        "canonical_source_lineage_digest": _digest(
            {"lineages": _unique_mappings(canonical_lineages)}
        ),
        "coverage_basis": "strict_calendar_session_and_canonical_reader",
        "results": results,
    }
    return {**body, "receipt_digest": _digest(body)}


def _monthly_chunks(query: HistoricalShadowQuery) -> Iterable[HistoricalShadowQuery]:
    start = datetime.fromisoformat(query.start).astimezone(UTC)
    end = datetime.fromisoformat(query.end).astimezone(UTC)
    cursor = start
    while cursor < end:
        if cursor.month == 12:
            boundary = datetime(cursor.year + 1, 1, 1, tzinfo=UTC)
        else:
            boundary = datetime(cursor.year, cursor.month + 1, 1, tzinfo=UTC)
        chunk_end = min(boundary, end)
        yield HistoricalShadowQuery(
            dataset_kind=query.dataset_kind,
            contract_or_series=query.contract_or_series,
            frequency=query.frequency,
            start=cursor.isoformat(),
            end=chunk_end.isoformat(),
        )
        cursor = chunk_end


def _minute_ends(session: AggregationSession) -> tuple[datetime, ...]:
    result: list[datetime] = []
    cursor = session.start + timedelta(minutes=1)
    while cursor <= session.end:
        result.append(cursor)
        cursor += timedelta(minutes=1)
    return tuple(result)


def _buckets(
    values: Sequence[datetime],
    size: int,
) -> tuple[tuple[datetime, ...], ...]:
    return tuple(
        tuple(values[offset : offset + size])
        for offset in range(0, len(values), size)
    )


def _bar_key_from_row(row: Mapping[str, Any]) -> str:
    return _bar_key(row.get("bar_end") or row.get("datetime") or row.get("time"))


def _bar_key(value: object) -> str:
    if not isinstance(value, str):
        if not isinstance(value, datetime):
            raise ValueError("shadow expected bar key invalid")
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("shadow expected bar key timezone required")
    return parsed.astimezone(UTC).isoformat()


def _rows_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    normalized = [
        {key: str(value) for key, value in sorted(dict(item).items())}
        for item in rows
    ]
    return _digest({"rows": normalized})


def _unique_mappings(values: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    unique = {
        json.dumps(value, sort_keys=True, separators=(",", ":")): value
        for value in values
    }
    return [unique[key] for key in sorted(unique)]


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
