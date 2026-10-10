"""Exact per-service Runtime authority. No credentials or configuration are read."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any

SERVICES = frozenset({"api", "web", "live", "market-feed", "alert", "reference-worker",
                      "after-market", "weekly-audit", "late-provider-recovery", "log-rotate"})
CONTRACTS = frozenset({"db", "live", "input", "formula", "reference", "launcher"})


class RuntimeBindingError(ValueError):
    """Bounded error codes; never attach sensitive command output."""


@dataclass(frozen=True)
class ServiceBinding:
    service: str
    root: str
    tag: str
    commit: str
    generation: int
    enabled: bool
    contracts: dict[str, str]
    launchd_label: str | None = None

    @property
    def label(self) -> str:
        return self.launchd_label or f"com.guiyi.quant-{self.service}"

    def __post_init__(self) -> None:
        try:
            path = Path(self.root)
            if (self.service not in SERVICES or not path.is_absolute()
                    or (self.launchd_label is not None and (not isinstance(self.launchd_label, str)
                        or re.fullmatch(rf"com\.guiyi\.quant-{re.escape(self.service)}-candidate-[0-9a-f]{{32}}", self.launchd_label) is None))
                    or path != path.resolve(strict=True) or not path.is_dir()
                    or re.fullmatch(r"v\d+\.\d+\.\d+", self.tag) is None
                    or re.fullmatch(r"[0-9a-f]{40}", self.commit) is None
                    or type(self.generation) is not int or self.generation < 1
                    or type(self.enabled) is not bool or self.contracts.keys() != CONTRACTS
                    or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in self.contracts.values())):
                raise ValueError
        except (OSError, TypeError, ValueError):
            raise RuntimeBindingError("INVALID_SERVICE_BINDING") from None


@dataclass(frozen=True)
class BindingRegistry:
    schema_version: int
    services: dict[str, ServiceBinding]

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not int or self.schema_version != 1
                or not self.services or self.services.keys() - SERVICES
                or any(key != value.service for key, value in self.services.items())):
            raise RuntimeBindingError("INVALID_BINDING_REGISTRY")


def registry_path(home: Path | None = None) -> Path:
    return (Path.home() if home is None else home) / "Library/Application Support/GuiyiQuant/service-bindings.json"



def authorized_program_arguments(binding: ServiceBinding, home: Path) -> tuple[str, ...]:
    launcher = str(home / "Library/Application Support/GuiyiQuant/run-local-service.sh")
    if binding.launchd_label is not None:
        request = binding.launchd_label.rsplit("-candidate-", 1)[1]
        return ("/bin/bash", launcher, "handover-candidate", binding.service, request, str(binding.generation))
    service_argument = "weekly-audit-scheduled" if binding.service == "weekly-audit" else binding.service
    return ("/bin/bash", launcher, service_argument)

def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _read(path: Path) -> bytes | None:
    try:
        if path.parent.exists():
            parent_info = path.parent.lstat()
            if (path.parent != path.parent.resolve(strict=True)
                    or not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid()
                    or parent_info.st_mode & 0o022):
                raise RuntimeBindingError("INVALID_REGISTRY_DIRECTORY")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        # A dangling symlink is present and invalid, not a first installation.
        if os.path.lexists(path):
            raise RuntimeBindingError("INVALID_BINDING_REGISTRY") from None
        return None
    except OSError:
        raise RuntimeBindingError("INVALID_BINDING_REGISTRY") from None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid != os.getuid() or before.st_nlink != 1 or before.st_size > 1024 * 1024):
            raise ValueError
        content = os.read(fd, 1024 * 1024 + 1)
        after = os.stat(path, follow_symlinks=False)
        def identity(item):
            return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if (identity(before) != identity(os.fstat(fd)) or identity(before) != identity(after) or len(content) != before.st_size):
            raise ValueError
        return content
    except (OSError, ValueError):
        raise RuntimeBindingError("INVALID_BINDING_REGISTRY") from None
    finally:
        os.close(fd)


def read_bindings(*, home: Path | None = None) -> BindingRegistry | None:
    content = _read(registry_path(home))
    if content is None:
        return None
    try:
        payload = json.loads(content, object_pairs_hook=_pairs)
        if payload.keys() != {"schema_version", "services"}:
            raise ValueError
        return BindingRegistry(payload["schema_version"],
            {key: ServiceBinding(**value) for key, value in payload["services"].items()})
    except (KeyError, AttributeError, TypeError, ValueError):
        raise RuntimeBindingError("INVALID_BINDING_REGISTRY") from None


def bindings_sha256(*, home: Path | None = None) -> str | None:
    read_bindings(home=home)  # A malformed registry never becomes an accepted CAS preimage.
    content = _read(registry_path(home))
    return hashlib.sha256(content).hexdigest() if content is not None else None


def write_bindings(registry: BindingRegistry, *, home: Path | None = None,
                   expected_sha256: str | None) -> str:
    """Atomically replace one validated authority, serialized under a stable flock."""
    registry.__post_init__()
    for binding in registry.services.values():
        binding.__post_init__()
    path = registry_path(home)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_info = path.parent.lstat()
    if (path.parent != path.parent.resolve(strict=True) or not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.getuid() or parent_info.st_mode & 0o022):
        raise RuntimeBindingError("INVALID_REGISTRY_DIRECTORY")
    lock = os.open(path.parent / "service-bindings.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    temporary = None
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeBindingError("INVALID_REGISTRY_LOCK")
        fcntl.flock(lock, fcntl.LOCK_EX)
        if bindings_sha256(home=home) != expected_sha256:
            raise RuntimeBindingError("REGISTRY_DRIFT")
        content = json.dumps(asdict(registry), sort_keys=True, separators=(",", ":")).encode()
        fd, temporary = tempfile.mkstemp(prefix=".service-bindings-", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return hashlib.sha256(content).hexdigest()
    finally:
        if temporary is not None:
            os.unlink(temporary)
        os.close(lock)


def resolve_service_binding(service: str, *, home: Path | None = None) -> ServiceBinding | None:
    if service not in SERVICES:
        raise RuntimeBindingError("INVALID_SERVICE")
    registry = read_bindings(home=home)
    if registry is None:
        return None
    try:
        return registry.services[service]
    except KeyError:
        raise RuntimeBindingError("SERVICE_BINDING_MISSING") from None


def pinned_release_roots(*, home: Path | None = None) -> frozenset[Path]:
    registry = read_bindings(home=home)
    return frozenset() if registry is None else frozenset(Path(item.root) for item in registry.services.values())


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(["/usr/bin/git", "-c", "core.fsmonitor=false", *arguments],
                                cwd=root, capture_output=True, text=True, timeout=15, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise RuntimeBindingError("RELEASE_IDENTITY_INVALID") from None


def verify_release(root: Path, tag: str, commit: str) -> None:
    if (not root.is_absolute() or root != root.resolve(strict=True)
            or re.fullmatch(r"v\d+\.\d+\.\d+", tag) is None
            or re.fullmatch(r"[0-9a-f]{40}", commit) is None
            or _git(root, "rev-parse", "--show-toplevel") != str(root)
            or _git(root, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD"
            or _git(root, "rev-parse", "HEAD") != commit
            or _git(root, "cat-file", "-t", f"refs/tags/{tag}") != "tag"
            or _git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}") != commit
            or _git(root, "status", "--porcelain=v1", "--untracked-files=all")):
        raise RuntimeBindingError("RELEASE_IDENTITY_INVALID")


# Conservative file classification is frozen in this version. Unknown changes affect all services.
ALL = SERVICES
BUSINESS = frozenset({"api", "live", "market-feed", "alert", "reference-worker", "after-market", "weekly-audit", "late-provider-recovery"})


def _owners(path: str) -> frozenset[str]:
    if path.startswith("apps/") or path == "services/quant-api/app/version.py":
        return frozenset({"api", "web"})
    if path.startswith(("packages/quant-core/", "services/quant-api/app/reference_trading/", "services/quant-api/app/strategies/")):
        return frozenset({"api", "alert", "reference-worker"})
    if path.startswith(("services/quant-api/app/api/", "services/quant-api/app/routers/", "services/quant-api/app/services/")):
        return frozenset({"api"})
    if path.startswith("services/quant-api/app/market_data/"):
        return BUSINESS
    if path.startswith(("services/quant-api/tests/", "tests/", "docs/", "openspec/")) or path.endswith(".md"):
        return frozenset()
    return ALL


def _tracked(root: Path) -> dict[str, str]:
    return {line.split("\t", 1)[1]: line.split()[2] for line in _git(root, "ls-tree", "-r", "HEAD").splitlines()}


def _digest(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def contract_fingerprints(root: Path) -> dict[str, str]:
    files = _tracked(root)
    prefixes = {"db": ("services/quant-api/alembic/", "services/quant-api/app/db/", "services/quant-api/app/models/"),
        "live": ("services/quant-api/app/market_data/live",),
        "input": ("services/quant-api/app/market_data/rqdata_adapter",
                  "services/quant-api/app/market_data/market_feed.py",
                  "services/quant-api/app/market_data/observation_stream.py", "data/universe/"),
        "formula": ("packages/quant-core/", "services/quant-api/app/strategies/"),
        "reference": ("services/quant-api/app/reference_trading/",),
        "launcher": ("scripts/ops/macos/run-local-service.sh", "scripts/ops/macos/runtime-service-dispatch.sh", "services/quant-api/app/runtime_bindings.py", "services/quant-api/app/runtime_entry", "services/quant-api/app/runtime_handover.py", "services/quant-api/app/runtime_deployment.py", "services/quant-api/app/runtime_bootstrap.py", "services/quant-api/app/runtime_scheduled.py")}
    result = {}
    for name, paths in prefixes.items():
        selected = {key: value for key, value in files.items() if key.startswith(paths)}
        if not selected:
            raise RuntimeBindingError("CONTRACT_UNPROVEN")
        result[name] = _digest(selected)
    return result


def bootstrap_registry(bindings: list[ServiceBinding]) -> BindingRegistry:
    """Pure assembly of independently verified installed identities; never infer roots."""
    if len({binding.service for binding in bindings}) != len(bindings):
        raise RuntimeBindingError("DUPLICATE_SERVICE_BINDING")
    for binding in bindings:
        verify_release(Path(binding.root), binding.tag, binding.commit)
        if binding.contracts != contract_fingerprints(Path(binding.root)):
            raise RuntimeBindingError("CONTRACT_IDENTITY_DRIFT")
    return BindingRegistry(1, {binding.service: binding for binding in bindings})


def build_release_plan(registry: BindingRegistry, *, candidate_root: Path, tag: str,
                       commit: str, registry_sha256: str | None = None) -> dict[str, Any]:
    """Read-only plan. Equality of contract fingerprints is the only v1 compatibility proof."""
    verify_release(candidate_root, tag, commit)
    candidate_files = _tracked(candidate_root)
    candidate_contracts = contract_fingerprints(candidate_root)
    affected = set()
    fingerprints = {}
    reasons = []
    candidates = {}
    for name, old in registry.services.items():
        verify_release(Path(old.root), old.tag, old.commit)
        if old.contracts != contract_fingerprints(Path(old.root)):
            raise RuntimeBindingError("CONTRACT_IDENTITY_DRIFT")
        previous = _tracked(Path(old.root))
        changed = {key for key in previous.keys() | candidate_files.keys() if previous.get(key) != candidate_files.get(key)}
        if any(name in _owners(key) for key in changed):
            affected.add(name)
        fingerprints[name] = {"previous": _digest({key: value for key, value in previous.items() if name in _owners(key)}),
                              "candidate": _digest({key: value for key, value in candidate_files.items() if name in _owners(key)})}
        candidates[name] = asdict(ServiceBinding(name, str(candidate_root), tag, commit,
                                old.generation + 1, old.enabled, candidate_contracts))
    if affected & {"api", "web"}:
        affected.update({"api", "web"} & registry.services.keys())
    # Each sequential handover temporarily mixes old and new services, including
    # services scheduled later in this same plan. v1 requires proven equal contracts.
    for name, old in registry.services.items():
        if old.enabled:
            incompatible = sorted(key for key in CONTRACTS if old.contracts[key] != candidate_contracts[key])
            if incompatible:
                reasons.append({"service": name, "code": "MIXED_CONTRACT_INCOMPATIBLE", "contracts": incompatible})
    payload = {"schema_version": 1, "readonly": True, "registry_sha256": registry_sha256,
               "candidate": {"root": str(candidate_root), "tag": tag, "commit": commit},
               "previous_bindings": asdict(registry)["services"], "candidate_bindings": candidates,
               "affected_services": sorted(affected), "fingerprints": fingerprints,
               "blocked": reasons, "status": "blocked" if reasons else "ready"}
    verify_release(candidate_root, tag, commit)
    for previous_binding in registry.services.values():
        verify_release(Path(previous_binding.root), previous_binding.tag, previous_binding.commit)
    payload["plan_sha256"] = _digest(payload)
    return payload
