"""Canonical read-only DCE JM trading-session contract."""

from __future__ import annotations

from datetime import time
from types import MappingProxyType
from typing import Final


JM_CONTRACT_TRADING_HOURS: Final = (
    "21:01-23:00,09:01-10:15,10:31-11:30,13:31-15:00"
)
JM_SESSION_ROWS: Final = (
    ("night", time(21, 0), time(23, 0)),
    ("day_am_1", time(9, 0), time(10, 15)),
    ("day_am_2", time(10, 30), time(11, 30)),
    ("day_pm", time(13, 30), time(15, 0)),
)
JM_SESSION_PROVIDER: Final = "rqdata_contract_v1"
JM_SESSION_BOUNDS: Final = MappingProxyType(
    {name: (start, end) for name, start, end in JM_SESSION_ROWS}
)
JM_SESSION_RANK: Final = MappingProxyType(
    {name: index for index, (name, _start, _end) in enumerate(JM_SESSION_ROWS)}
)
