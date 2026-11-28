from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.backtest_center.contracts import RunConfig
from app.research_center.advanced import create_request, run_binding


def test_plan_validates_every_native_fold_before_publication():
    config = RunConfig.model_validate({"product": "fu", "contract": "FU2603", "warmup_start": "2025-12-22",
                                       "start": "2026-01-06", "end": "2026-01-23"})
    fold = {
        "train_warmup_start": date(2020, 1, 1), "train_start": date(2026, 1, 6),
        "train_end": date(2026, 1, 14), "test_warmup_start": date(2025, 12, 22),
        "test_start": date(2026, 1, 15), "test_end": date(2026, 1, 23),
    }
    with pytest.raises(ValidationError, match="BACKTEST_WINDOW_TOO_LARGE"):
        create_request(config, [0, 1], [fold], "statistics-v02:test")
    experiment = create_request(config, [0, 1], [{**fold, "train_warmup_start": date(2025, 12, 22)}],
                                "statistics-v02:test")
    assert experiment.kind == "oos"
    assert experiment.configs[0].parameters == {}
    assert int(experiment.configs[1].parameters["execution_delay_minutes"]) == 1


def test_search_source_digest_binds_owner_configuration_and_verified_snapshot():
    publication = {"run_id": "a", "result_digest": "a" * 64,
                   "config": {"slippage_ticks": 0}, "snapshot": {"data_revision": "old"}}
    owner = Path("/tmp/backtests.sqlite3")
    original = run_binding(owner, publication)
    assert run_binding(owner, {**publication, "config": {"slippage_ticks": 1}}) != original
    assert run_binding(owner, {**publication, "snapshot": {"data_revision": "new"}}) != original
    assert run_binding(owner.with_name("other.sqlite3"), publication) != original
