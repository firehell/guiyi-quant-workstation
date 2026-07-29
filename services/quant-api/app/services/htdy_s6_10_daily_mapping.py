"""Approval-D-bound exact daily rank-1 mapping materialization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.data_center import MainContractMap
from app.services.actual_contract_semantics import (
    load_strict_main_contract_mapping,
)
from app.services.htdy_s6_08_daily_mapping import (
    _exact_response,
)
from app.services.htdy_s6_10_long_running import canonical_hash


PRODUCT = "jm"
RANK = 1
RULE = "volume_open_interest"
PROVIDER = "rqdata"
SOURCE = "rqdatac.futures.get_dominant"
TASK_ID = "JM-LIVE-STABILITY-S6-10"
RECEIPT_TYPE = "htdy_s6_10_daily_mapping"
_ACTUAL_CONTRACT = re.compile(r"^JM\d{4}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HtDyS610DailyMappingError(RuntimeError):
    """Raised when the exact S6-10 daily mapping cannot be frozen."""


@dataclass(frozen=True)
class HtDyS610DailyMappingResult:
    status: str
    actual_contract: str
    mapping_sha256: str
    receipt: Mapping[str, Any]


def resolve_or_create_s610_daily_mapping(
    session: Session,
    *,
    trading_day: date,
    approval_d_hash: str,
    client: Any,
    now: datetime,
) -> HtDyS610DailyMappingResult:
    """Materialize or verify one logical mapping without committing."""

    _validate_inputs(
        trading_day=trading_day,
        approval_d_hash=approval_d_hash,
        now=now,
    )
    try:
        response = client.dominant_contracts(
            PRODUCT,
            trading_day,
            trading_day,
            RANK,
        )
        actual_contract, response_sha256 = _exact_response(
            response,
            trading_day=trading_day,
        )
    except Exception as exc:
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_rqdata_unavailable_or_invalid"
        ) from exc

    mapping = _strict_mapping(session, trading_day)
    if mapping is None:
        mapping = MainContractMap(
            instrument_symbol=PRODUCT,
            trade_date=trading_day,
            rank=RANK,
            contract_code=actual_contract,
            rule=RULE,
            provider=PROVIDER,
            data_version=(
                f"htdy_s610_{trading_day:%Y%m%d}_"
                f"{approval_d_hash[:12]}_v1"
            ),
            raw_payload={
                "schema_version": 1,
                "task_id": TASK_ID,
                "source": SOURCE,
                "approval_d_hash": approval_d_hash,
                "rqdata_response_sha256": response_sha256,
                "observed_at": _utc_iso(now),
                "purpose": "observation_only",
                "auto_order": False,
            },
        )
        session.add(mapping)
        session.flush()
        status = "created"
    else:
        selected_contract = _normalized_contract(mapping.contract_code)
        if selected_contract != actual_contract:
            raise HtDyS610DailyMappingError(
                "s610_daily_mapping_rqdata_drift"
            )
        status = "existing_verified"

    identity = _mapping_identity(mapping)
    mapping_sha256 = canonical_hash(identity)
    receipt = {
        "schema_version": 1,
        "receipt_type": RECEIPT_TYPE,
        "task_id": TASK_ID,
        "status": status,
        "source": SOURCE,
        "product": PRODUCT,
        "rank": RANK,
        "rule": RULE,
        "provider": PROVIDER,
        "trading_day": trading_day.isoformat(),
        "actual_contract": actual_contract,
        "mapping_identity": identity,
        "mapping_sha256": mapping_sha256,
        "mapping_id_independent": True,
        "rqdata_response_sha256": response_sha256,
        "approval_d_hash": approval_d_hash,
        "observed_at": _utc_iso(now),
        "purpose": "observation_only",
        "auto_order": False,
    }
    receipt["receipt_hash"] = _receipt_hash(receipt)
    return HtDyS610DailyMappingResult(
        status=status,
        actual_contract=actual_contract,
        mapping_sha256=mapping_sha256,
        receipt=receipt,
    )


def verify_s610_daily_mapping_receipt(
    session: Session,
    *,
    receipt: Mapping[str, Any],
    trading_day: date,
    approval_d_hash: str,
) -> HtDyS610DailyMappingResult:
    """Rebind one create-only receipt to the current logical DB mapping."""

    if not _receipt_contract_valid(
        receipt,
        trading_day=trading_day,
        approval_d_hash=approval_d_hash,
    ):
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_receipt_invalid"
        )
    mapping = _strict_mapping(session, trading_day)
    if mapping is None:
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_receipt_database_drift"
        )
    identity = _mapping_identity(mapping)
    mapping_sha256 = canonical_hash(identity)
    actual_contract = _normalized_contract(mapping.contract_code)
    if (
        receipt.get("actual_contract") != actual_contract
        or receipt.get("mapping_identity") != identity
        or receipt.get("mapping_sha256") != mapping_sha256
    ):
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_receipt_database_drift"
        )
    return HtDyS610DailyMappingResult(
        status=str(receipt["status"]),
        actual_contract=actual_contract,
        mapping_sha256=mapping_sha256,
        receipt=dict(receipt),
    )


def result_payload(
    result: HtDyS610DailyMappingResult,
) -> dict[str, Any]:
    return asdict(result)


def _strict_mapping(
    session: Session,
    trading_day: date,
) -> MainContractMap | None:
    try:
        return load_strict_main_contract_mapping(
            session,
            instrument_symbol=PRODUCT,
            trade_date=trading_day,
            provider=PROVIDER,
            rule=RULE,
            rank=RANK,
        )
    except ValueError as exc:
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_database_conflict"
        ) from exc


def _mapping_identity(mapping: MainContractMap) -> dict[str, Any]:
    return {
        "trade_date": mapping.trade_date.isoformat(),
        "contract_code": mapping.contract_code,
        "normalized_contract_code": _normalized_contract(
            mapping.contract_code
        ),
        "rank": mapping.rank,
        "rule": mapping.rule,
        "provider": mapping.provider,
        "data_version": mapping.data_version,
    }


def _receipt_contract_valid(
    receipt: Mapping[str, Any],
    *,
    trading_day: date,
    approval_d_hash: str,
) -> bool:
    return bool(
        receipt.get("schema_version") == 1
        and receipt.get("receipt_type") == RECEIPT_TYPE
        and receipt.get("task_id") == TASK_ID
        and receipt.get("status") in {"created", "existing_verified"}
        and receipt.get("source") == SOURCE
        and receipt.get("product") == PRODUCT
        and receipt.get("rank") == RANK
        and receipt.get("rule") == RULE
        and receipt.get("provider") == PROVIDER
        and receipt.get("trading_day") == trading_day.isoformat()
        and receipt.get("approval_d_hash") == approval_d_hash
        and receipt.get("mapping_id_independent") is True
        and receipt.get("purpose") == "observation_only"
        and receipt.get("auto_order") is False
        and _ACTUAL_CONTRACT.fullmatch(
            str(receipt.get("actual_contract") or "")
        )
        and _SHA256.fullmatch(
            str(receipt.get("mapping_sha256") or "")
        )
        and _SHA256.fullmatch(
            str(receipt.get("rqdata_response_sha256") or "")
        )
        and _SHA256.fullmatch(
            str(receipt.get("receipt_hash") or "")
        )
        and _aware_iso(receipt.get("observed_at"))
        and receipt.get("receipt_hash") == _receipt_hash(receipt)
    )


def _validate_inputs(
    *,
    trading_day: date,
    approval_d_hash: str,
    now: datetime,
) -> None:
    if type(trading_day) is not date:
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_trading_day_invalid"
        )
    if not _SHA256.fullmatch(str(approval_d_hash or "")):
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_approval_d_hash_invalid"
        )
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_now_invalid"
        )


def _normalized_contract(value: Any) -> str:
    contract = str(value or "").strip().upper()
    if not _ACTUAL_CONTRACT.fullmatch(contract):
        raise HtDyS610DailyMappingError(
            "s610_daily_mapping_contract_invalid"
        )
    return contract


def _receipt_hash(receipt: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            key: value
            for key, value in receipt.items()
            if key != "receipt_hash"
        }
    )


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _aware_iso(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed.tzinfo is not None
