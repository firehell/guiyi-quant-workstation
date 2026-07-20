from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.after_market_archive_gate import ArchiveGateError
from app.services.provider_readiness import ProviderReadinessError


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "after_market_archive.py"
SPEC = importlib.util.spec_from_file_location("after_market_archive_cli", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_prepare_failure_reports_trading_day_not_closed() -> None:
    payload, exit_code = MODULE._prepare_failure_result(ArchiveGateError("trading_day_not_closed"))

    assert payload == {"status": "TRADING_DAY_NOT_CLOSED", "reason": "trading_day_not_closed"}
    assert exit_code == 3


def test_prepare_failure_reports_provider_pending_without_detail_leak() -> None:
    payload, exit_code = MODULE._prepare_failure_result(
        ProviderReadinessError("provider_data_pending:future_minbar")
    )

    assert payload == {"status": "PROVIDER_FINAL_PENDING", "reason": "provider_data_pending"}
    assert exit_code == 3


def test_prepare_failure_redacts_unknown_exception_message() -> None:
    payload, exit_code = MODULE._prepare_failure_result(RuntimeError("password=do-not-print"))

    assert payload == {"status": "failed", "error_type": "RuntimeError"}
    assert exit_code == 1
