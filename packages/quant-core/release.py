"""Build and verify a private, immutable Quant Core release candidate."""

from argparse import ArgumentParser
from hashlib import file_digest
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


PACKAGE = Path(__file__).resolve().parent


def _digest(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def _run(*command, cwd, env=None, capture=False):
    result = subprocess.run(command, cwd=cwd, env=env, check=True, text=True, capture_output=capture)
    return result.stdout if capture else None


def verified_wheel(record_path, *, expected_version, expected_sha256):
    """Resolve a release wheel only from an exact version and matching record digest."""
    record = json.loads(record_path.read_text())
    if record["package"]["name"] != "guiyi-quant-core" or record["package"]["version"] != expected_version:
        raise ValueError("QUANT_CORE_ARTIFACT_VERSION_MISMATCH")
    name, proof = next(
        (name, info) for name, info in record["artifacts"].items() if info["type"] == "wheel"
    )
    if Path(name).name != name or not name.endswith(".whl"):
        raise ValueError("QUANT_CORE_ARTIFACT_NAME_INVALID")
    wheel = record_path.parent / name
    if not wheel.is_file() or _digest(wheel) != expected_sha256 or proof["sha256"] != expected_sha256:
        raise ValueError("QUANT_CORE_ARTIFACT_HASH_MISMATCH")
    return wheel


def install(record, consumer_lock, python):
    pin = tomllib.loads(consumer_lock.read_text())
    package = json.loads(record.read_text())["package"]
    identity_fields = (
        "version", "compute_contract_version", "result_schema_version", "state_schema_version",
    )
    if pin["package"] != package["name"] or any(pin[key] != package[key] for key in identity_fields):
        raise ValueError("QUANT_CORE_CONSUMER_LOCK_INCOMPATIBLE")
    expected_version = pin["version"]
    wheel = verified_wheel(record, expected_version=expected_version, expected_sha256=pin["wheel_sha256"])
    if "sdist_sha256" in pin:
        artifacts = json.loads(record.read_text())["artifacts"]
        name = f"guiyi_quant_core-{expected_version}.tar.gz"
        proof = artifacts.get(name, {})
        source = record.parent / name
        if (proof != {"type": "sdist", "sha256": pin["sdist_sha256"]}
                or not source.is_file() or _digest(source) != pin["sdist_sha256"]):
            raise ValueError("QUANT_CORE_SDIST_HASH_MISMATCH")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    _run("uv", "pip", "install", "--no-deps", "--python", python, str(wheel), cwd=record.parent, env=env)
    _run(python, "-c", f"""
from importlib.metadata import distribution
from pathlib import Path
import sys
from guiyi_quant.compute.manifest import require_contract
dist = distribution("guiyi-quant-core")
assert dist.version == {expected_version!r}
assert Path(dist.locate_file("guiyi_quant/compute")).is_relative_to(sys.prefix)
require_contract(
    compute={pin["compute_contract_version"]!r},
    result={pin["result_schema_version"]!r},
    state={pin["state_schema_version"]!r},
)
""", cwd=record.parent, env=env)


def _vendor_dependency(wheel, package):
    lock = tomllib.loads((PACKAGE / "uv.lock").read_text())
    permitted = {
        row["url"].rsplit("/", 1)[-1]: row["hash"].removeprefix("sha256:")
        for item in lock["package"] if item["name"] == package
        for row in item["wheels"]
    }
    if wheel.name not in permitted or _digest(wheel) != permitted[wheel.name]:
        raise ValueError("QUANT_CORE_VENDOR_WHEEL_MISMATCH")


def build(output, python, *, vendor_wheel=None):
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    version = tomllib.loads((PACKAGE / "pyproject.toml").read_text())["project"]["version"]
    environment = output / "test-env"
    env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(environment), SOURCE_DATE_EPOCH="1704067200")
    # Run every installation and check outside the source tree.
    env.pop("PYTHONPATH", None)
    _run("uv", "build", "--no-sources", "--out-dir", str(output), str(PACKAGE), cwd=output, env=env)
    dependencies = []
    if vendor_wheel is not None:
        _vendor_dependency(vendor_wheel, "ta-lib")
        dependencies = ["--no-install-package", "ta-lib"]
    _run("uv", "sync", "--frozen", "--no-install-project", "--group", "test",
         "--python", python, "--project", str(PACKAGE), *dependencies, cwd=output, env=env)
    wheel, = output.glob("*.whl")
    source, = output.glob("*.tar.gz")
    executable = environment / "bin" / "python"
    if vendor_wheel is not None:
        _run("uv", "pip", "install", "--no-deps", "--python", str(executable), str(vendor_wheel), cwd=output, env=env)
    _run("uv", "pip", "install", "--no-deps", "--python", str(executable), str(wheel), cwd=output, env=env)
    provenance = json.loads(_run(
        str(executable), "-m", "guiyi_quant.compute.manifest", cwd=output, env=env, capture=True,
    ))
    if provenance["version"] != version:
        raise ValueError("QUANT_CORE_ARTIFACT_VERSION_MISMATCH")
    _run(str(executable), "-c", (
        "from pathlib import Path; from guiyi_quant import compute; import sys; "
        "assert Path(compute.__file__).is_relative_to(sys.prefix)"
    ), cwd=output, env=env)
    _run(str(executable), "-m", "pytest", "--import-mode=importlib", "-q", str(PACKAGE / "tests"),
         cwd=output, env=env)
    record = {
        "package": provenance,
        "artifacts": {wheel.name: {"type": "wheel", "sha256": _digest(wheel)},
                      source.name: {"type": "sdist", "sha256": _digest(source)}},
    }
    record_path = output / "release.json"
    with record_path.open("x") as file:
        json.dump(record, file, sort_keys=True, indent=2)
        file.write("\n")
    verified_wheel(record_path, expected_version=version, expected_sha256=record["artifacts"][wheel.name]["sha256"])


def main():
    parser = ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--python", default=sys.executable)
    build_parser.add_argument("--vendor-wheel", type=Path)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--record", type=Path, required=True)
    install_parser.add_argument("--consumer-lock", type=Path, required=True)
    install_parser.add_argument("--python", required=True)
    args = parser.parse_args()
    if args.command == "build":
        vendor_wheel = args.vendor_wheel.resolve() if args.vendor_wheel else None
        build(args.output.resolve(), args.python, vendor_wheel=vendor_wheel)
    else:
        install(args.record.resolve(), args.consumer_lock.resolve(), args.python)


if __name__ == "__main__":
    main()
