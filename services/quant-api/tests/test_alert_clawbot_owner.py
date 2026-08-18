from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.alerts.clawbot_owner import (
    CLAWBOT_CHANNEL,
    CLAWBOT_OWNER_ALIAS,
    CLAWBOT_OWNER_VERSION,
    ClawbotOwner,
    ClawbotOwnerError,
    load_clawbot_owner,
    write_clawbot_owner_atomic,
)


ACCOUNT_ID = "fixture-account"
TARGET_USER_ID = "fixture-owner@im.wechat"


def _private_path(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    return parent / "alert-clawbot-owner.json"


def _payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "version": 1,
        "channel": "openclaw-weixin",
        "owner_alias": "owner",
        "account_id": ACCOUNT_ID,
        "target_user_id": TARGET_USER_ID,
    }
    value.update(overrides)
    return value


def _write(path: Path, payload: object, *, mode: int = 0o600) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


def test_loads_one_immutable_owner(tmp_path: Path) -> None:
    path = _write(_private_path(tmp_path), _payload())

    owner = load_clawbot_owner(path)

    assert owner == ClawbotOwner(1, "openclaw-weixin", "owner", ACCOUNT_ID, TARGET_USER_ID)
    assert CLAWBOT_OWNER_VERSION == 1
    assert CLAWBOT_CHANNEL == "openclaw-weixin"
    assert CLAWBOT_OWNER_ALIAS == "owner"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"version": 1},
        _payload(extra=True),
        _payload(version=True),
        _payload(version=2),
        _payload(channel="other"),
        _payload(owner_alias="other"),
        _payload(account_id=""),
        _payload(account_id=" fixture"),
        _payload(account_id="fixture\x00"),
        _payload(target_user_id=""),
        _payload(target_user_id="fixture-owner"),
        _payload(target_user_id=" fixture-owner@im.wechat"),
        _payload(target_user_id="fixture\nowner@im.wechat"),
    ],
)
def test_invalid_schema_fails_closed_without_private_values(tmp_path: Path, payload: object) -> None:
    path = _private_path(tmp_path)
    if payload is None:
        path.write_text("not-json", encoding="utf-8")
        path.chmod(0o600)
    else:
        _write(path, payload)

    with pytest.raises(ClawbotOwnerError) as captured:
        load_clawbot_owner(path)

    assert str(captured.value) == "CLAWBOT_OWNER_INVALID"
    assert ACCOUNT_ID not in str(captured.value)
    assert TARGET_USER_ID not in str(captured.value)
    assert str(path) not in str(captured.value)


@pytest.mark.parametrize("problem", ["missing", "symlink", "directory", "fifo"])
def test_rejects_non_regular_or_missing_owner_file(tmp_path: Path, problem: str) -> None:
    path = _private_path(tmp_path)
    if problem == "symlink":
        real = _write(path.parent / "real.json", _payload())
        path.symlink_to(real)
    elif problem == "directory":
        path.mkdir(mode=0o700)
    elif problem == "fifo":
        os.mkfifo(path, mode=0o600)

    with pytest.raises(ClawbotOwnerError, match="^CLAWBOT_OWNER_INVALID$"):
        load_clawbot_owner(path)


@pytest.mark.parametrize("problem", ["parent_mode", "file_mode", "parent_uid", "file_uid"])
def test_requires_exact_private_modes_and_current_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    path = _write(_private_path(tmp_path), _payload())
    if problem == "parent_mode":
        path.parent.chmod(0o755)
    elif problem == "file_mode":
        path.chmod(0o640)
    else:
        selected = path.parent if problem == "parent_uid" else path
        original_lstat = Path.lstat

        def wrong_owner(candidate: Path):
            metadata = original_lstat(candidate)
            if candidate == selected:
                return SimpleNamespace(st_mode=metadata.st_mode, st_uid=os.getuid() + 1)
            return metadata

        monkeypatch.setattr(Path, "lstat", wrong_owner)

    with pytest.raises(ClawbotOwnerError, match="^CLAWBOT_OWNER_INVALID$"):
        load_clawbot_owner(path)


def test_atomic_writer_creates_0600_owner_and_round_trips(tmp_path: Path) -> None:
    path = _private_path(tmp_path)

    write_clawbot_owner_atomic(path, account_id=ACCOUNT_ID, target_user_id=TARGET_USER_ID)

    assert path.stat().st_mode & 0o777 == 0o600
    assert load_clawbot_owner(path) == ClawbotOwner(
        1, "openclaw-weixin", "owner", ACCOUNT_ID, TARGET_USER_ID
    )
    assert list(path.parent.glob(f".{path.name}.*")) == []


@pytest.mark.parametrize(
    ("account_id", "target_user_id"),
    [("", TARGET_USER_ID), (ACCOUNT_ID, "fixture-owner"), ("secret\nvalue", TARGET_USER_ID)],
)
def test_atomic_writer_rejects_invalid_ids_without_artifacts(
    tmp_path: Path, account_id: str, target_user_id: str
) -> None:
    path = _private_path(tmp_path)

    with pytest.raises(ClawbotOwnerError, match="^CLAWBOT_OWNER_INVALID$"):
        write_clawbot_owner_atomic(path, account_id=account_id, target_user_id=target_user_id)

    assert not path.exists()
    assert list(path.parent.iterdir()) == []


def test_atomic_writer_requires_private_current_uid_parent(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    path.parent.chmod(0o755)

    with pytest.raises(ClawbotOwnerError, match="^CLAWBOT_OWNER_INVALID$"):
        write_clawbot_owner_atomic(path, account_id=ACCOUNT_ID, target_user_id=TARGET_USER_ID)

    assert not path.exists()
