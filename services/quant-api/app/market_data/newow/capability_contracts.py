"""Frozen wire scopes, shared with the generated Web validator data.

Reading an old version here does not open it as an API or Runtime capability.
"""
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any


@lru_cache(maxsize=1)
def _contracts() -> dict[str, Any]:
    return json.loads(files(__package__).joinpath("capability_contracts.json").read_text())


def capability_response(version: str) -> dict[str, Any]:
    """Return independent data so callers cannot mutate the frozen registry."""
    return deepcopy(_contracts()[version]["response"])


def capability_intraday_scope(version: str) -> frozenset[str]:
    return frozenset(_contracts()[version]["intradayScope"]["allowed"])
