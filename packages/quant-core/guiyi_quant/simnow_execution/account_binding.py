"""Read-only proof of the existing four journals; never initialize or migrate."""

from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import stat

from ..htdy_account_execution import LocalStore


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
        state = LocalStore.inspect(folder / "account.sqlite")
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
