"""Private target configuration binding for closeout; never sources shell or logs settings."""

from datetime import UTC, datetime
from copy import deepcopy
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat

from redis import Redis
from sqlalchemy.engine import make_url

from app.db.url import normalize_database_url
from app.market_data.after_market import public_after_market_status
from app.market_data.after_market_closeout import (
    _directory,
    _read,
    verify_closeout_identity,
    verify_runtime_release_identity,
)
from app.market_data.captured_recovery_runtime import (
    _read_command,
    _read_launchd_service,
    _verify_heartbeat,
    _verify_loaded_service,
)
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.operational_universe import load_operational_products
from app.market_data.rqdata_adapter import (
    RQDATA_PROVIDER_SETTINGS,
    runtime_provider_settings,
)


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


def _redis_url(settings: dict[str, str]) -> str:
    value = settings["REDIS_URL"]
    if not value or value == "redis://127.0.0.1:6379/0":
        password = settings.get("REDIS_PASSWORD") or settings["POSTGRES_PASSWORD"]
        value = f"redis://:{password}@127.0.0.1:6379/0"
    return value


def _assert_dependency_endpoints(settings, *, root: Path, session, redis, products) -> Path:
    """Verify DB/Redis/Canonical/universe identities without constructing a provider."""
    if any(key.startswith("PG") for key in os.environ):
        raise ValueError
    expected_db = make_url(normalize_database_url(settings["DATABASE_URL"]))
    if session.get_bind().url != expected_db or expected_db.get_backend_name() != "postgresql":
        raise ValueError
    expected_redis = Redis.from_url(_redis_url(settings))
    try:
        # Redis creates these pool-local objects anew; they are not endpoint,
        # authentication, TLS, database, or connection-class configuration.
        local_objects = {"maint_notifications_pool_handler", "maint_notifications_config"}
        actual = {key: value for key, value in redis.connection_pool.connection_kwargs.items() if key not in local_objects}
        expected = {key: value for key, value in expected_redis.connection_pool.connection_kwargs.items() if key not in local_objects}
        if actual != expected or redis.connection_pool.connection_class != expected_redis.connection_pool.connection_class:
            raise ValueError
    finally:
        expected_redis.close()
    canonical = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    if not canonical.is_absolute() or canonical != canonical.resolve() or ".." in canonical.parts:
        raise ValueError
    if products != _products(root):
        raise ValueError
    return canonical


def assert_catalog_dependencies(settings, *, root: Path, catalog, session, redis, products) -> None:
    """Verify the provider-free current-day plan/apply dependency surface."""
    canonical = _assert_dependency_endpoints(
        settings, root=root, session=session, redis=redis, products=products
    )
    if catalog.session is not session or catalog.canonical_root != canonical:
        raise ValueError


def assert_dependencies(settings, *, root: Path, manager, session, redis, products) -> None:
    """Inspect actual constructed historical dependencies without provider calls."""
    canonical = _assert_dependency_endpoints(
        settings, root=root, session=session, redis=redis, products=products
    )
    if (manager.catalog.session is not session or manager.catalog.canonical_root != canonical
            or manager.store.root != canonical or manager.coverage.session is not session
            or manager.store.boundary_validator != manager.coverage.valid_boundaries):
        raise ValueError
    if (
        not hasattr(manager.provider, "matches_provider_settings")
        or not manager.provider.matches_provider_settings(settings)
    ):
        raise ValueError
    target = DatabaseCoverageSource(session, root / "data/universe/product_window_starts.csv",
        history_floor_path=root / "data/universe/active_history_floor.txt")
    if manager.coverage.starts != target.starts or manager.coverage.history_floor != target.history_floor:
        raise ValueError


def _products(root: Path) -> tuple[str, ...]:
    directory = root / "data/universe"
    return load_operational_products(directory / "operational_products.txt",
        active_path=directory / "active_products.txt", retired_path=directory / "retired_products.txt")


