"""The P8 benchmark must reject unsafe targets before a connection is opened."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[4] / "scripts/reference_trading_benchmark.py"
SPEC = importlib.util.spec_from_file_location("reference_trading_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://test:test@127.0.0.1:5432/guiyi_reference_isolated_test",
    "postgresql+psycopg://test:test@remote.example:55433/guiyi_reference_isolated_test",
    "postgresql+psycopg://test:test@127.0.0.1:55433/guiyi_production",
    "postgresql+psycopg://test:test@127.0.0.1:55433/guiyi_reference_isolated_test?host=remote.example&port=5432",
    "postgresql+psycopg://test:test@127.0.0.1:55433/guiyi_reference_isolated_test?service=production",
    "sqlite+pysqlite:///:memory:",
])
def test_benchmark_rejects_unsafe_target_without_connecting(monkeypatch, url):
    monkeypatch.setattr(benchmark, "create_engine", lambda *_args, **_kwargs: pytest.fail("connected"))
    with pytest.raises(ValueError, match="dedicated loopback"):
        benchmark.validate_target({"GUIYI_ISOLATED_MIGRATION_DATABASE_URL": url})


def test_benchmark_rejects_runtime_database_url_without_connecting(monkeypatch):
    monkeypatch.setattr(benchmark, "create_engine", lambda *_args, **_kwargs: pytest.fail("connected"))
    with pytest.raises(ValueError, match="DATABASE_URL must be unset"):
        benchmark.validate_target({
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL":
                "postgresql+psycopg://test:test@127.0.0.1:55433/guiyi_reference_isolated_test",
            "DATABASE_URL": "postgresql+psycopg://runtime@localhost:5432/guiyi",
        })


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGHOST", "PGSERVICE", "PGSERVICEFILE"])
def test_benchmark_rejects_libpq_environment_routing_before_connect(monkeypatch, name):
    monkeypatch.setattr(benchmark, "create_engine", lambda *_args, **_kwargs: pytest.fail("connected"))
    with pytest.raises(ValueError, match="libpq environment"):
        benchmark.validate_target({
            "GUIYI_ISOLATED_MIGRATION_DATABASE_URL":
                "postgresql+psycopg://test:test@127.0.0.1:55433/guiyi_reference_isolated_test",
            name: "remote.example",
        })
