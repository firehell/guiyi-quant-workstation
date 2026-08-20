"""Secure Git-external configuration for the active Alert transport."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping


NOTIFICATION_CONFIG_SCHEMA_VERSION = 1
NOTIFICATION_CONFIG_ENV = "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"
_CONFIG_KEYS = {"schema_version", "transport", "transport_config"}
_TRANSPORT_CONFIG_KEYS = {"message_token", "htdy_topic"}
_MESSAGE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]{32}\Z")


class NotificationConfigError(RuntimeError):
    """Stable configuration error that never includes private values."""

    def __init__(self, code: str = "ALERT_NOTIFICATION_CONFIG_INVALID") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True, repr=False)
class NotificationConfig:
    schema_version: int
    transport: str
    transport_config: Mapping[str, object]

    def __repr__(self) -> str:
        return (
            "NotificationConfig("
            f"schema_version={self.schema_version!r}, "
            f"transport={self.transport!r}"
            ")"
        )


def load_notification_config(path: Path) -> NotificationConfig:
    """Load one private config without following links or inode replacement."""
    try:
        _validate_parent(path.parent)
        initial = path.lstat()
        _validate_file(initial)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            opened = os.fstat(stream.fileno())
            _validate_file(opened)
            if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError
            return _parse_config(json.load(stream))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise NotificationConfigError() from None


def validate_pushplus_transport_config(config: Mapping[str, object]) -> None:
    try:
        if set(config) != _TRANSPORT_CONFIG_KEYS:
            raise ValueError
        message_token = config["message_token"]
        htdy_topic = config["htdy_topic"]
        if (
            not isinstance(message_token, str)
            or _MESSAGE_TOKEN_PATTERN.fullmatch(message_token) is None
            or not _valid_private_identifier(htdy_topic)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise NotificationConfigError() from None


def _validate_parent(parent: Path) -> None:
    metadata = parent.lstat()
    if (
        not parent.is_absolute()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _validate_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _parse_config(payload: Any) -> NotificationConfig:
    if not isinstance(payload, dict) or set(payload) != _CONFIG_KEYS:
        raise ValueError
    schema_version = payload["schema_version"]
    transport = payload["transport"]
    raw_transport_config = payload["transport_config"]
    if (
        type(schema_version) is not int
        or schema_version != NOTIFICATION_CONFIG_SCHEMA_VERSION
        or transport != "pushplus"
        or not isinstance(raw_transport_config, dict)
        or not all(isinstance(key, str) for key in raw_transport_config)
    ):
        raise ValueError
    validate_pushplus_transport_config(raw_transport_config)
    return NotificationConfig(
        schema_version=schema_version,
        transport=transport,
        transport_config=MappingProxyType(dict(raw_transport_config)),
    )


def _valid_private_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value.strip() == value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )
