"""Continue an existing frozen Market recovery from a newer, independently verified release."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from app.runtime_bindings import BindingRegistry, ServiceBinding, verify_release
from app.runtime_cohort import _require_forward_application_release, require
from app.runtime_deployment import assert_no_unknown_deployment
from app.runtime_handover import _read
from app.runtime_identity import file_snapshot, read_command
from app.runtime_market_recovery import RecoveryHost, apply, inspect, peers
from app.version import APP_VERSION

# Runs in the candidate's isolated interpreter. All candidate dependencies, source
# pinning, contract fingerprints and plist rendering remain the published candidate's.
_NATIVE_CHECK = """
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from app import runtime_market_recovery as native
from app.runtime_bindings import _parse_bindings
root, tag, commit = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if Path(native.__file__).resolve().parents[3] != root:
    raise ValueError("MARKET_CANDIDATE_SOURCE_DRIFT")
old = _parse_bindings(sys.stdin.buffer.read(), inventory=True)
host = native.RecoveryHost()
targets, component, schema = host.targets(root, tag, commit, old)
print(json.dumps({"targets": {n: asdict(b) for n,b in targets.items()}, "component": component,
                  "schema": schema, "plists": {n: sha256(host._plist(b)).hexdigest() for n,b in targets.items()}}))
"""


def candidate_proof(root, tag, commit, old):
    verify_release(root, tag, commit)
    python = root / "services/quant-api/.venv/bin/python"
    result = subprocess.run(
        [str(python), "-I", "-B", "-c", _NATIVE_CHECK, str(root), tag, commit],
        input=json.dumps(asdict(old)).encode(),
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={
            "HOME": str(Path.home()),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "LC_ALL": "C",
        },
        timeout=90,
        check=False,
    )
    require(
        result.returncode == 0 and 0 < len(result.stdout) < 131072, "MARKET_NATIVE_CANDIDATE_CHECK_FAILED"
    )
    return json.loads(result.stdout)


class ReleasedController(RecoveryHost):
    def __init__(self, tag, commit):
        super().__init__()
        self.control_root = Path(__file__).resolve().parents[3]
        self.control_tag = tag
        self.control_commit = commit

    def verify_control(self):
        verify_release(self.control_root, self.control_tag, self.control_commit)
        require(
            self.control_tag == "v" + APP_VERSION
            and Path(sys.prefix).resolve() == (self.control_root / "services/quant-api/.venv").resolve()
            and not os.path.lexists(self.control_root / ".env"),
            "MARKET_CONTROL_RELEASE_INVALID",
        )

    def targets(self, root, tag, commit, previous):
        self.verify_control()
        require(
            root != self.control_root
            and not root.is_relative_to(self.control_root)
            and not self.control_root.is_relative_to(root),
            "MARKET_CONTROL_ROOT_INVALID",
        )
        read_command(
            [
                "/usr/bin/git",
                "-c",
                "core.fsmonitor=false",
                "merge-base",
                "--is-ancestor",
                commit,
                self.control_commit,
            ],
            root=self.control_root,
        )
        native = candidate_proof(root, tag, commit, previous)
        targets = {n: ServiceBinding(**b) for n, b in native["targets"].items()}
        _require_forward_application_release(self.control_tag, BindingRegistry(1, targets))
        require(
            native["plists"] == {n: sha256(self._plist(b)).hexdigest() for n, b in targets.items()},
            "MARKET_NATIVE_CANDIDATE_PLIST_DRIFT",
        )
        return targets, native["component"], native["schema"]


def verify_pending(host, plan):
    host.verify_control()
    authority, old, targets, attempt = inspect(host, plan)
    progress = _read(host.directory / "market-recovery.json") or {}
    require(
        progress.get("plan_sha256") == plan["plan_sha256"]
        and progress.get("phase")
        in {
            "parking",
            "cas_intent",
            "installing",
            "alert_intent",
            "starting",
            "stop_unknown",
            "start_failed",
        },
        "MARKET_RECOVERY_NO_PENDING_PLAN",
    )
    assert_no_unknown_deployment(market_recovery_sha256=plan["plan_sha256"])
    raw = file_snapshot(attempt / "previous-registry.json", private=True)[0]
    require(sha256(raw).hexdigest() == plan["old_sha256"], "MARKET_ORIGINAL_DRIFT")
    identity = targets["api"]
    root = Path(identity.root)
    require(
        host.targets(root, identity.tag, identity.commit, old)
        == (targets, plan["component"], plan["schema"]),
        "MARKET_CANDIDATE_DRIFT",
    )
    peers(host, old, root, plan)
    return {
        "authority": authority,
        "phase": progress["phase"],
        "plan_sha256": plan["plan_sha256"],
        "controller_tag": host.control_tag,
        "controller_commit": host.control_commit,
        "target_tag": identity.tag,
        "target_commit": identity.commit,
        "candidate_plists": "verified",
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("verify", "resume"))
    for key in ("controller-tag", "controller-commit"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        host = ReleasedController(args.controller_tag, args.controller_commit)
        plan = json.loads(file_snapshot(args.plan, private=True)[0])
        proof = verify_pending(host, plan)
        if args.operation == "resume":
            proof.update(apply(host, plan, resume=True))
        print(json.dumps(proof, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc)
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": reason
                    if re.fullmatch("[A-Z0-9_]+", reason)
                    else "MARKET_RECOVERY_CONTROL_UNAVAILABLE",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
