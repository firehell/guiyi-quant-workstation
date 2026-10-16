"""Strict private Runtime configuration readers shared by tools and recovery."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from app.market_data.rqdata_adapter import RQDATA_PROVIDER_SETTINGS

class PrivateSettingsError(ValueError):
    """Never include file contents or credentials in public failures."""
    def __init__(self, code: str = "PROJECT_ENV_UNSAFE") -> None:
        self.code = code
        super().__init__(code)

_DEPENDENCY_SETTINGS = {
    "DATABASE_URL", "POSTGRES_PASSWORD", "REDIS_URL", "REDIS_PASSWORD",
    "GUIYI_CANONICAL_DATA_ROOT", "GUIYI_LIVE_RECOVERY_ENABLED",
} | RQDATA_PROVIDER_SETTINGS

_DEPENDENCY_SOURCE_SETTINGS = _DEPENDENCY_SETTINGS | {
    "POSTGRES_DB", "POSTGRES_PORT", "POSTGRES_USER", "REDIS_PORT",
}


_CLOSEOUT_IGNORED_SETTINGS = {
    "CORS_ORIGINS", "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH", "GUIYI_MARKET_HOME_PROJECTION_ENABLED",
    "VITE_API_BASE_URL",
    "VITE_MARKET_WS_URL", "VITE_PROXY_API_TARGET", "VITE_PROXY_WS_TARGET",
}

_RETIRED_INERT_SETTINGS = {
    "APP_ENV", "APP_PORT", "APP_SECRET_KEY", "BACKTEST_DATA_PATH", "BACKTEST_MAX_WORKERS",
    "BACKTEST_RESULT_PATH", "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
    "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH", "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET",
    "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED", "GUIYI_DATA_CORE_V2_EOD_ENABLED",
    "GUIYI_DATA_CORE_V2_LIVE_DECISION_ENABLED",
    "GUIYI_DATA_CORE_V2_RETENTION_SCHEDULER_ENABLED", "GUIYI_DATA_CORE_V2_REVIEW_ENABLED",
    "GUIYI_DATA_SOURCE_FALLBACKS", "GUIYI_DATA_SOURCE_PRIMARY", "GUIYI_HTDY_S610_ACTIVATION_RECEIPT",
    "GUIYI_HTDY_S610_APPROVAL_C2_HASH", "GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT",
    "GUIYI_HTDY_S610_APPROVAL_C2_SIGNATURE", "GUIYI_HTDY_S610_APPROVAL_C_BUNDLE",
    "GUIYI_HTDY_S610_APPROVAL_C_HASH", "GUIYI_HTDY_S610_APPROVAL_C_RECEIPT",
    "GUIYI_HTDY_S610_APPROVAL_C_SIGNATURE", "GUIYI_HTDY_S610_APPROVED_SIGNERS",
    "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED", "GUIYI_HTDY_S610_OUTPUT_DIR",
    "GUIYI_HTDY_S610_PHASE", "GUIYI_HTDY_S610_REQUIRED", "GUIYI_LIVE_RUNTIME_ENABLED",
    "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH", "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET",
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
    "GUIYI_SUBING_OBSERVATION_ROOT", "GUIYI_WECHAT_AUTOSEND_ENABLED", "LOG_FILE", "LOG_LEVEL",
    "QYWX_WEBHOOK_URL", "RISK_MAX_DAILY_LOSS", "RISK_MAX_DRAWDOWN", "RISK_MAX_POSITION_RATIO",
    "VITE_WS_URL",
}


def literal_settings(
        content: bytes, *, dependency_sources: set[str] | None = None,
        discarded_settings: set[str] | None = None) -> dict[str, str]:
    """A deliberately narrow subset of launcher assignments; unsupported shell fails closed."""
    values: dict[str, str] = {}
    seen: set[str] = set()
    for line in content.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export )?([A-Z][A-Z0-9_]*)=(.*)", line)
        if match is None or match[1] in seen:
            raise ValueError
        name = match[1]
        seen.add(name)
        if discarded_settings is not None and name in discarded_settings:
            continue
        value = match[2]
        single = value.startswith("'")
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or not value.endswith(quote) or quote in value[1:-1]:
                raise ValueError
            value = value[1:-1]
        elif any(c.isspace() for c in value) or any(c in value for c in "'\""):
            raise ValueError
        if any(c in value for c in "`\\;|&<>\r\n()"):
            raise ValueError
        if not single:
            def expand(match):
                key = match[1] or match[2]
                if (key not in values or dependency_sources is not None
                        and name in dependency_sources and key not in dependency_sources):
                    raise ValueError
                return values[key]
            value = re.sub(r"\$\{([A-Z][A-Z0-9_]*)\}|\$([A-Z][A-Z0-9_]*)", expand, value)
            if "$" in value:
                raise ValueError
        values[name] = value
    return values

def runtime_dependency_settings(content: bytes) -> dict[str, str]:
    """Extract only the existing Runtime dependency settings from project.env."""
    parsed = literal_settings(
        content,
        dependency_sources=_DEPENDENCY_SOURCE_SETTINGS,
        discarded_settings=_CLOSEOUT_IGNORED_SETTINGS | _RETIRED_INERT_SETTINGS,
    )
    if parsed.keys() - _DEPENDENCY_SOURCE_SETTINGS:
        raise ValueError
    return {key: value for key, value in parsed.items() if key in _DEPENDENCY_SETTINGS}

def read_private_settings_content(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or info.st_mode & 0o077
                or info.st_size > 1024 * 1024
            ):
                raise OSError
            content = os.read(fd, 1024 * 1024 + 1)
            if len(content) != info.st_size:
                raise OSError
        finally:
            os.close(fd)
        return content
    except (OSError, UnicodeError) as exc:
        raise PrivateSettingsError("PROJECT_ENV_UNSAFE") from exc

def private_dependency_settings(
    path: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    content = read_private_settings_content(path)
    try:
        settings = runtime_dependency_settings(content)
        canonical = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
        if (
            "DATABASE_URL" not in settings
            or not canonical.is_absolute()
            or canonical != canonical.resolve()
            or ".." in canonical.parts
        ):
            raise ValueError
    except (OSError, KeyError, UnicodeError, ValueError) as exc:
        raise PrivateSettingsError("PROJECT_ENV_UNSAFE") from exc
    identity = {
        "config_sha256": hashlib.sha256(content).hexdigest(),
        "canonical_root_sha256": hashlib.sha256(
            str(canonical).encode("utf-8")
        ).hexdigest(),
    }
    return settings, identity

def load_private_readonly_settings(
    path: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load only DB/Canonical dependencies; never require provider credentials."""
    return private_dependency_settings(path)

def load_private_execution_settings(
    path: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load writer dependencies and require the existing provider configuration."""
    settings, identity = private_dependency_settings(path)
    try:
        from app.market_data.rqdata_adapter import runtime_provider_settings

        runtime_provider_settings(settings, required=True)
    except (KeyError, ValueError) as exc:
        raise PrivateSettingsError("PROJECT_ENV_UNSAFE") from exc
    return settings, identity
