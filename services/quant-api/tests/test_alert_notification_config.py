from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.alerts.notification_config import (
    NotificationConfigError,
    load_notification_config,
)


MESSAGE_TOKEN = "0123456789abcdef0123456789abcdef"
HTDY_TOPIC = "fixture-private-topic"


def _private_parent(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    return parent


def _payload(*, transport: str = "pushplus") -> dict[str, object]:
    return {
        "schema_version": 1,
        "transport": transport,
        "transport_config": {
            "message_token": MESSAGE_TOKEN,
            "htdy_topic": HTDY_TOPIC,
        },
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def test_loads_exact_pushplus_config_without_exposing_private_values(
    tmp_path: Path,
) -> None:
    path = _private_parent(tmp_path) / "notification.json"
    _write(path, _payload())

    config = load_notification_config(path)

    assert config.schema_version == 1
    assert config.transport == "pushplus"
    assert dict(config.transport_config) == {
        "message_token": MESSAGE_TOKEN,
        "htdy_topic": HTDY_TOPIC,
    }
    rendered = repr(config)
    assert MESSAGE_TOKEN not in rendered
    assert HTDY_TOPIC not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1},
        _payload(transport="wxpusher"),
        {
            **_payload(),
            "active_recipients": [{"alias": "owner", "target": "private"}],
        },
        {
            "schema_version": 1,
            "transport": "pushplus",
            "transport_config": {"message_token": MESSAGE_TOKEN},
        },
        {
            "schema_version": 1,
            "transport": "pushplus",
            "transport_config": {
                "message_token": "wrong",
                "htdy_topic": HTDY_TOPIC,
            },
        },
        {
            "schema_version": 1,
            "transport": "pushplus",
            "transport_config": {
                "message_token": MESSAGE_TOKEN,
                "htdy_topic": " bad ",
            },
        },
    ],
)
def test_rejects_invalid_config_without_leaking_values(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    path = _private_parent(tmp_path) / "notification.json"
    _write(path, payload)

    with pytest.raises(
        NotificationConfigError,
        match="^ALERT_NOTIFICATION_CONFIG_INVALID$",
    ) as captured:
        load_notification_config(path)

    assert MESSAGE_TOKEN not in str(captured.value)
    assert HTDY_TOPIC not in str(captured.value)
    assert str(path) not in str(captured.value)


@pytest.mark.parametrize("problem", ["parent_mode", "file_mode", "symlink", "inode_changed"])
def test_safe_config_loader_rejects_unsafe_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    problem: str,
) -> None:
    parent = _private_parent(tmp_path)
    path = parent / "notification.json"
    _write(path, _payload())
    if problem == "parent_mode":
        parent.chmod(0o755)
    elif problem == "file_mode":
        path.chmod(0o644)
    elif problem == "symlink":
        outside = tmp_path / "outside.json"
        _write(outside, _payload())
        path.unlink()
        path.symlink_to(outside)
    else:
        original_open = os.open

        def replacing_open(
            candidate: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: int,
        ) -> int:
            if Path(candidate) == path:
                replacement = path.with_name("replacement.json")
                _write(replacement, _payload())
                replacement.replace(path)
            return original_open(candidate, flags, *args)

        monkeypatch.setattr(os, "open", replacing_open)

    with pytest.raises(
        NotificationConfigError,
        match="^ALERT_NOTIFICATION_CONFIG_INVALID$",
    ):
        load_notification_config(path)
