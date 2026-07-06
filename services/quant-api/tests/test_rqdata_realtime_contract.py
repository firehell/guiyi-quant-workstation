from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "rqdata_realtime_poc.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("rqdata_realtime_poc", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_dry_run_does_not_construct_real_client(monkeypatch, capsys) -> None:
    module = _load_module()

    def fail_client_factory():
        raise AssertionError("dry-run must not construct RqDataClient")

    exit_code = module.main([], client_factory=fail_client_factory, environ={})

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run"
    assert {item["status"] for item in payload["results"]} == {"skipped"}


def test_redacts_sensitive_values_from_errors(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("RQDATA_PASSWORD", "super-secret-password")
    monkeypatch.setenv("RQDATA_LICENSE_KEY", "license-value-123")

    redacted = module.redact_message("bad super-secret-password and license-value-123")

    assert "super-secret-password" not in redacted
    assert "license-value-123" not in redacted
    assert "[REDACTED]" in redacted


def test_missing_rqdata_package_returns_structured_failure(monkeypatch, capsys) -> None:
    module = _load_module()
    original_import = module.importlib.import_module

    def fake_import(name: str):
        if name == "rqdatac":
            raise ImportError("no module named rqdatac")
        return original_import(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import)

    exit_code = module.main(["--run-readonly"], client_factory=lambda: None, environ={})

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    package_result = payload["results"][0]
    assert package_result["capability"] == "rqdatac_import"
    assert package_result["status"] == "fail"
    assert package_result["error_type"] == "ImportError"


def test_mock_success_generates_capability_matrix(capsys) -> None:
    module = _load_module()

    class FakeClient:
        rqdatac = type("Rq", (), {"__version__": "3.2.5"})()

        def all_future_instruments(self):
            return pd.DataFrame([{"order_book_id": "JM2609", "underlying_symbol": "JM"}])

        def trading_dates(self, start_date, end_date):
            return [start_date]

        def trading_periods(self, products):
            return pd.DataFrame([{"product": "JM", "start_time": "21:00:00", "end_time": "23:00:00"}])

        def dominant_contracts(self, product, start_date, end_date, rank):
            return pd.DataFrame([{"date": start_date, "dominant": "JM2609"}])

        def continuous_contracts(self, product, start_date, end_date):
            return pd.DataFrame([{"date": start_date, "front_month": "JM2609"}])

        def ex_factor(self, product, start_date, end_date):
            return pd.DataFrame([{"ex_date": start_date, "ex_factor": 1.0}])

        def trading_parameters(self, contract, start_date, end_date):
            return pd.DataFrame([{"date": start_date, "long_margin_ratio": 0.1, "open_commission": 0.0001}])

        def price_tick(self, contract):
            return 0.5

        def contract_multiplier(self, contract):
            return 60

        def exchange_daily(self, contract, start_date, end_date):
            return pd.DataFrame([{"date": start_date, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1, "open_interest": 2}])

        def contract_bars(self, contract, start_date, end_date, frequency):
            return pd.DataFrame([{"datetime": pd.Timestamp("2026-01-05 09:01:00"), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1}])

        def warehouse_stocks(self, product, start_date, end_date):
            return pd.DataFrame([{"date": start_date, "quantity": 1}])

        def roll_yield(self, product, start_date, end_date):
            return pd.DataFrame([{"date": start_date, "roll_yield": 0.01}])

        def basis(self, contract, start_date, end_date):
            return pd.DataFrame([{"date": start_date, "basis": 1}])

    exit_code = module.main(["--run-readonly"], client_factory=FakeClient, environ={})

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "readonly"
    assert any(item["capability"] == "historical_1m_sample" and item["status"] == "pass" for item in payload["results"])
    assert any(item["sample_columns"] for item in payload["results"])


def test_mock_exception_records_error_type_without_crashing(capsys) -> None:
    module = _load_module()

    class BrokenClient:
        rqdatac = type("Rq", (), {"__version__": "3.2.5"})()

        def all_future_instruments(self):
            raise PermissionError("no permission")

    exit_code = module.main(["--run-readonly"], client_factory=BrokenClient, environ={})

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(item["error_type"] == "PermissionError" for item in payload["results"])


def test_script_does_not_reference_data_writes_or_database_connections() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    forbidden = [
        "SessionLocal",
        "create_engine",
        "to_parquet",
        "write_parquet",
        "data/manifests",
        "data/raw",
        "data/parquet",
    ]
    for token in forbidden:
        assert token not in source


def test_output_does_not_contain_secret_values(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setenv("RQDATA_PASSWORD", "super-secret-password")
    monkeypatch.setenv("RQDATA_LICENSE_KEY", "license-value-123")

    exit_code = module.main(["--dry-run"], environ=dict(module.os.environ))

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "super-secret-password" not in output
    assert "license-value-123" not in output
    assert "present" in output or "missing" in output
