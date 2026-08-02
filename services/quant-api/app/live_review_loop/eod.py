from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.live_review_loop.contracts import canonical_digest
from app.live_review_loop.evaluator import ApprovedEma21DirectionEvaluator
from app.data_core.catalog import GapWindow, HistoricalCatalog
from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.models.data_center import utc_now
from app.models.data_core import MarketDataset
from app.models.live_review_loop import SignalDecision, SignalDecisionReconciliation
from app.live_review_loop.provider_final import ProviderFinalSnapshot


class ReconciliationConflictError(RuntimeError):
    pass


class EodReconciliationService:
    """Provider-final comparison only; this module has no event/notification dependency."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def complete(
        self,
        decision: SignalDecision,
        *,
        recipe_version: str,
        provider_final_snapshot: Mapping[str, Any],
        provider_data_version: str,
        provider_request_digest: str,
        recomputed_result: Mapping[str, Any],
    ) -> SignalDecisionReconciliation:
        if (
            not provider_data_version.strip()
            or re.fullmatch(r"[0-9a-f]{64}", provider_request_digest) is None
        ):
            raise ValueError("EOD_PROVIDER_LINEAGE_INVALID")
        provider_snapshot = dict(provider_final_snapshot)
        _validate_reconciliation_contract(decision, recipe_version, provider_snapshot)
        result = dict(recomputed_result)
        provider_digest = canonical_digest(provider_snapshot)
        result_digest = canonical_digest(result)
        data_changed = provider_digest != decision.input_digest
        result_changed = result_digest != decision.result_digest
        outcome = _outcome(data_changed=data_changed, result_changed=result_changed)
        row = self._existing(decision.id, recipe_version)
        if row is not None and row.status == "completed":
            if (
                row.provider_final_digest != provider_digest
                or row.provider_data_version != provider_data_version
                or row.provider_request_digest != provider_request_digest
                or row.recomputed_result_digest != result_digest
                or row.outcome != outcome
            ):
                raise ReconciliationConflictError("EOD_RECONCILIATION_CONFLICT")
            return row
        if row is None:
            row = SignalDecisionReconciliation(
                decision_id=decision.id,
                recipe_version=recipe_version,
                status="pending",
                window_start=decision.input_window_start,
                window_end=decision.input_window_end,
                provider_final_snapshot={},
                recomputed_result={},
                attempt_count=0,
            )
            self.session.add(row)
        row.status = "completed"
        row.outcome = outcome
        row.data_changed = data_changed
        row.result_changed = result_changed
        row.provider_final_snapshot = provider_snapshot
        row.provider_final_digest = provider_digest
        row.provider_data_version = provider_data_version
        row.provider_request_digest = provider_request_digest
        row.recomputed_result = result
        row.recomputed_result_digest = result_digest
        row.error_code = None
        row.error_message = None
        row.completed_at = utc_now()
        self.session.flush()
        return row

    def run(
        self,
        decision: SignalDecision,
        *,
        recipe_version: str,
        provider_final_loader: Callable[[SignalDecision], ProviderFinalSnapshot],
        gap_recorder: Callable[[SignalDecision, datetime, datetime], None],
    ) -> SignalDecisionReconciliation:
        _validate_recipe(decision, recipe_version)
        row = self._existing(decision.id, recipe_version)
        if row is not None and row.status == "completed":
            return row
        if row is not None and row.attempt_count >= 3:
            return row
        if row is None:
            row = SignalDecisionReconciliation(
                decision_id=decision.id,
                recipe_version=recipe_version,
                status="pending",
                window_start=decision.input_window_start,
                window_end=decision.input_window_end,
                provider_final_snapshot={},
                recomputed_result={},
                attempt_count=0,
            )
            self.session.add(row)
            self.session.flush()
        try:
            provider_final = provider_final_loader(decision)
            if not isinstance(provider_final, ProviderFinalSnapshot):
                raise TypeError("EOD_PROVIDER_FINAL_SNAPSHOT_TYPE")
        except Exception as exc:  # noqa: BLE001 - bounded failure is persisted for the exact window.
            row.attempt_count = min(row.attempt_count + 1, 3)
            row.status = "failed" if row.attempt_count == 3 else "retry_pending"
            row.error_code = type(exc).__name__
            row.error_message = _redacted_error_fingerprint(exc)
            if row.attempt_count == 3:
                gap_recorder(decision, decision.input_window_start, decision.input_window_end)
            self.session.flush()
            return row
        result = ApprovedEma21DirectionEvaluator()(
            decision,
            provider_final.strategy_input,
        )
        return self.complete(
            decision,
            recipe_version=recipe_version,
            provider_final_snapshot=provider_final.strategy_input,
            provider_data_version=provider_final.data_version,
            provider_request_digest=provider_final.request_digest,
            recomputed_result=result,
        )

    def _existing(self, decision_id: int, recipe_version: str) -> SignalDecisionReconciliation | None:
        return self.session.scalar(
            select(SignalDecisionReconciliation).where(
                SignalDecisionReconciliation.decision_id == decision_id,
                SignalDecisionReconciliation.recipe_version == recipe_version,
            )
        )


def _outcome(*, data_changed: bool, result_changed: bool) -> str:
    if data_changed and result_changed:
        return "data_and_result_changed"
    if data_changed:
        return "data_changed"
    if result_changed:
        return "result_changed"
    return "unchanged"


def _redacted_error_fingerprint(exc: Exception) -> str:
    digest = canonical_digest(
        {
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    )
    return f"redacted_sha256:{digest}"


def _validate_reconciliation_contract(
    decision: SignalDecision,
    recipe_version: str,
    provider_final_snapshot: Mapping[str, Any],
) -> None:
    _validate_recipe(decision, recipe_version)
    original = decision.input_snapshot
    identity_keys = ("schema_version", "trigger", "strategy", "mapping")
    original_identity = {key: original.get(key) for key in identity_keys}
    provider_identity = {key: provider_final_snapshot.get(key) for key in identity_keys}
    if canonical_digest(provider_identity) != canonical_digest(original_identity):
        raise ValueError("EOD_INPUT_IDENTITY_MISMATCH")


def _validate_recipe(decision: SignalDecision, recipe_version: str) -> None:
    strategy = decision.input_snapshot.get("strategy")
    if not isinstance(strategy, Mapping) or strategy.get("recipe_version") != recipe_version:
        raise ValueError("EOD_RECIPE_MISMATCH")


def record_eod_data_gap(
    session: Session,
    decision: SignalDecision,
    window_start: datetime,
    window_end: datetime,
):
    raw = decision.dataset_key
    key = DatasetKey(
        provider=str(raw["provider"]),
        dataset_kind=DatasetKind(str(raw["dataset_kind"])),
        symbol=str(raw["symbol"]),
        contract_or_series=str(raw["contract_or_series"]),
        frequency=BarFrequency(str(raw["frequency"])),
        adjustment=str(raw["adjustment"]),
        schema_version=str(raw["schema_version"]),
    )
    existing = session.scalar(
        select(MarketDataset).where(
            MarketDataset.provider == key.provider,
            MarketDataset.dataset_kind == key.dataset_kind.value,
            MarketDataset.symbol == key.symbol,
            MarketDataset.contract_or_series == key.contract_or_series,
            MarketDataset.frequency == key.frequency.value,
            MarketDataset.adjustment == key.adjustment,
            MarketDataset.schema_version == key.schema_version,
        )
    )
    if existing is None:
        raise RuntimeError("EOD_BOUND_DATASET_NOT_FOUND")
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=UTC)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=UTC)
    return HistoricalCatalog(session).record_gap(
        key,
        GapWindow(
            gap_start=window_start,
            gap_end=window_end,
            reason_code="eod_provider_final_unavailable",
            details={
                "decision_key": decision.decision_key,
                "fingerprint": decision.fingerprint,
                "actual_contract": decision.actual_contract,
            },
        ),
    )
