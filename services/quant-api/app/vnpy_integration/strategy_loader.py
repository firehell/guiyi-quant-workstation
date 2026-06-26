from __future__ import annotations

import importlib
from typing import Any

from app.vnpy_integration.errors import StrategyLoadError


def load_strategy_class(class_path: str) -> type[Any]:
    module_name, class_name = _split_class_path(class_path)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise StrategyLoadError(f"Cannot import strategy module: {module_name}") from exc

    try:
        strategy_class = getattr(module, class_name)
    except AttributeError as exc:
        raise StrategyLoadError(f"Strategy class not found: {class_path}") from exc

    if not isinstance(strategy_class, type):
        raise StrategyLoadError(f"Strategy path does not resolve to a class: {class_path}")
    return strategy_class


def _split_class_path(class_path: str) -> tuple[str, str]:
    candidate = class_path.strip()
    if not candidate:
        raise StrategyLoadError("strategy class path cannot be empty")
    if ":" in candidate:
        module_name, class_name = candidate.rsplit(":", 1)
    else:
        module_name, class_name = candidate.rsplit(".", 1) if "." in candidate else ("", "")
    if not module_name or not class_name:
        raise StrategyLoadError(f"Invalid strategy class path: {class_path}")
    return module_name, class_name
