"""Run the fixed adapter under the configured Plus interpreter."""

import json
from pathlib import Path
import platform
import sys
from time import monotonic, sleep


def main(scratch: Path, bundle: Path) -> None:
    api = Path(__file__).resolve().parents[2]
    source_core = api.parents[1] / "packages/quant-core"
    sys.path.insert(0, str(api))
    if source_core.exists():
        sys.path.insert(0, str(source_core))

    from app.backtest_center.codec import digest, encode
    from app.backtest_center.errors import BacktestError
    from app.backtest_center.provenance import code_digest

    def deny_process(event, _):
        if event in {"subprocess.Popen", "os.posix_spawn", "os.fork", "os.forkpty", "os.exec", "os.system"}:
            raise BacktestError("PLUS_NESTED_PROCESS_BLOCKED")

    # Python's cached processor lookup invokes the host's uname on macOS.
    platform.processor()
    sys.addaudithook(deny_process)
    request = json.loads((scratch / "request.json").read_text())
    snapshot = None

    def send(name, payload):
        staged = scratch / (name + ".tmp")
        staged.write_text(encode(payload))
        staged.rename(scratch / name)

    def admit(native):
        nonlocal snapshot
        if snapshot is not None:
            raise BacktestError("PLUS_ADMISSION_ALREADY_RECORDED")
        snapshot = {**native, **request["identity"], "execution_policy": request["execution_policy"],
                    "research_profile_id": request["research_profile_id"]}
        send("admission.json", snapshot)
        until = monotonic() + 30
        while not (scratch / "admission.ok").is_file():
            if monotonic() >= until:
                raise BacktestError("PLUS_ADMISSION_ACK_TIMEOUT")
            sleep(0.05)

    code = None
    try:
        if code_digest() != request["identity"]["code_sha256"]:
            raise BacktestError("BACKTEST_ENGINE_CODE_IDENTITY_MISMATCH")
        from app.backtest_center.native_plus import execute

        profile_path = Path(request["cost_profile"]) if request.get("cost_profile") else None
        result = execute(request["config"], request["run_id"], bundle, request["expected"], admit,
                         cost_profile=profile_path)
        if snapshot is None:
            raise BacktestError("PLUS_ADMISSION_NOT_CONFIRMED")
        if code_digest() != request["identity"]["code_sha256"]:
            raise BacktestError("BACKTEST_ENGINE_CODE_CHANGED")
        send("result.json", {"run_id": request["run_id"], "snapshot_sha256": digest(snapshot), "result": result})
    except BacktestError as exc:
        code = exc.code
    except ImportError:
        code = "PLUS_DEPENDENCIES_UNAVAILABLE"
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        code = "PLUS_RUN_FAILED"
    if code:
        send("result.json", {"error": code})
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
