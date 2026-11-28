"""Private configuration of the supervised workstation API and its Plus child."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path

from app.core.env import PROJECT_ROOT
from app.runtime_bindings import _pairs, resolve_service_binding
from app.runtime_handover import _write, deployment_lock, runtime_directory
from app.runtime_identity import file_snapshot


PLUS_PATHS = frozenset({
    "GUIYI_BACKTEST_PLUS_PYTHON", "GUIYI_BACKTEST_PLUS_BUNDLE", "GUIYI_BACKTEST_PLUS_COST_PROFILE",
})
PLUS = PLUS_PATHS | {"RQSDK_LICENSE"}
READER = "GUIYI_SIMULATION_READER_DSN"
PROFILE = "workstation-api.json"


def profile(path):
    """Only a current-user 0600 file under a real private directory is accepted."""
    try:
        raw = file_snapshot(path, private=True, limit=65536)[0]
        values = json.loads(raw, object_pairs_hook=_pairs)
        if (not isinstance(values, dict) or not values or values.keys() - (PLUS | {READER})
                or values.keys() & PLUS and not PLUS <= values.keys()
                or any(not isinstance(v, str) or not v.strip() or any(ord(c) < 32 for c in v)
                       for v in values.values())
                or any(not Path(values[k]).is_absolute() or ".." in Path(values[k]).parts
                       for k in values.keys() & PLUS_PATHS)):
            raise ValueError
        return values, hashlib.sha256(raw).hexdigest()
    except (ValueError, OSError, RecursionError):
        raise ValueError("WORKSTATION_API_PROFILE_INVALID") from None


def configured_environment():
    if os.environ.get("GUIYI_RUNTIME_HANDOVER_ENABLED") != "1":
        return {}
    path = runtime_directory() / PROFILE
    if not os.path.lexists(path):
        return {}
    binding = resolve_service_binding("api")
    if (not binding or not binding.enabled or binding.root != str(PROJECT_ROOT)
            or any(os.environ.get(k) != v for k, v in {
                "GUIYI_PROJECT_ROOT": binding.root, "GUIYI_RUNTIME_COMMIT": binding.commit,
                "GUIYI_RUNTIME_TAG": binding.tag, "GUIYI_RUNTIME_GENERATION": str(binding.generation),
            }.items())):
        raise ValueError("WORKSTATION_API_PROFILE_OWNER_MISMATCH")
    values, _ = profile(path)
    if any(k in os.environ and os.environ[k] != v for k, v in values.items()):
        raise ValueError("WORKSTATION_API_PROFILE_ENV_CONFLICT")
    return values


@asynccontextmanager
async def api_lifespan(app):
    from app.api.backtest_center import workstation_lifespan

    values = configured_environment()
    added = values.keys() - os.environ.keys()
    try:
        os.environ.update(values)
        async with workstation_lifespan(app):
            yield
    finally:
        for name in added:
            os.environ.pop(name, None)


def install(source, directory):
    incoming, _ = profile(source)
    target = directory / PROFILE
    with deployment_lock(runtime_dir=directory):
        existing = profile(target)[0] if os.path.lexists(target) else {}
        if any(existing[k] != incoming[k] for k in existing.keys() & incoming.keys()):
            raise ValueError("WORKSTATION_API_PROFILE_CONFLICT")
        desired = {**existing, **incoming}
        encoded = json.dumps(desired, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > 65536:
            raise ValueError("WORKSTATION_API_PROFILE_INVALID")
        if desired != existing:
            _write(target, desired)
        installed, checksum = profile(target)
        if installed != desired:
            raise ValueError("WORKSTATION_API_PROFILE_DRIFT")
        return checksum


def main(argv=None):
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="operation", required=True)
    modes.add_parser("install").add_argument("--source", type=Path, required=True)
    modes.add_parser("read")
    args = parser.parse_args(argv)
    try:
        directory = runtime_directory()
        if args.operation == "install":
            install(args.source, directory)
        values, checksum = profile(directory / PROFILE)
        print(json.dumps({"sha256": checksum, "backtest": PLUS <= values.keys(), "simulation_reader": READER in values}))
    except (ValueError, OSError, RuntimeError):
        print('{"status":"blocked","code":"WORKSTATION_API_PROFILE_UNAVAILABLE_OR_CONFLICT"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
