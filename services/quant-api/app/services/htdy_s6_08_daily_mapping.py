"""Create-only daily rank-1 mapping for the exact HTDY S6-08 pilot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
import hashlib
import json
import re
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import MainContractMap


PRODUCT = "jm"
RANK = 1
RULE = "volume_open_interest"
PROVIDER = "rqdata"
SOURCE = "rqdatac.futures.get_dominant"
_ACTUAL_CONTRACT = re.compile(r"^JM\d{4}$")


class HtDyDailyMappingError(RuntimeError):
    """Raised when the daily actual-contract mapping cannot be frozen."""


@dataclass(frozen=True)
class HtDyDailyMappingResult:
    status: str
    actual_contract: str
    mapping_id: int
    mapping_sha256: str
    receipt: Mapping[str, Any]


def resolve_or_create_daily_mapping(
    session: Session,
    *,
    trading_day: date,
    parent_hash: str,
    client: Any,
    now: datetime,
) -> HtDyDailyMappingResult:
    """Verify RQData rank-1 and create one exact DB mapping when absent.

    The caller owns the transaction.  This function flushes but never commits.
    """

    _validate_inputs(
        trading_day=trading_day,
        parent_hash=parent_hash,
        now=now,
    )
    try:
        response = client.dominant_contracts(
            PRODUCT,
            trading_day,
            trading_day,
            RANK,
        )
    except Exception as exc:
        raise HtDyDailyMappingError(
            "daily_mapping_rqdata_unavailable"
        ) from exc
    actual_contract, response_sha256 = _exact_response(
        response,
        trading_day=trading_day,
    )
    rows = list(
        session.scalars(
            select(MainContractMap).where(
                MainContractMap.instrument_symbol == PRODUCT,
                MainContractMap.trade_date == trading_day,
                MainContractMap.rank == RANK,
                MainContractMap.rule == RULE,
                MainContractMap.provider == PROVIDER,
            )
        )
    )
    if len(rows) > 1:
        contracts = {str(row.contract_code).strip().upper() for row in rows}
        reason = (
            "daily_mapping_database_conflict"
            if len(contracts) > 1
            else "daily_mapping_database_duplicate"
        )
        raise HtDyDailyMappingError(reason)

    if rows:
        mapping = rows[0]
        if str(mapping.contract_code).strip().upper() != actual_contract:
            raise HtDyDailyMappingError("daily_mapping_rqdata_drift")
        status = "existing_verified"
    else:
        mapping = MainContractMap(
            instrument_symbol=PRODUCT,
            trade_date=trading_day,
            rank=RANK,
            contract_code=actual_contract,
            rule=RULE,
            provider=PROVIDER,
            data_version=(
                f"htdy_s608_{trading_day:%Y%m%d}_{parent_hash[:12]}"
            ),
            raw_payload={
                "schema_version": 1,
                "task_id": "V1-HTDY-05-S6-08-REAL-ACCEPTANCE",
                "source": SOURCE,
                "parent_packet_hash": parent_hash,
                "rqdata_response_sha256": response_sha256,
                "observed_at": _utc_iso(now),
            },
        )
        session.add(mapping)
        session.flush()
        status = "created"

    identity = _mapping_identity(mapping)
    mapping_sha256 = _canonical_hash(identity)
    receipt = {
        "schema_version": 1,
        "status": status,
        "source": SOURCE,
        "product": PRODUCT,
        "rank": RANK,
        "rule": RULE,
        "provider": PROVIDER,
        "trading_day": trading_day.isoformat(),
        "actual_contract": actual_contract,
        "mapping_id": mapping.id,
        "mapping_sha256": mapping_sha256,
        "rqdata_response_sha256": response_sha256,
        "parent_packet_hash": parent_hash,
        "observed_at": _utc_iso(now),
    }
    return HtDyDailyMappingResult(
        status=status,
        actual_contract=actual_contract,
        mapping_id=mapping.id,
        mapping_sha256=mapping_sha256,
        receipt=receipt,
    )


def result_payload(result: HtDyDailyMappingResult) -> dict[str, Any]:
    """Return a plain payload for Runtime adapters and evidence writers."""

    return asdict(result)


def verify_daily_mapping_receipt(
    session: Session,
    *,
    receipt: Mapping[str, Any],
    trading_day: date,
    parent_hash: str,
) -> HtDyDailyMappingResult:
    """Re-bind an existing create-only receipt to the current DB row."""

    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") not in {"created", "existing_verified"}
        or receipt.get("source") != SOURCE
        or receipt.get("product") != PRODUCT
        or receipt.get("rank") != RANK
        or receipt.get("rule") != RULE
        or receipt.get("provider") != PROVIDER
        or receipt.get("trading_day") != trading_day.isoformat()
        or receipt.get("parent_packet_hash") != parent_hash
        or not _sha256(receipt.get("mapping_sha256"))
        or not _sha256(receipt.get("rqdata_response_sha256"))
        or not _aware_iso(receipt.get("observed_at"))
    ):
        raise HtDyDailyMappingError("daily_mapping_receipt_invalid")
    rows = list(
        session.scalars(
            select(MainContractMap).where(
                MainContractMap.instrument_symbol == PRODUCT,
                MainContractMap.trade_date == trading_day,
                MainContractMap.rank == RANK,
                MainContractMap.rule == RULE,
                MainContractMap.provider == PROVIDER,
            )
        )
    )
    if len(rows) != 1:
        raise HtDyDailyMappingError("daily_mapping_receipt_database_drift")
    mapping = rows[0]
    actual_contract = str(mapping.contract_code).strip().upper()
    mapping_sha256 = _canonical_hash(_mapping_identity(mapping))
    if (
        receipt.get("actual_contract") != actual_contract
        or receipt.get("mapping_id") != mapping.id
        or receipt.get("mapping_sha256") != mapping_sha256
        or not _ACTUAL_CONTRACT.fullmatch(actual_contract)
    ):
        raise HtDyDailyMappingError("daily_mapping_receipt_database_drift")
    return HtDyDailyMappingResult(
        status=str(receipt["status"]),
        actual_contract=actual_contract,
        mapping_id=mapping.id,
        mapping_sha256=mapping_sha256,
        receipt=dict(receipt),
    )


def _validate_inputs(
    *,
    trading_day: date,
    parent_hash: str,
    now: datetime,
) -> None:
    if type(trading_day) is not date:
        raise HtDyDailyMappingError("daily_mapping_trading_day_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(parent_hash)):
        raise HtDyDailyMappingError("daily_mapping_parent_hash_invalid")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise HtDyDailyMappingError("daily_mapping_now_invalid")


def _exact_response(
    value: Any,
    *,
    trading_day: date,
) -> tuple[str, str]:
    if not isinstance(value, pd.DataFrame) or value.empty:
        raise HtDyDailyMappingError("daily_mapping_rqdata_invalid")
    frame = value.copy()
    date_column = _first_column(
        frame,
        ("date", "trade_date", "trading_date", "datetime", "index"),
    )
    contract_column = _first_column(
        frame,
        ("contract", "dominant", "order_book_id", "symbol", 0, "0"),
    )
    if date_column is None or contract_column is None or len(frame) != 1:
        raise HtDyDailyMappingError("daily_mapping_rqdata_invalid")
    parsed_day = pd.to_datetime(
        frame.iloc[0][date_column],
        errors="coerce",
    )
    if pd.isna(parsed_day) or parsed_day.date() != trading_day:
        raise HtDyDailyMappingError("daily_mapping_rqdata_invalid")
    contract = str(frame.iloc[0][contract_column]).strip().upper()
    if not _ACTUAL_CONTRACT.fullmatch(contract):
        raise HtDyDailyMappingError("daily_mapping_rqdata_invalid")
    canonical_response = {
        "source": SOURCE,
        "product": PRODUCT,
        "rank": RANK,
        "trading_day": trading_day.isoformat(),
        "actual_contract": contract,
    }
    return contract, _canonical_hash(canonical_response)


def _first_column(
    frame: pd.DataFrame,
    candidates: tuple[Any, ...],
) -> Any | None:
    return next(
        (candidate for candidate in candidates if candidate in frame.columns),
        None,
    )


def _mapping_identity(mapping: MainContractMap) -> dict[str, Any]:
    return {
        "trade_date": mapping.trade_date.isoformat(),
        "contract_code": mapping.contract_code,
        "rank": mapping.rank,
        "rule": mapping.rule,
        "provider": mapping.provider,
        "data_version": mapping.data_version,
    }


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _aware_iso(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed.tzinfo is not None
