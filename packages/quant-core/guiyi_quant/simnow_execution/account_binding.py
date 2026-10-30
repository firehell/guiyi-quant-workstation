"""Read-only proof of the existing four journals; never initialize or migrate."""

from contextlib import closing, contextmanager
from contextvars import ContextVar
from hashlib import sha256
from threading import get_ident
from pathlib import Path
import json
import os
import sqlite3
import stat

from ..htdy_account_execution import LocalStore


# Private, same-call proof reuse. No API accepts a caller-supplied account state.
_snapshot_proof = ContextVar("simnow_snapshot_account_proof", default=None)


def _ledger_identity(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED")
        content_hash = sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                content_hash.update(chunk)
        after = os.fstat(fd)

        def signature(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                info.st_mode,
                info.st_uid,
                info.st_nlink,
            )

        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_mode & 0o077
            or before.st_nlink != 1
            or signature(before) != signature(after)
            or path.is_symlink()
            or signature(path.lstat()) != signature(after)
        ):
            raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED")
        return signature(after), content_hash.hexdigest()
    finally:
        os.close(fd)


@contextmanager
def _snapshot_account_proof(root, account):
    """One synchronous snapshot only; all other journal checks remain uncached."""
    if _snapshot_proof.get() is not None:
        raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED")
    proof = dict(
        key=(Path(root), account),
        owner=get_ident(),
        active=True,
        state=None,
        identity=None,
    )
    token = _snapshot_proof.set(proof)
    try:
        yield
        if (
            proof["state"] is not None
            and _ledger_identity(Path(root) / account / "account.sqlite")
            != proof["identity"]
        ):
            raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED")
    finally:
        proof["active"] = False
        _snapshot_proof.reset(token)


def _verified_ledger(root, account):
    proof = _snapshot_proof.get()
    path = Path(root) / account / "account.sqlite"
    if proof is None:
        return LocalStore.inspect(path)
    if (
        not proof["active"]
        or proof["owner"] != get_ident()
        or proof["key"] != (Path(root), account)
    ):
        raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED")
    identity = _ledger_identity(path)
    if proof["state"] is not None:
        if identity != proof["identity"]:
            raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED")
        return proof["state"]
    state = LocalStore.inspect(path)
    if _ledger_identity(path) != identity:
        raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED")
    proof.update(state=state, identity=identity)
    return state


def existing_account(root, account):
    folder = Path(root) / account
    try:
        for directory in (Path(root), folder):
            info = directory.stat()
            if (
                directory.is_symlink()
                or directory.resolve() != directory
                or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise ValueError
        for name in (
            "account.sqlite",
            "dispatch.sqlite",
            "signals.sqlite",
            "native-evidence.sqlite",
        ):
            path = folder / name
            info = path.stat()
            if (
                path.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
            ):
                raise ValueError
            with path.open("rb") as stream:
                header = stream.read(20)
            if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
                raise ValueError
        state = _verified_ledger(root, account)
        if state.account_id != account:
            raise ValueError
        expected = {
            "dispatch.sqlite": (
                "SELECT account,schema FROM identity",
                [(account, "simnow_dispatch_v1")],
            ),
            "signals.sqlite": (
                "SELECT account,scope FROM identity",
                [
                    (
                        account,
                        json.dumps(tuple(sorted(p.product for p in state.products))),
                    )
                ],
            ),
            "native-evidence.sqlite": ("SELECT account FROM owner", [(account,)]),
        }
        for name, (sql, rows) in expected.items():
            with closing(
                sqlite3.connect((folder / name).as_uri() + "?mode=ro", uri=True)
            ) as db:
                db.execute("PRAGMA query_only=ON")
                if db.execute(sql).fetchall() != rows:
                    raise ValueError
        return state
    except (OSError, ValueError, sqlite3.Error):
        raise ValueError("EXISTING_ACCOUNT_BINDING_REQUIRED") from None
