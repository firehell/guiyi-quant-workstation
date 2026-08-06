"""Scoped post-publish verifier for historical update affected windows only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence

from app.data_core.contracts import DatasetKey
from app.services.data_operations.contracts import (
    CommandStatus,
    DataTarget,
    PublicError,
    TargetResult,
)
from app.services.data_operations.guards import to_dataset_key


class _PartitionLike(Protocol):
    coverage_start: object
    coverage_end: object


class _CatalogLike(Protocol):
    def list_effective_partitions(self, key: DatasetKey) -> Sequence[_PartitionLike]: ...

    def list_gaps(self, key: DatasetKey) -> Sequence[object]: ...


@dataclass(frozen=True, slots=True)
class VerifyFinding:
    code: str
    target: DataTarget
    facts: Mapping[str, object]


class TargetWindowVerifier:
    """Verify only the windows touched by this update round.

    Intentionally does not import ``task07_target_canonical`` and does not scan
    full-history physical residuals.
    """

    def __init__(
        self,
        *,
        catalog: _CatalogLike,
        market_data_readable: Callable[[DataTarget], bool] | None = None,
    ) -> None:
        self._catalog = catalog
        self._market_data_readable = market_data_readable

    def verify(self, targets: Sequence[DataTarget]) -> tuple[TargetResult, ...]:
        results: list[TargetResult] = []
        for target in targets:
            findings = self._verify_one(target)
            if findings:
                results.append(
                    TargetResult(
                        target=target,
                        status=CommandStatus.ERROR,
                        detail={"findings": [item.code for item in findings]},
                        error=PublicError(
                            code=findings[0].code,
                            type="VerificationError",
                        ),
                    )
                )
            else:
                results.append(
                    TargetResult(
                        target=target,
                        status=CommandStatus.PASSED,
                        detail={"verified_window": True},
                    )
                )
        return tuple(results)

    def _verify_one(self, target: DataTarget) -> tuple[VerifyFinding, ...]:
        dataset = to_dataset_key(target)
        findings: list[VerifyFinding] = []
        partitions = tuple(self._catalog.list_effective_partitions(dataset))
        if not partitions:
            findings.append(
                VerifyFinding(
                    code="UPDATE_COVERAGE_MISSING",
                    target=target,
                    facts={"reason": "no_partitions"},
                )
            )
            return tuple(findings)
        covered = False
        for partition in partitions:
            start = partition.coverage_start
            end = partition.coverage_end
            if start <= target.start and end >= target.end:
                covered = True
                break
            if start < target.end and target.start < end:
                covered = True
        if not covered:
            findings.append(
                VerifyFinding(
                    code="UPDATE_COVERAGE_MISSING",
                    target=target,
                    facts={"reason": "window_not_covered"},
                )
            )
        gaps = tuple(self._catalog.list_gaps(dataset))
        if gaps:
            findings.append(
                VerifyFinding(
                    code="UPDATE_GAP_PRESENT",
                    target=target,
                    facts={"gap_count": len(gaps)},
                )
            )
        if self._market_data_readable is not None:
            try:
                readable = self._market_data_readable(target)
            except Exception as exc:  # noqa: BLE001 - surface as finding
                findings.append(
                    VerifyFinding(
                        code="UPDATE_MARKET_DATA_UNREADABLE",
                        target=target,
                        facts={"type": type(exc).__name__},
                    )
                )
            else:
                if not readable:
                    findings.append(
                        VerifyFinding(
                            code="UPDATE_MARKET_DATA_UNREADABLE",
                            target=target,
                            facts={"reason": "empty"},
                        )
                    )
        return tuple(findings)
