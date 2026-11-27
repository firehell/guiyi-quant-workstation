"""Check the installed Quant Core identity at formal assembly."""

from hashlib import sha256
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
import sys
import tomllib


def locked_core(lock_path: Path) -> tuple[dict, Path]:
    try:
        pin = tomllib.loads(lock_path.read_text())
        artifact = distribution(pin["package"])
        package = artifact.locate_file("guiyi_quant").resolve(strict=True)
        expected = pin["version"], pin["source_sha256"]
    except (KeyError, OSError, PackageNotFoundError) as exc:
        raise ValueError("QUANT_CORE_INSTALLED_ARTIFACT_UNPROVEN") from exc
    if artifact.version != expected[0] or not package.is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError("QUANT_CORE_INSTALLED_ARTIFACT_UNPROVEN")
    content = sha256()
    for source in sorted(package.rglob("*.py"), key=lambda item: item.relative_to(package).as_posix()):
        relative = source.relative_to(package).as_posix()
        if source.resolve() != source:
            raise ValueError("QUANT_CORE_INSTALLED_ARTIFACT_UNPROVEN")
        content.update(relative.encode() + b"\0" + sha256(source.read_bytes()).digest())
    if content.hexdigest() != expected[1]:
        raise ValueError("QUANT_CORE_INSTALLED_ARTIFACT_UNPROVEN")
    return pin, package


def require_locked_core() -> None:
    from guiyi_quant import compute

    pin, package = locked_core(Path(__file__).resolve().parents[2] / "quant-core-release.toml")
    if Path(compute.__file__).resolve() != package / "compute/__init__.py":
        raise ValueError("QUANT_CORE_INSTALLED_ARTIFACT_UNPROVEN")
    from guiyi_quant.compute.manifest import require_contract

    require_contract(compute=pin["compute_contract_version"], result=pin["result_schema_version"],
                     state=pin["state_schema_version"])
