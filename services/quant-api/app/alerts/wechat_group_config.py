"""Strict private configuration for the single WeChat Alert group."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import stat
from typing import Any
import unicodedata


WECHAT_GROUP_CONFIG_VERSION = 1
WECHAT_GROUP_CHANNEL = "wechat-courier"
PRIMARY_ALERT_GROUP_ALIAS = "primary_alert_group"
_SCHEMA_KEYS = {"version", "channel", "group_alias", "target_chat"}


class WeChatGroupConfigError(RuntimeError):
    """Stable error that never contains a private path or group title."""


@dataclass(frozen=True, slots=True)
class WeChatGroupTarget:
    version: int
    channel: str
    group_alias: str
    target_chat: str


def load_wechat_group_target(path: Path) -> WeChatGroupTarget:
    """Load one immutable 0600 group target from an exact 0700 parent."""
    try:
        parent_metadata = path.parent.lstat()
        file_metadata = path.lstat()
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
            or not stat.S_ISREG(file_metadata.st_mode)
            or stat.S_IMODE(file_metadata.st_mode) != 0o600
        ):
            raise ValueError
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _parse_target(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise WeChatGroupConfigError("WECHAT_GROUP_CONFIG_INVALID") from None


def _parse_target(payload: Any) -> WeChatGroupTarget:
    if not isinstance(payload, dict) or set(payload) != _SCHEMA_KEYS:
        raise ValueError
    version = payload["version"]
    channel = payload["channel"]
    group_alias = payload["group_alias"]
    target_chat = payload["target_chat"]
    if type(version) is not int or version != WECHAT_GROUP_CONFIG_VERSION:
        raise ValueError
    if channel != WECHAT_GROUP_CHANNEL or group_alias != PRIMARY_ALERT_GROUP_ALIAS:
        raise ValueError
    if (
        not isinstance(target_chat, str)
        or not target_chat
        or target_chat.strip() != target_chat
        or any(unicodedata.category(character).startswith("C") for character in target_chat)
    ):
        raise ValueError
    return WeChatGroupTarget(version, channel, group_alias, target_chat)
