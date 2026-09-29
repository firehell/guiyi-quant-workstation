"""Local evidence storage: confined names, exclusive creation, no silent overwrite."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
from .context import need


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


class EvidenceStore:
    def __init__(self, root: Path):
        root = Path(root).absolute()
        need(not root.is_symlink() and root.resolve() == root, 'OUTPUT_SYMLINK_FORBIDDEN')
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        name_path = Path(name)
        need(not name_path.is_absolute() and '..' not in name_path.parts and bool(name_path.parts), 'EVIDENCE_PATH_ESCAPE')
        result = self.root / name_path
        need(result.resolve().is_relative_to(self.root), 'EVIDENCE_PATH_ESCAPE')
        for component in [result, *result.parents]:
            if component == self.root.parent:
                break
            need(not component.is_symlink(), 'EVIDENCE_SYMLINK_FORBIDDEN')
        return result

    def write(self, name: str, body: object) -> dict:
        # Encode first: a serializer failure must not leave a purported result.
        encoded = (json.dumps(body, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path(name)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as out:
            out.write(encoded); out.flush(); os.fsync(out.fileno())
        return dict(path=name, sha256=hashlib.sha256(encoded).hexdigest(), bytes=len(encoded))

    def read(self, name: str) -> dict:
        path = self.path(name)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            need(stat.S_ISREG(os.fstat(source.fileno()).st_mode), 'REGULAR_EVIDENCE_REQUIRED')
            return json.load(source)

    def reference(self, name: str) -> dict:
        path = self.path(name)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            need(stat.S_ISREG(os.fstat(source.fileno()).st_mode), 'REGULAR_EVIDENCE_REQUIRED')
            digest_value = hashlib.file_digest(source, 'sha256').hexdigest()
            size = os.fstat(source.fileno()).st_size
        return dict(path=name, sha256=digest_value, bytes=size)
