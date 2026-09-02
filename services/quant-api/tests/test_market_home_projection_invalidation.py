from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.guiyi_cli import data_commands
from app.market_data.historical_data_manager import (
    AuditRequest,
    RefreshRequest,
    UpdateRequest,
)
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
        self.fail_after_invalidation = False

    def update(self, _request):
        self.projection_exists_at_action.append(self.projection_path.exists())
        self.calls.append("update")
        if self.fail_after_invalidation:
            raise RuntimeError("manager update failed")
        return "updated"

    def refresh(self, _request):
        self.projection_exists_at_action.append(self.projection_path.exists())
        self.calls.append("refresh")
        if self.fail_after_invalidation:
            raise RuntimeError("manager refresh failed")
        return "refreshed"

    def audit(self, _request):
        self.projection_exists_at_action.append(self.projection_path.exists())
        self.calls.append("audit")
        return "audited"


@pytest.mark.parametrize(
    ("command", "data_request", "expected"),
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
    data_request: UpdateRequest | RefreshRequest,
    expected: str,
) -> None:
    canonical_root = tmp_path / "canonical"
    manager = _Manager(canonical_root)
    projection = manager.projection_path
    projection.parent.mkdir(parents=True)
    projection.write_text("old projection", encoding="utf-8")
    monkeypatch.setattr(data_commands, "build_request", lambda _args: data_request)
    args = SimpleNamespace(data_command=command)

    result = data_commands.run_data_command(args, manager)  # type: ignore[arg-type]

    assert result == expected
    assert manager.calls == [command]
    assert manager.projection_exists_at_action == [False]
    assert not projection.exists()


@pytest.mark.parametrize(
    ("command", "data_request", "expected"),
    [
        ("update", UpdateRequest(("jm",), None, None, apply=False), "updated"),
        (
            "refresh",
            RefreshRequest("jm", date(2026, 9, 1), date(2026, 9, 2), apply=False),
            "refreshed",
        ),
        ("audit", AuditRequest(("jm",), through=None), "audited"),
    ],
)
def test_non_apply_data_commands_do_not_invalidate_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    data_request: AuditRequest | RefreshRequest | UpdateRequest,
    expected: str,
) -> None:
    canonical_root = tmp_path / "canonical"
    manager = _Manager(canonical_root)
    projection = manager.projection_path
    projection.parent.mkdir(parents=True)
    projection.write_text("old projection", encoding="utf-8")
    monkeypatch.setattr(data_commands, "build_request", lambda _args: data_request)
    args = SimpleNamespace(data_command=command)

    result = data_commands.run_data_command(args, manager)  # type: ignore[arg-type]

    assert result == expected
    assert manager.calls == [command]
    assert manager.projection_exists_at_action == [True]
    assert projection.read_text(encoding="utf-8") == "old projection"


def test_apply_failure_keeps_projection_invalidated(tmp_path: Path, monkeypatch) -> None:
    canonical_root = tmp_path / "canonical"
    manager = _Manager(canonical_root)
    manager.fail_after_invalidation = True
    projection = manager.projection_path
    projection.parent.mkdir(parents=True)
    projection.write_text("old projection", encoding="utf-8")
    monkeypatch.setattr(
        data_commands,
        "build_request",
        lambda _args: UpdateRequest(("jm",), None, None, apply=True),
    )

    with pytest.raises(RuntimeError, match="manager update failed"):
        data_commands.run_data_command(
            SimpleNamespace(data_command="update"), manager  # type: ignore[arg-type]
        )

    assert manager.projection_exists_at_action == [False]
    assert not projection.exists()


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
