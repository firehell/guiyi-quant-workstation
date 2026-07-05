#!/usr/bin/env python3
"""只读检查当前 license 是否含 RQAlpha 期货回测权限（不打印 license 原文）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_license_key() -> str | None:
    for env_name in ("RQDATA_LICENSE_KEY", "RQSDK_LICENSE", "RQDATAC_CONF", "RQDATAC2_CONF"):
        value = os.getenv(env_name)
        if value:
            return value
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("RQDATA_LICENSE_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> int:
    try:
        from rqsdk.license_helper import format_rqdatac_uri, get_permissions_info
    except ImportError:
        print("请先安装 rqsdk: pip install rqsdk")
        return 1

    raw = _load_license_key()
    if not raw:
        print("未找到 license。请设置 RQDATA_LICENSE_KEY 或运行 rqsdk license -l <key>")
        return 1

    uri = format_rqdatac_uri(raw)
    info = get_permissions_info(uri)

    print("剩余天数:", info.get("date_to_expire"))
    print("许可类型:", "FULL" if "rqdata_limit__license_type__full" in info.get("current_permissions", []) else "其他/试用")
    print()
    print("RQAlpha 回测权限（商品/股指/股债期货）:")
    found = False
    for row in info.get("permissions_table", []):
        if row.get("type") == "商品、股指、股债期货" and "RQAlpha" in row.get("name", ""):
            found = True
            print(f"  - {row.get('back_test_level')}: enable={row.get('enable')}")
    if not found:
        print("  未找到期货回测条目，请联系米筐确认 license。")
        return 1

    perms = set(info.get("current_permissions", []))
    has_future = "rqsdk__mod_backtest_future" in perms
    print()
    print("rqsdk__mod_backtest_future:", "有" if has_future else "无")
    return 0 if has_future else 1


if __name__ == "__main__":
    raise SystemExit(main())
