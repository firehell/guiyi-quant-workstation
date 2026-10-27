"""Dependency auth normalization must match the existing local service launcher."""

import importlib.util
from pathlib import Path
from urllib.parse import unquote, urlsplit


SPEC = importlib.util.spec_from_file_location(
    "continuous_runner",
    Path(__file__).parents[3] / "scripts/broker/simnow_supervisor.py",
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_documented_default_redis_url_uses_shared_password_without_mutating_source():
    source = {
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "POSTGRES_PASSWORD": "fixture @ value",
    }
    prepared = runner.dependency_environment(source)
    assert (
        unquote(urlsplit(prepared["REDIS_URL"]).password) == source["POSTGRES_PASSWORD"]
    )
    assert prepared["PGOPTIONS"] == "-c default_transaction_read_only=on"
    assert source["REDIS_URL"] == "redis://127.0.0.1:6379/0"


def test_explicit_redis_endpoint_and_auth_are_preserved():
    source = {
        "REDIS_URL": "redis://fixture:fixture@localhost:6380/4",
        "POSTGRES_PASSWORD": "other",
    }
    assert runner.dependency_environment(source)["REDIS_URL"] == source["REDIS_URL"]


def test_explicit_redis_password_wins_over_postgres_and_empty_url_is_normalized():
    source = {
        "REDIS_URL": "",
        "REDIS_PASSWORD": "redis fixture",
        "POSTGRES_PASSWORD": "pg fixture",
    }
    assert (
        unquote(urlsplit(runner.dependency_environment(source)["REDIS_URL"]).password)
        == source["REDIS_PASSWORD"]
    )
