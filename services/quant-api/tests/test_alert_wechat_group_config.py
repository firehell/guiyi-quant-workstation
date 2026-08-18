from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.alerts.wechat_group_config import (
    PRIMARY_ALERT_GROUP_ALIAS,
    WECHAT_GROUP_CHANNEL,
    WECHAT_GROUP_CONFIG_VERSION,
    WeChatGroupConfigError,
    WeChatGroupTarget,
    load_wechat_group_target,
)


FIXTURE_TARGET = "fixture-group-title"


def _private_path(tmp_path: Path) -> Path:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    return private / "alert-wechat-group.json"


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "channel": "wechat-courier",
        "group_alias": "primary_alert_group",
        "target_chat": FIXTURE_TARGET,
    }
    payload.update(overrides)
    return payload


def _write(path: Path, payload: object, *, mode: int = 0o600) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


def test_load_private_group_target(tmp_path: Path) -> None:
    path = _write(_private_path(tmp_path), _payload())

    result = load_wechat_group_target(path)

    assert result == WeChatGroupTarget(
        version=1,
        channel="wechat-courier",
        group_alias="primary_alert_group",
        target_chat=FIXTURE_TARGET,
    )
    assert WECHAT_GROUP_CONFIG_VERSION == 1
    assert WECHAT_GROUP_CHANNEL == "wechat-courier"
    assert PRIMARY_ALERT_GROUP_ALIAS == "primary_alert_group"


@pytest.mark.parametrize(
    ("case", "payload"),
    (
        ("malformed", None),
        ("missing_key", {"version": 1}),
        ("extra_key", _payload(extra=True)),
        ("wrong_version", _payload(version=2)),
        ("boolean_version", _payload(version=True)),
        ("wrong_channel", _payload(channel="other")),
        ("wrong_alias", _payload(group_alias="secondary_group")),
        ("blank_target", _payload(target_chat="   ")),
        ("leading_space", _payload(target_chat=f" {FIXTURE_TARGET}")),
        ("newline", _payload(target_chat=f"{FIXTURE_TARGET}\nother")),
        ("control", _payload(target_chat=f"{FIXTURE_TARGET}\x00")),
        ("non_string", _payload(target_chat=7)),
    ),
)
def test_invalid_schema_fails_closed_without_exposing_target(
    tmp_path: Path,
    case: str,
    payload: object,
) -> None:
    path = _private_path(tmp_path)
    if case == "malformed":
        path.write_text("not-json", encoding="utf-8")
        path.chmod(0o600)
    else:
        _write(path, payload)

    with pytest.raises(WeChatGroupConfigError) as captured:
        load_wechat_group_target(path)

    assert str(captured.value) == "WECHAT_GROUP_CONFIG_INVALID"
    assert FIXTURE_TARGET not in str(captured.value)


def test_missing_file_fails_closed_without_exposing_path(tmp_path: Path) -> None:
    path = _private_path(tmp_path)

    with pytest.raises(WeChatGroupConfigError) as captured:
        load_wechat_group_target(path)

    assert str(captured.value) == "WECHAT_GROUP_CONFIG_INVALID"
    assert str(path) not in str(captured.value)


def test_symlink_is_rejected_even_when_target_is_private(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    real = _write(private / "real.json", _payload())
    link = private / "alert-wechat-group.json"
    link.symlink_to(real)

    with pytest.raises(WeChatGroupConfigError, match="^WECHAT_GROUP_CONFIG_INVALID$"):
        load_wechat_group_target(link)


def test_directory_is_rejected(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    path.mkdir(mode=0o700)

    with pytest.raises(WeChatGroupConfigError, match="^WECHAT_GROUP_CONFIG_INVALID$"):
        load_wechat_group_target(path)


def test_non_regular_file_is_rejected(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    os.mkfifo(path, mode=0o600)

    with pytest.raises(WeChatGroupConfigError, match="^WECHAT_GROUP_CONFIG_INVALID$"):
        load_wechat_group_target(path)


def test_parent_mode_must_be_exactly_0700(tmp_path: Path) -> None:
    path = _write(_private_path(tmp_path), _payload())
    path.parent.chmod(0o755)

    with pytest.raises(WeChatGroupConfigError, match="^WECHAT_GROUP_CONFIG_INVALID$"):
        load_wechat_group_target(path)


def test_file_mode_must_be_exactly_0600(tmp_path: Path) -> None:
    path = _write(_private_path(tmp_path), _payload(), mode=0o640)

    with pytest.raises(WeChatGroupConfigError, match="^WECHAT_GROUP_CONFIG_INVALID$"):
        load_wechat_group_target(path)
