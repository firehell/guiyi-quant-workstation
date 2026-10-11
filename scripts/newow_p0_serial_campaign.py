"""Serial dispatch only; stopping or failures never retry an unknown command.

Run after separately verified bootstrap. Completed dispatch receipts allow
resumption at the next not-yet-started command. Any dispatch without its durable
completion receipt blocks; preserved files require independent readback.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop-after-product")
    args = parser.parse_args()
    root = args.worktree.resolve()
    sys.path.insert(0, str(root))
    from scripts.newow_p0_candidate import _freeze, safe_path, stage_order, stage_key, write_once
    output = safe_path(args.output, root / "outputs")
    manifest_bytes = args.manifest.read_bytes()
    manifest, frozen_root = _freeze(args.manifest)
    if frozen_root != root:
        raise ValueError("P0_WORKTREE_MISMATCH")
    bootstrap = json.loads((output / "bootstrap-completed.json").read_text())
    if bootstrap["manifest_sha256"] != sha256(manifest_bytes).hexdigest():
        raise ValueError("P0_BOOTSTRAP_MANIFEST_CHANGED")
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{root}/services/quant-api:{root}/packages/quant-core:{root}"}
    if args.stop_after_product is not None and args.stop_after_product not in manifest["products"]:
        raise ValueError("P0_STOP_PRODUCT_OUTSIDE_UNIVERSE")
    completed_streams = 0
    order = stage_order(manifest["products"])
    for index, (product, frequency, strategy) in enumerate(order):
        key = stage_key(product, frequency, strategy, manifest["products"])
        stage = safe_path(output / "assets" / key, output)
        for command in ("plan", "build", "readback"):
            marker = stage / f"dispatch-{command}.json"
            completed_path = stage / f"dispatch-{command}-completed.json"
            artifact = stage / {"plan": "plan.json", "build": "native-report.json",
                "readback": "readback.json"}[command]
            if completed_path.exists():
                done = json.loads(completed_path.read_text())
                if (done["manifest_sha256"] != sha256(manifest_bytes).hexdigest()
                        or done["artifact_sha256"] != sha256(artifact.read_bytes()).hexdigest()):
                    raise ValueError("P0_COMPLETED_DISPATCH_DRIFT")
                continue
            if marker.exists() or artifact.exists() or (command == "build" and (stage / "attempt.json").exists()):
                raise ValueError("P0_PRIOR_DISPATCH_STOP_NO_RETRY:" + key + ":" + command)
            argv = [sys.executable, "-m", "scripts.newow_p0_candidate", command,
                "--manifest", str(args.manifest.resolve()), "--output", str(output),
                "--product", product, "--frequency", frequency, "--strategy", strategy]
            write_once(marker, {"state": "UNKNOWN", "retry_allowed": False,
                "manifest_sha256": sha256(manifest_bytes).hexdigest(), "argv": argv})
            log = safe_path(stage / f"dispatch-{command}.log", output)
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                process = subprocess.run(argv, cwd=root, env=environment,
                    stdout=handle, stderr=subprocess.STDOUT, check=False)
                handle.flush()
                os.fsync(handle.fileno())
            print(json.dumps({"key": key, "command": command, "exit_code": process.returncode}), flush=True)
            if process.returncode:
                return process.returncode
            write_once(completed_path, {"state": "COMPLETED", "retry_allowed": False,
                "manifest_sha256": sha256(manifest_bytes).hexdigest(),
                "artifact_sha256": sha256(artifact.read_bytes()).hexdigest()})
        completed_streams += 1
        if (args.stop_after_product == product and (index + 1 == len(order) or order[index + 1][0] != product)):
            print(json.dumps({"status": "PARTIAL_NATIVE_COMPLETION", "expected_streams": 720,
                "completed_streams": completed_streams, "stop_after_product": product,
                "api_numeric_visual_acceptance": "PENDING"}), flush=True)
            return 0
    print(json.dumps({"status": "LOCAL_NATIVE_COMPLETION_ARTIFACTS_ONLY",
        "expected_streams": 720, "api_numeric_visual_acceptance": "PENDING"}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        from scripts.newow_p0_candidate import safe_error_reason
        print(json.dumps({"status": "BLOCKED", "reason": safe_error_reason(exc)}), flush=True)
        raise SystemExit(1)