def _snapshot(path: Path, *, private: bool = False) -> tuple[bytes, tuple[int, ...]]:
    with _directory(path.parent) as directory:
        if private and stat.S_IMODE(os.fstat(directory).st_mode) != 0o700:
            raise ValueError
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or info.st_mode & 0o022 or info.st_size > 1024 * 1024
                    or private and stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError
            content = os.read(fd, 1024 * 1024 + 1)
            def identity(item):
                return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            after = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if len(content) != info.st_size or identity(info) != identity(os.fstat(fd)) or identity(info) != identity(after):
                raise ValueError
            return content, identity(after)
        finally:
            os.close(fd)


def _arguments(output: str) -> tuple[str, ...]:
    scopes: list[str] = []
    values: list[str] = []
    seen = False
    for raw in output.splitlines():
        line = raw.strip()
        if line.endswith((" = {", " => {")):
            name = line.rsplit(" ", 2)[0]
            scopes.append(name)
            if len(scopes) == 2 and name == "arguments":
                if seen:
                    raise ValueError
                seen = True
        elif line == "}":
            if not scopes:
                raise ValueError
            scopes.pop()
        elif len(scopes) == 2 and scopes[-1] == "arguments":
            values.append(line)
    if scopes or not seen:
        raise ValueError
    return tuple(values)


def _environments(output: str) -> tuple[dict[str, str], ...]:
    """Read only direct launchd environment scopes, never event descriptors."""
    names = {"environment", "inherited environment", "default environment"}
    scopes: list[tuple[str, str]] = []
    result: dict[str, dict[str, str]] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if line.endswith((" = {", " => {")):
            name, operator, _ = line.rsplit(" ", 2)
            if not scopes and operator != "=":
                raise ValueError
            if len(scopes) == 2 and scopes[-1][0] in names:
                raise ValueError
            if name in names:
                if len(scopes) != 1 or operator != "=" or name in result:
                    raise ValueError
                result[name] = {}
            scopes.append((name, operator))
        elif line == "}":
            if not scopes:
                raise ValueError
            scopes.pop()
        elif len(scopes) == 2 and scopes[-1][0] in names:
            match = re.fullmatch(r"([^\s]+) => (.*)", line)
            if match is None or match[1] in result[scopes[-1][0]]:
                raise ValueError
            result[scopes[-1][0]][match[1]] = match[2]
    if scopes or "environment" not in result:
        raise ValueError
    return tuple(result.values())


