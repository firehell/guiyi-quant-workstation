"""Fixed-file strategy parameter loader used by registered strategies."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


STRATEGY_PARAMS_FILE_ENV = "GUIYI_BACKTEST_STRATEGY_PARAMS_FILE"


class StrategyParamsError(ValueError):
    def __init__(self) -> None:
        super().__init__("STRATEGY_PARAMS_INVALID")


def load_strategy_params() -> dict[str, Any]:
    """Read parameters only from the runner-provided fixed JSON file."""

    raw_path = os.environ.get(STRATEGY_PARAMS_FILE_ENV, "")
    path = Path(raw_path) if raw_path else Path()
    if not raw_path or not path.is_absolute() or not path.is_file():
        raise StrategyParamsError
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyParamsError from exc
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) for key in payload
    ):
        raise StrategyParamsError
    return payload
