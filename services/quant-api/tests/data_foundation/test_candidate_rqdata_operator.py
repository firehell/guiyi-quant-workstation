from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.market_data.gate_a_operator import (
    CandidateRunConfig,
    GateAOperatorError,
    default_candidate_root,
    reset_candidate_storage,
    run_rqdata_update,
)
from app.market_data.maintenance import MaintenanceResult


def test_default_candidate_root_uses_through_suffix() -> None:
    root = default_candidate_root(date(2026, 8, 7))
    assert root.name == "through=2026-08-07"


def test_reset_candidate_storage_deletes_parquet_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    leaf = root / "kind=continuous/symbol=jm/series=MAIN/frequency=1d/year=2026/month=08"
    leaf.mkdir(parents=True)
    (leaf / "part.parquet").write_bytes(b"pq")
    (leaf / "manifest.json").write_text("{}", encoding="utf-8")

    result = reset_candidate_storage(root)

    assert result["deleted_paths"] >= 2
    assert not (leaf / "part.parquet").exists()


def test_run_rqdata_update_requires_intent_for_apply(tmp_path: Path) -> None:
    config = CandidateRunConfig(
        through=date(2026, 8, 7),
        candidate_root=(tmp_path / "candidate").resolve(),
        candidate_catalog="guiyi_canonical_candidate_20260807",
        products=("jm",),
    )
    session = MagicMock()

    with pytest.raises(GateAOperatorError, match="GATE_A_APPLY_INTENT_REQUIRED"):
        run_rqdata_update(
            config,
            session=session,
            apply=True,
            intent_confirmed=False,
        )


def test_run_rqdata_update_uses_candidate_historical_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = CandidateRunConfig(
        through=date(2026, 8, 7),
        candidate_root=(tmp_path / "candidate").resolve(),
        candidate_catalog="guiyi_canonical_candidate_20260807",
        products=("jm",),
    )
    session = MagicMock()
    manager = MagicMock()
    manager.legacy = None
    manager.update.return_value = MaintenanceResult(
        action="update",
        status="noop",
        through=date(2026, 8, 7),
        planned=0,
        applied=0,
        blocked=0,
        failed=0,
        provider_requests=0,
    )
    monkeypatch.setattr(
        "app.market_data.gate_a_operator.build_candidate_historical_data_manager",
        lambda _session, root: manager,
    )
    monkeypatch.setattr(
        "app.market_data.gate_a_operator.canonical_root",
        lambda: (tmp_path / "production").resolve(),
    )

    payload = run_rqdata_update(
        config,
        session=session,
        apply=False,
        intent_confirmed=False,
    )

    manager.update.assert_called_once()
    assert payload["action"] == "candidate_rqdata_update"
    assert payload["status"] == "noop"
