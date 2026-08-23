from __future__ import annotations

from pathlib import Path

import pytest

from app.backtest.config import BacktestConfigError, BacktestSettings


REQUIRED_ENV = {
    "GUIYI_BACKTEST_PYTHON_EXECUTABLE": "/opt/rqalpha/bin/python",
    "GUIYI_BACKTEST_BUNDLE_PATH": "/data/rqalpha/bundle",
    "GUIYI_BACKTEST_RUNS_ROOT": "/data/guiyi-backtests/runs",
    "GUIYI_BACKTEST_CORS_ORIGINS": ("http://127.0.0.1:5173,http://localhost:5173"),
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)


def test_settings_load_exact_environment_names_and_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("GUIYI_BACKTEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("BACKTEST_TIMEOUT_SECONDS", "9")

    settings = BacktestSettings.from_env()

    assert settings.python_executable == Path("/opt/rqalpha/bin/python")
    assert settings.bundle_path == Path("/data/rqalpha/bundle")
    assert settings.runs_root == Path("/data/guiyi-backtests/runs")
    assert settings.timeout_seconds == 3600
    assert settings.cors_origins == (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GUIYI_BACKTEST_PYTHON_EXECUTABLE", "relative/python"),
        ("GUIYI_BACKTEST_BUNDLE_PATH", "relative/bundle"),
        ("GUIYI_BACKTEST_RUNS_ROOT", "relative/runs"),
    ],
)
def test_settings_reject_relative_paths(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(BacktestConfigError, match="^BACKTEST_CONFIG_INVALID$"):
        BacktestSettings.from_env()


@pytest.mark.parametrize("timeout", ["0", "-1", "1.5", "not-an-integer"])
def test_settings_reject_invalid_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GUIYI_BACKTEST_TIMEOUT_SECONDS", timeout)

    with pytest.raises(BacktestConfigError, match="^BACKTEST_CONFIG_INVALID$"):
        BacktestSettings.from_env()


@pytest.mark.parametrize(
    ("bundle", "runs"),
    [
        ("/data/shared", "/data/shared/runs"),
        ("/data/shared/bundle", "/data/shared"),
        ("/data/shared", "/data/shared"),
    ],
)
def test_settings_reject_bundle_and_runs_overlap(
    monkeypatch: pytest.MonkeyPatch,
    bundle: str,
    runs: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GUIYI_BACKTEST_BUNDLE_PATH", bundle)
    monkeypatch.setenv("GUIYI_BACKTEST_RUNS_ROOT", runs)

    with pytest.raises(BacktestConfigError, match="^BACKTEST_CONFIG_INVALID$"):
        BacktestSettings.from_env()


def test_settings_resolve_symlinks_before_overlap_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    alias = tmp_path / "bundle-alias"
    alias.symlink_to(bundle, target_is_directory=True)
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GUIYI_BACKTEST_BUNDLE_PATH", str(alias))
    monkeypatch.setenv("GUIYI_BACKTEST_RUNS_ROOT", str(bundle / "runs"))

    with pytest.raises(BacktestConfigError, match="^BACKTEST_CONFIG_INVALID$"):
        BacktestSettings.from_env()


@pytest.mark.parametrize(
    "origins",
    [
        "",
        "https://127.0.0.1:5173",
        "http://192.168.1.10:5173",
        "http://localhost:5173/path",
    ],
)
def test_settings_reject_non_loopback_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
    origins: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GUIYI_BACKTEST_CORS_ORIGINS", origins)

    with pytest.raises(BacktestConfigError, match="^BACKTEST_CONFIG_INVALID$"):
        BacktestSettings.from_env()


@pytest.mark.parametrize("origin", ["http://[::1", "http://[not-ipv6]:5173"])
def test_settings_malformed_cors_origins_fail_with_stable_error(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GUIYI_BACKTEST_CORS_ORIGINS", origin)

    with pytest.raises(BacktestConfigError, match="^BACKTEST_CONFIG_INVALID$"):
        BacktestSettings.from_env()