class RuntimeDataBinding:
    """Pins source identity in memory. No configuration or digest is publicly returned."""

    def __init__(self, root: Path, commit: str, status_sha256: str):
        if any(key.startswith("PG") for key in os.environ):
            raise ValueError
        self.root, self.commit = root, commit
        with _directory(root / ".run") as directory:
            status = _read(directory, "after-market-status.json")
        if hashlib.sha256(status).hexdigest() != status_sha256:
            raise ValueError
        parsed, started, interruption = self._validate_status(status)
        self._status = status
        self._status_sha256 = status_sha256
        self._status_payload = parsed
        self.last_interruption = interruption
        self.after_market_state = "stopped" if interruption is not None else "loaded"
        self._verify_runtime_identity()
        self.started_ns = int(started.timestamp() * 1_000_000_000)
        self.runtime_dir = Path.home() / "Library/Application Support/GuiyiQuant"
        self.agent_dir = Path.home() / "Library/LaunchAgents"
        self.config_path = self.runtime_dir / "project.env"
        self._sources = self._read_sources()
        self._processes = self._read_processes()
        self._validate_age()
        parsed_settings = literal_settings(
            self._sources[self.config_path][0], dependency_sources=_DEPENDENCY_SOURCE_SETTINGS,
            discarded_settings=_CLOSEOUT_IGNORED_SETTINGS | _RETIRED_INERT_SETTINGS,
        )
        if (parsed_settings.keys() - _DEPENDENCY_SOURCE_SETTINGS - _CLOSEOUT_IGNORED_SETTINGS
                - _RETIRED_INERT_SETTINGS):
            raise ValueError
        self.settings = {key: value for key, value in parsed_settings.items() if key in _DEPENDENCY_SETTINGS}
        required = {"DATABASE_URL", "REDIS_URL", "POSTGRES_PASSWORD", "GUIYI_CANONICAL_DATA_ROOT",
                    "GUIYI_LIVE_RECOVERY_ENABLED"}
        if (not required <= self.settings.keys() or not self.settings["POSTGRES_PASSWORD"]
                or self.settings["GUIYI_LIVE_RECOVERY_ENABLED"] != "1"):
            raise ValueError
        runtime_provider_settings(self.settings, required=True)
        self.products = _products(root)
        if interruption is not None and tuple(parsed["last_run"]["products"]) != self.products:
            raise ValueError

    @staticmethod
    def _validate_status(status: bytes):
        try:
            parsed = json.loads(status)
            if not isinstance(parsed, dict):
                raise ValueError
            current = parsed.get("current_run")
            if current is not None:
                if not isinstance(current, dict) or not isinstance(current.get("started_at"), str):
                    raise ValueError
                started = datetime.fromisoformat(current["started_at"])
                if started.utcoffset() is None:
                    raise ValueError
                return parsed, started, None
            if type(parsed.get("schema_version")) is not int or parsed["schema_version"] != 5:
                raise ValueError
            public = public_after_market_status(parsed)
            interruption = public.get("last_interruption")
            last_run = public.get("last_run")
            last_failure = public.get("last_failure")
            if (not isinstance(interruption, dict) or not isinstance(last_run, dict)
                    or last_run.get("status") != "interrupted"
                    or last_run.get("error_code") != "AFTER_MARKET_INTERRUPTED"
                    or not isinstance(last_failure, dict)
                    or last_failure.get("error_code") != "AFTER_MARKET_INTERRUPTED"
                    or last_run.get("trading_day") != interruption.get("trading_day")
                    or last_run.get("started_at") != interruption.get("started_at")
                    or last_run.get("finished_at") != interruption.get("closed_at")
                    or last_failure.get("trading_day") != interruption.get("trading_day")):
                raise ValueError
            started = datetime.fromisoformat(interruption["started_at"])
            if started.utcoffset() is None:
                raise ValueError
            return public, started, interruption
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError from None

    def _read_status(self) -> bytes:
        with _directory(self.root / ".run") as directory:
            return _read(directory, "after-market-status.json")

    def _verify_pinned_status(self) -> None:
        status = self._read_status()
        if status != self._status or hashlib.sha256(status).hexdigest() != self._status_sha256:
            raise ValueError

    def _verify_runtime_identity(self) -> None:
        if self.after_market_state == "stopped":
            verify_runtime_release_identity(self.root, self.commit)
        else:
            verify_closeout_identity(self.root, self.commit)

    def recheck_identity(self) -> None:
        """Recheck every pinned filesystem, process and status fact."""
        self._verify_runtime_identity()
        self._verify_pinned_status()
        if self._read_sources() != self._sources or self._read_processes() != self._processes:
            raise ValueError

    def rebind_terminal_status(self, status_sha256: str) -> None:
        """Explicitly replace a pinned running status with its exact schema-v5 terminal."""
        if re.fullmatch(r"[0-9a-f]{64}", status_sha256) is None:
            raise ValueError
        current = self._status_payload.get("current_run")
        if not isinstance(current, dict):
            raise ValueError
        self._verify_runtime_identity()
        if self._read_sources() != self._sources or self._read_processes() != self._processes:
            raise ValueError
        status = self._read_status()
        if hashlib.sha256(status).hexdigest() != status_sha256:
            raise ValueError
        parsed, _, interruption = self._validate_status(status)
        last_run = parsed["last_run"]
        if (interruption is None or last_run["started_at"] != current["started_at"]
                or current.get("scheduled_date", last_run["trading_day"]) != last_run["trading_day"]
                or current.get("products", last_run["products"]) != last_run["products"]
                or tuple(last_run["products"]) != self.products
                or current.get("attempt", last_run["attempts"]) != last_run["attempts"]):
            raise ValueError
        self._verify_runtime_identity()
        if (self._read_sources() != self._sources or self._read_processes() != self._processes
                or self._read_status() != status):
            raise ValueError
        self._status = status
        self._status_sha256 = status_sha256
        self._status_payload = parsed
        self.last_interruption = interruption

    def compatible_recovery_proof(
        self,
        *,
        candidate_root: Path,
        candidate_commit: str,
        expected_operational_products_sha256: str,
        _identity_reader: Callable[..., str] | None = None,
        _heartbeat_checker: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        """Render a bounded proof; publication and recovery execution stay external gates."""
        from app.market_data.captured_recovery_runtime import (
            _read_command as read_identity_command,
        )

        identity_reader = _identity_reader or read_identity_command
        heartbeat_checker = _heartbeat_checker or self.check_runtime_heartbeats

        if (
            re.fullmatch(r"[0-9a-f]{40}", candidate_commit) is None
            or re.fullmatch(r"[0-9a-f]{64}", expected_operational_products_sha256)
            is None
            or candidate_root != candidate_root.resolve(strict=True)
            or Path(__file__).resolve()
            != candidate_root
            / "services/quant-api/app/market_data/closeout_binding.py"
        ):
            raise ValueError
        heartbeat_checker()
        if (
            self._read_sources() != self._sources
            or self._read_processes() != self._processes
            or self._status_payload.get("schema_version") != 5
            or self._status_payload.get("current_run") is not None
            or not isinstance(self.last_interruption, dict)
        ):
            raise ValueError
        products_path = self.root / "data/universe/operational_products.txt"
        products_content = self._sources[products_path][0]
        if hashlib.sha256(products_content).hexdigest() != expected_operational_products_sha256:
            raise ValueError
        git = ["/usr/bin/git", "-c", "core.fsmonitor=false"]

        def candidate_identity() -> str:
            if (
                identity_reader(
                    [*git, "rev-parse", "--show-toplevel"], root=candidate_root
                )
                != str(candidate_root)
                or identity_reader([*git, "rev-parse", "HEAD"], root=candidate_root)
                != candidate_commit
                or identity_reader(
                    [*git, "status", "--porcelain=v1", "--untracked-files=all"],
                    root=candidate_root,
                )
            ):
                raise ValueError
            tree = identity_reader(
                [*git, "rev-parse", "HEAD^{tree}"], root=candidate_root
            )
            if re.fullmatch(r"[0-9a-f]{40}", tree) is None:
                raise ValueError
            return tree

        candidate_tree = candidate_identity()
        heartbeat_checker()
        if (
            self._read_sources() != self._sources
            or self._read_processes() != self._processes
            or candidate_identity() != candidate_tree
        ):
            raise ValueError
        return {
            "schema_version": 1,
            "command": "data.compatible-recovery-proof",
            "status": "passed",
            "readonly": True,
            "candidate": {
                "root": str(candidate_root),
                "commit": candidate_commit,
                "tree": candidate_tree,
            },
            "source_runtime": {"root": str(self.root), "commit": self.commit},
            "status_schema_version": 5,
            "status_sha256": self._status_sha256,
            "operational_products_sha256": expected_operational_products_sha256,
            "operational_products_count": len(self.products),
            "last_interruption": deepcopy(self.last_interruption),
            "configuration_identity": {
                "database": "retained",
                "redis": "retained",
                "canonical": "retained",
                "rqdata": "retained",
            },
            "required_services": ["api", "web", "live", "alert", "after-market"],
            "provider_requests": 0,
            "database_writes": 0,
            "canonical_writes": 0,
            "runtime_mutations": 0,
            "recovery_ready": False,
            "recovery_blockers": [
                "PUBLISHED_EXACT_RECOVERY_TAG_REQUIRED",
                "IMMUTABLE_RECOVERY_ROOT_REQUIRED",
                "SEPARATE_RECOVERY_EXECUTION_INTENT_REQUIRED",
            ],
        }

    def _check_heartbeats(self, redis, store, now: Callable[[], datetime]) -> None:
        observed = now()
        _verify_heartbeat(
            store.heartbeat(), now=observed, root=self.root, commit=self.commit
        )
        raw = redis.get("alert:heartbeat")
        _verify_heartbeat(
            json.loads(raw) if raw is not None else None,
            now=observed,
            root=self.root,
            commit=self.commit,
        )

    def check_runtime_heartbeats(self) -> None:
        """Verify stopped-terminal service identity and both fresh Runtime heartbeats."""
        from app.market_data.live_market import RedisClient, RedisLiveStore
        from app.market_data.session_clock import SHANGHAI
        from typing import cast

        self.recheck_identity()
        redis = Redis.from_url(_redis_url(self.settings))
        try:
            store = RedisLiveStore(cast(RedisClient, redis))
            self._check_heartbeats(redis, store, lambda: datetime.now(SHANGHAI))
            self.recheck_identity()
        finally:
            redis.close()

    def _read_sources(self):
        # Target Python imports load dotenv without override. Even explicit main
        # URLs cannot stop it adding PGOPTIONS or other unsupported parameters.
        # Do not inspect secrets or silently support a second configuration source.
        if os.path.lexists(self.root / ".env"):
            raise ValueError
        paths = [self.config_path, self.runtime_dir / "run-local-service.sh",
            self.root / "scripts/ops/macos/run-local-service.sh"]
        paths += [self.root / "data/universe" / name for name in (
            "operational_products.txt", "active_products.txt", "retired_products.txt",
            "product_window_starts.csv", "active_history_floor.txt")]
        paths += [self.agent_dir / f"com.guiyi.quant-{name}.plist"
                  for name in ("api", "web", "live", "alert", "after-market")]
        result = {path: _snapshot(path, private=path == self.config_path) for path in paths}
        with _directory(self.root) as directory:
            info = os.fstat(directory)
            # Detect removal of a former dotenv after the old process started.
            result[self.root] = (b"", (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
        if result[paths[1]][0] != result[paths[2]][0]:
            raise ValueError
        return result

    def _read_processes(self):
        result = {}
        allowed = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "LC_CTYPE",
                   "XPC_SERVICE_NAME", "XPC_FLAGS", "OSLogRateLimit", "MallocSpaceEfficient",
                   "__CF_USER_TEXT_ENCODING", "SSH_AUTH_SOCK", "GUIYI_PROJECT_ROOT", "GUIYI_RUNTIME_COMMIT"}
        def validate_environment(values, service):
            supported = allowed | ({"GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"} if service in {"api", "alert"} else set())
            if values.keys() - supported or values.get("HOME", str(Path.home())) != str(Path.home()):
                raise ValueError
            notification = values.get("GUIYI_ALERT_NOTIFICATION_CONFIG_PATH")
            if notification is not None and (not isinstance(notification, str) or not Path(notification).is_absolute()
                    or ".." in Path(notification).parts or any(c in notification for c in "\n\r\t")):
                raise ValueError
        for name in ("api", "web", "live", "alert", "after-market"):
            label = f"com.guiyi.quant-{name}"
            arguments = ("/bin/bash", str(self.runtime_dir / "run-local-service.sh"), name)
            working_directory = Path.home() if name in {"api", "web"} else self.root
            path = self.agent_dir / f"{label}.plist"
            payload = plistlib.loads(self._sources[path][0])
            if not isinstance(payload, dict) or payload.get("Label") != label:
                raise ValueError
            installed_environment = payload.get("EnvironmentVariables", {})
            validate_environment(installed_environment, name)
            if (tuple(payload.get("ProgramArguments", ())) != arguments
                    or payload.get("WorkingDirectory") != str(working_directory)
                    or installed_environment.get("GUIYI_PROJECT_ROOT") != str(self.root)
                    or installed_environment.get("GUIYI_RUNTIME_COMMIT") != self.commit):
                raise ValueError
            output = _read_launchd_service(label, root=self.root)
            if name == "after-market" and self.after_market_state == "stopped":
                if output is not None:
                    raise ValueError
                continue
            if output is None:
                raise ValueError
            environments = _environments(output)
            for environment in environments:
                validate_environment(environment, name)
            if _arguments(output) != arguments:
                raise ValueError
            fields = _verify_loaded_service(output, root=self.root, commit=self.commit,
                allow_idle=name == "after-market", require_idle=name == "after-market",
                working_directory=working_directory)
            matching_environments = [environment for environment in environments
                if environment.get("GUIYI_PROJECT_ROOT") == str(self.root)
                and environment.get("GUIYI_RUNTIME_COMMIT") == self.commit]
            behavior_keys = {"PATH", "GUIYI_PROJECT_ROOT", "GUIYI_RUNTIME_COMMIT",
                             "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"}
            if (len(matching_environments) != 1
                    or {key: value for key, value in matching_environments[0].items()
                        if key in behavior_keys}
                    != {key: value for key, value in installed_environment.items()
                        if key in behavior_keys}
                    or any(matching_environments[0].get(key) != value
                           for key, value in installed_environment.items())):
                raise ValueError
            if name != "after-market":
                pid = fields["pid"]
                start = _read_command(["/usr/bin/env", "TZ=UTC", "/bin/ps", "-p", pid, "-o", "lstart="], root=self.root)
                parsed = datetime.strptime(start, "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC)
                result[name] = (pid, int(parsed.timestamp() * 1_000_000_000))
        return result

    def _validate_age(self):
        changed_at = {path: max(metadata[3:]) for path, (_, metadata) in self._sources.items()}
        # Every source must precede the interrupted run. The staged installer may
        # recopy only its shared launcher and individual plists after an earlier
        # service started; their exact bytes/loaded definitions are checked above.
        if any(timestamp >= self.started_ns for timestamp in changed_at.values()):
            raise ValueError
        install_artifacts = {self.runtime_dir / "run-local-service.sh"}
        install_artifacts.update(
            self.agent_dir / f"com.guiyi.quant-{name}.plist"
            for name in ("api", "web", "live", "alert", "after-market")
        )
        consumer_started = min(item[1] for item in self._processes.values())
        if any(timestamp >= consumer_started for path, timestamp in changed_at.items()
               if path not in install_artifacts):
            raise ValueError

    def check(self, manager, session, redis, store, now) -> None:
        self._verify_runtime_identity()
        self._verify_pinned_status()
        if self._read_sources() != self._sources or self._read_processes() != self._processes:
            raise ValueError
        assert_dependencies(self.settings, root=self.root, manager=manager, session=session,
                            redis=redis, products=self.products)
        self._check_heartbeats(redis, store, now)
        self._verify_pinned_status()

    def check_catalog(self, catalog, session, redis, store, now) -> None:
        """Recheck Runtime, heartbeats, and provider-free Catalog dependencies."""
        self._verify_runtime_identity()
        self._verify_pinned_status()
        if self._read_sources() != self._sources or self._read_processes() != self._processes:
            raise ValueError
        assert_catalog_dependencies(
            self.settings,
            root=self.root,
            catalog=catalog,
            session=session,
            redis=redis,
            products=self.products,
        )
        self._check_heartbeats(redis, store, now)
        self._verify_pinned_status()
