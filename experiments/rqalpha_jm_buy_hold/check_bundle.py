#!/usr/bin/env python3
"""检查 RQAlpha bundle 是否满足 JM 期货日线回测要求。"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE = Path.home() / ".rqalpha-plus" / "bundle"
FUTURES_H5 = BUNDLE / "futures.h5"
REQUIRED_FIELDS = {
    "datetime",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "open_interest",
}


def main() -> int:
    if not FUTURES_H5.exists():
        print(f"未找到 {FUTURES_H5}")
        print("请先执行: rqsdk download-data --sample")
        return 1

    try:
        import h5py
    except ImportError:
        print("请安装 h5py: pip install h5py")
        return 1

    with h5py.File(FUTURES_H5, "r") as f:
        if "JM88" not in f:
            print("bundle 中无 JM88，请执行: rqsdk update-data --base")
            return 1

        fields = {name for name in f["JM88"].dtype.names or ()}
        missing = REQUIRED_FIELDS - fields
        if missing:
            print("bundle 期货日线字段过旧，缺少:", ", ".join(sorted(missing)))
            print()
            print("这是样例包与当前 rqalpha-plus 版本不兼容，不是 license 权限问题。")
            print("请执行（会消耗 RQData 流量，耗时较长）:")
            print("  rqsdk update-data --base")
            return 1

        bars = f["JM88"]
        if len(bars) == 0:
            print("JM88 无行情数据")
            return 1

        first_dt = bars[0]["datetime"]
        last_dt = bars[-1]["datetime"]
        print("bundle 检查通过")
        print(f"  路径: {FUTURES_H5}")
        print(f"  JM88 字段: {sorted(fields)}")
        print(f"  JM88 条数: {len(bars)}")
        print(f"  日期范围( int ): {first_dt} ~ {last_dt}")
        print()
        print("若回测区间超出上述范围，同样需要: rqsdk update-data --base")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
