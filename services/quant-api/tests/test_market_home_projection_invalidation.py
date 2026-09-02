from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.guiyi_cli import data_commands
from app.market_data.historical_data_manager import RefreshRequest, UpdateRequest
from app.market_data.market_home_overview import MarketHomeAuthorityIdentity
from app.market_data.market_home_projection import (
    MarketHomeProjectionError,
    MarketHomeProjectionStore,
    market_home_projection_path,
)


class _Manager:
    def __init__(self, canonical_root: Path) -> None:
        self.catalog = SimpleNamespace(canonical_root=canonical_root)
        self.calls: list[str] = []
        self.projection_path = market_home_projection_path(canonical_root)
        self.projection_exists_at_action: list[bool] = []

    def update(self, _request):
        self.projection_exists_at_action.append(self.projection_path.exists())
        self.calls.append("update")
        return "updated"

    def refresh(self, _request):
        self.projection_exists_at_action.append(self.projection_path.exists())
        self.calls.append("refresh")
        return "refreshed"


@pytest.mark.parametrize(
    ("command", "request", "expected"),
    [
        (
            "update",
            UpdateRequest(("jm",), None, None, apply=True),
            "updated",
        ),
        (
            "refresh",
            RefreshRequest("jm", date(2026, 9, 1), date(2026, 9, 2), apply=True),
            "refreshed",
        ),
    ],
)
def test_apply_data_command_invalidates_projection_before_manager_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    request: UpdateRequest | RefreshRequest,
    expected: str,
) -> None:
    canonical_root = tmp_path / "canonical"
    manager = _Manager(canonical_root)
    projection = manager.projection_path
    projection.parent.mkdir(parents=True)
    projection.write_text("old projection", encoding="utf-8")
    monkeypatch.setattr(data_commands, "build_request", lambda _args: request)
    args = SimpleNamespace(data_command=command)

    result = data_commands.run_data_command(args, manager)  # type: ignore[arg-type]

    assert result == expected
    assert manager.calls == [command]
    assert manager.projection_exists_at_action == [False]
    assert not projection.exists()


def test_dry_run_does_not_invalidate_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_root = tmp_path / "canonical"
    manager = _Manager(canonical_root)
    projection = manager.projection_path
    projection.parent.mkdir(parents=True)
    projection.write_text("old projection", encoding="utf-8")
    request = UpdateRequest(("jm",), None, None, apply=False)
    monkeypatch.setattr(data_commands, "build_request", lambda _args: request)
    args = SimpleNamespace(data_command="update")

    result = data_commands.run_data_command(args, manager)  # type: ignore[arg-type]

    assert result == "updated"
    assert manager.calls == ["update"]
    assert manager.projection_exists_at_action == [True]
    assert projection.read_text(encoding="utf-8") == "old projection"


def test_projection_store_rejects_symlink_parent_for_read_and_invalidation(
    tmp_path: Path,
) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    derived = canonical_root / ".derived"
    derived.symlink_to(outside, target_is_directory=True)
    store = MarketHomeProjectionStore(market_home_projection_path(canonical_root))
    identity = MarketHomeAuthorityIdentity(date(2026, 9, 2), "a" * 64)

    assert store.load(identity) is None
    with pytest.raises(
        MarketHomeProjectionError,
        match="MARKET_HOME_PROJECTION_INVALIDATION_FAILED",
    ):
        store.invalidate()
