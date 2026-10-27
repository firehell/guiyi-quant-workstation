"""Local-only SimNow Keychain provisioning. Never pass secrets in argv or files."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "quant-core"))

from guiyi_quant.simnow_execution.credentials import (
    CredentialError,
    CredentialStore,
    fingerprint_for,
)


def provision(store: CredentialStore, expected_account_id: str | None = None) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CredentialError("LOCAL_TTY_REQUIRED")
    user = input("SimNow第一套投资者代码：").strip()
    account = fingerprint_for(user)
    if expected_account_id is not None and account != expected_account_id:
        raise CredentialError("CREDENTIAL_IDENTITY_MISMATCH")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("交易密码（隐藏）：")
    return store.save(user, password)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="本机 SimNow Keychain 凭据配置")
    parser.add_argument("action", choices=("provision", "check"))
    parser.add_argument("--account-id", help="仅 check 使用，64位账户指纹")
    parser.add_argument("--expected-account-id", help="仅 provision 使用，预期账户指纹")
    args = parser.parse_args(argv)
    if args.action == "provision" and args.account_id is not None:
        parser.error("provision 不接受账户参数")
    if args.action == "check" and args.account_id is None:
        parser.error("check 需要账户指纹")
    if args.action == "check" and args.expected_account_id is not None:
        parser.error("check 不接受预期账户参数")
    try:
        store = CredentialStore()
        if args.action == "provision":
            account = provision(store, args.expected_account_id)
            print(f"CREDENTIAL_STORED account_id={account}")
        else:
            store.load(args.account_id)
            print(f"CREDENTIAL_AVAILABLE account_id={args.account_id}")
        return 0
    except (CredentialError, getpass.GetPassWarning) as exc:
        # Only fixed error codes produced by this module; no native error text.
        code = str(exc) if isinstance(exc, CredentialError) else "LOCAL_TTY_REQUIRED"
        print(code, file=sys.stderr)
        return 2
    except Exception:
        print("CREDENTIAL_UNAVAILABLE", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
