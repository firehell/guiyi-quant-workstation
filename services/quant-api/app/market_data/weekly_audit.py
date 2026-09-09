"""One optional full-history operational audit; status is observation, never repair authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any

from app.db.readonly import readonly_transaction
from app.market_data.after_market import _atomic_write_status, _local_timestamp, _public_timestamp
from app.market_data.domain import DatasetKey
from app.market_data.historical_data_manager import (
    AuditProgressEvent, AuditRequest, HistoricalDataManager, _AUDIT_METADATA_CATEGORIES,
)


_FINDING_CODES = frozenset(_AUDIT_METADATA_CATEGORIES) | {
    "MAIN_CONTRACT_MAP_MISSING", "CONTRACT_PARTITION_OUTSIDE_LIFECYCLE", "EXPECTED_PARTITION_MISSING",
    "PARTITION_CATALOG_MISMATCH", "PARTITION_CONTENT_HASH_MISMATCH", "PARTITION_COVERAGE_MISMATCH",
    "PARTITION_EMPTY", "PARTITION_MONTH_MISMATCH", "PARTITION_ROW_COUNT_MISMATCH", "PARTITION_UNREADABLE",
    "BAR_END_NOT_STRICTLY_INCREASING", "PHYSICAL_CONSISTENCY_INVALID", "SESSION_BOUNDARY_INVALID",
    "CANONICAL_ROOT_ESCAPE", "EMPTY_PARTITION", "EXPECTED_BAR_END_INVALID", "TARGET_WINDOW_INCOMPLETE",
}
_CATEGORIES = {"partition", "physical", "main_contract_map", "metadata_session", "metadata_calendar", "metadata_window"}


def _identity_valid(identity: Mapping[str, object]) -> bool:
    root, commit = identity.get("runtime_root"), identity.get("runtime_commit")
    return (isinstance(root, str) and root.startswith("/") and ".." not in Path(root).parts
            and not any(ord(c) < 32 for c in root)
            and isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) is not None)


def _findings(value: object, products: tuple[str, ...]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError
        code, category, dataset = item.get("code"), item.get("category"), item.get("dataset")
        if (not isinstance(code, str) or code not in _FINDING_CODES
                or not isinstance(category, str) or category not in _CATEGORIES
                or not isinstance(dataset, (list, tuple)) or len(dataset) != 4
                or not all(isinstance(part, str) for part in dataset) or dataset[1] not in products):
            raise ValueError
        if dataset[0] == "metadata":
            if dataset[2] not in {"rank1", "session", "calendar", "window", "exchange"} or dataset[3] != "1d":
                raise ValueError
        else:
            DatasetKey(*dataset)
        year, month = item.get("year"), item.get("month")
        if (year is None) != (month is None) or (year is not None and (
            type(year) is not int or not 1990 <= year <= 2200 or type(month) is not int or not 1 <= month <= 12
        )):
            raise ValueError
        result.append({"code": code, "category": category, "dataset": list(dataset), "year": year, "month": month})
    return result


def run_weekly_audit(
    manager: HistoricalDataManager, *, status_path: Path, products: tuple[str, ...],
    identity: Mapping[str, object], now: Callable[[], datetime],
) -> dict[str, Any]:
    """Acquire nonblocking shared lease before opening a fresh bounded read-only transaction."""
    if not _identity_valid(identity) or not products or len(set(products)) != len(products) or any(
        re.fullmatch(r"[a-z]{1,4}", symbol) is None for symbol in products
    ):
        raise ValueError("WEEKLY_AUDIT_IDENTITY_INVALID")
    started = _local_timestamp(now()).isoformat()
    payload: dict[str, Any] = {
        "schema_version": 1, "command": "data.weekly-audit", "readonly": True,
        "runtime_root": identity["runtime_root"], "runtime_commit": identity["runtime_commit"],
        "products": list(products), "scope": "operational_full_history", "status": "running",
        "started_at": started, "updated_at": started, "finished_at": None,
        "current_symbol": None, "completed": 0, "total": len(products),
        "through": None, "finding_count": 0, "findings": [], "error_code": None,
        "provider_requests": 0, "data_writes": 0,
    }
    # Status is a local diagnostic output; no Catalog, DB, provider, or data lake write.
    lease = manager.catalog.acquire_maintenance_lock()
    if lease is None:
        payload.update(status="skipped_busy", finished_at=started)
        _atomic_write_status(status_path, payload)
        return payload
    try:
        _atomic_write_status(status_path, payload)
        def observe(event: AuditProgressEvent) -> None:
            payload.update(current_symbol=event.symbol, completed=event.completed,
                           updated_at=_local_timestamp(now()).isoformat())
            _atomic_write_status(status_path, payload)
        try:
            with readonly_transaction(manager.catalog.session):
                result = manager.audit(AuditRequest(products), observer=observe)
            if result.provider_requests or result.applied or result.action != "audit":
                raise ValueError
            findings = _findings(result.as_payload()["findings"], products)
            if result.status not in {"passed", "failed"} or (result.status == "passed") != (not findings):
                raise ValueError
            payload.update(status="findings" if findings else "passed", findings=findings,
                           finding_count=len(findings), through=result.through.isoformat() if result.through else None,
                           completed=len(products), current_symbol=None)
        except Exception:
            payload.update(status="failed", error_code="WEEKLY_AUDIT_FAILED", current_symbol=None)
        payload.update(finished_at=_local_timestamp(now()).isoformat(), updated_at=_local_timestamp(now()).isoformat())
        _atomic_write_status(status_path, payload)
        return payload
    finally:
        lease.release()


def weekly_audit_health(
    path: Path | None, *, identity: Mapping[str, object], products: tuple[str, ...], now: datetime,
) -> dict[str, object]:
    """Independent optional summary; never promotes service or historical readiness."""
    empty = {"status": "not_run", "readonly": True, "finding_count": None,
             "started_at": None, "updated_at": None, "finished_at": None,
             "completed": None, "total": None, "current_symbol": None,
             "through": None, "scope": "operational_full_history"}
    if path is None or not path.exists():
        return empty
    try:
        if path.is_symlink():
            raise ValueError
        with path.open("rb") as source:
            content = source.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024:
            raise ValueError
        raw = json.loads(content)
        if (not isinstance(raw, Mapping) or not _identity_valid(identity)
                or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1
                or raw.get("command") != "data.weekly-audit" or raw.get("readonly") is not True
                or raw.get("scope") != "operational_full_history" or raw.get("products") != list(products)
                or any(raw.get(key) != identity[key] for key in ("runtime_root", "runtime_commit"))
                or type(raw.get("provider_requests")) is not int or raw["provider_requests"] != 0
                or type(raw.get("data_writes")) is not int or raw["data_writes"] != 0):
            raise ValueError
        status = raw.get("status")
        if status not in {"passed", "findings", "failed", "running", "skipped_busy"}:
            raise ValueError
        started, updated, finished = (_public_timestamp(raw.get(key)) for key in ("started_at", "updated_at", "finished_at"))
        if started is None or updated is None or not datetime.fromisoformat(started) <= datetime.fromisoformat(updated) <= now:
            raise ValueError
        if status == "running":
            if raw.get("finished_at") is not None:
                raise ValueError
        elif finished is None or not datetime.fromisoformat(started) <= datetime.fromisoformat(finished) <= datetime.fromisoformat(updated):
            raise ValueError
        findings = _findings(raw.get("findings"), products)
        through = raw.get("through")
        if through is not None and (not isinstance(through, str) or date.fromisoformat(through) > now.date()):
            raise ValueError
        if status == "passed" and through is None:
            raise ValueError
        completed, total, count = (raw.get(key) for key in ("completed", "total", "finding_count"))
        if (type(completed) is not int or type(total) is not int or total != len(products)
                or not 0 <= completed <= total or type(count) is not int or count != len(findings)
                or raw.get("current_symbol") not in (None, *products)
                or (status in {"passed", "findings"} and completed != total)
                or (status == "passed" and count != 0) or (status == "findings" and count == 0)
                or (raw.get("error_code") != ("WEEKLY_AUDIT_FAILED" if status == "failed" else None))):
            raise ValueError
        if now - datetime.fromisoformat(updated) > (timedelta(hours=2) if status == "running" else timedelta(days=8)):
            status = "stuck" if status == "running" else "stale"
        return {**empty, "status": status, "finding_count": count, "started_at": started,
                "updated_at": updated, "finished_at": finished, "completed": completed,
                "total": total, "current_symbol": raw.get("current_symbol"), "through": through}
    except (OSError, ValueError, TypeError, KeyError):
        return {**empty, "status": "invalid"}
