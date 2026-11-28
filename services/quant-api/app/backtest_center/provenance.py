"""Content identity verified by both the workstation and the Plus interpreter."""

from hashlib import sha256
from pathlib import Path

from .codec import digest

_EXECUTION_FILES = (
    "codec.py", "errors.py", "native_plus.py", "plus_costs.py", "plus_entry.py", "plus_inputs.py",
    "plus_reconcile.py", "provenance.py",
)


def code_digest() -> str:
    import guiyi_quant

    adapter = Path(__file__).resolve().parent
    core = Path(guiyi_quant.__file__).resolve().parent
    files = {
        **{f"adapter/{name}": adapter / name for name in _EXECUTION_FILES},
        **{f"quant_core/{path.relative_to(core).as_posix()}": path for path in core.rglob("*.py")},
    }
    return digest({name: sha256(path.read_bytes()).hexdigest() for name, path in files.items()})
