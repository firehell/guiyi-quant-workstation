"""Bounded execution-input observation facts; never an execution permission."""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat

VERSION = "simnow_execution_input_check_v1"


def input_check_records(checks, *, products=()):
    """Persist times and sources, never a boolean that promises future freshness."""
    return {
        product: {
            k: v
            for k, v in checks.get(
                product, dict(schema=VERSION, status="NOT_CHECKED")
            ).items()
            if k not in ("fresh", "execution_permitted")
        }
        for product in sorted(set(products) | set(checks))
    }


def input_check_view(checks, now, *, connected, products=()):
    """Old success stays inspectable but cannot appear fresh after TTL/disconnect."""
    result = {}
    for product in sorted(set(products) | set(checks)):
        check = dict(checks.get(product, dict(schema=VERSION, status="NOT_CHECKED")))
        fresh = False
        if connected and check.get("status") == "VERIFIED_AT_CHECK":
            try:
                checked = datetime.fromisoformat(check["checked_at"])
                until = datetime.fromisoformat(check["valid_until"])
                fresh = checked <= now < until
            except (KeyError, TypeError, ValueError):
                pass
        result[product] = {**check, "fresh": fresh, "execution_permitted": False}
    return result


def read_input_checks(path, now):
    """One genuinely read-only projection; no SQLite, credentials or broker access."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("PRIVATE_INPUT_CHECK_REQUIRED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or info.st_size > 1024 * 1024
        ):
            raise ValueError("PRIVATE_INPUT_CHECK_REQUIRED")
        data = json.loads(os.read(fd, 1024 * 1024 + 1))
    finally:
        os.close(fd)
    products = data["products"]
    if (
        not isinstance(products, list)
        or not 1 <= len(products) <= 60
        or len(set(products)) != len(products)
        or any(
            not isinstance(p, str) or re.fullmatch("[A-Z]{1,3}", p) is None
            for p in products
        )
        or data["mode"] not in ("observe", "manage", "trade")
    ):
        raise ValueError("INPUT_CHECK_SCOPE_INVALID")
    published = datetime.fromisoformat(data["at"])
    connected = (
        data.get("connection") == "LOGGED_IN"
        and published <= now
        and (now - published).total_seconds() < 30
    )
    checks = data.get("input_checks", {})
    if not isinstance(checks, dict) or set(checks) - set(products):
        raise ValueError("INPUT_CHECK_SCOPE_INVALID")
    return dict(
        schema=VERSION,
        checked_at=now.isoformat(),
        mode=data["mode"],
        host_fresh=connected,
        checks=input_check_view(checks, now, connected=connected, products=products),
        execution_permitted=False,
    )
