"""Scoped verifier must not scan full history or import task07 target canonical."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.data_core.contracts import BarFrequency, DatasetKind
from app.services.data_operations.contracts import CommandStatus, DataTarget
from app.services.data_operations.target_verifier import TargetWindowVerifier


def test_verifier_only_checks_requested_targets() -> None:
    start = datetime(2026, 8, 3, tzinfo=UTC)
    end = datetime(2026, 8, 4, tzinfo=UTC)
    target = DataTarget(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
        start=start,
        end=end,
    )

    class Catalog:
        def list_effective_partitions(self, key):
            del key
            return [
                type(
                    "P",
                    (),
                    {"coverage_start": start, "coverage_end": end},
                )()
            ]

        def list_gaps(self, key):
            del key
            return ()

    results = TargetWindowVerifier(catalog=Catalog()).verify((target,))
    assert len(results) == 1
    assert results[0].status is CommandStatus.PASSED


def test_verifier_module_does_not_depend_on_task07_target_canonical() -> None:
    import app.services.data_operations.target_verifier as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "task07_target_canonical" not in source
