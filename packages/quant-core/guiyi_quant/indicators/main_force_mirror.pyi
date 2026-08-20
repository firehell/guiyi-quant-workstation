from dataclasses import dataclass
from typing import Any, Final, Literal, Sequence, TypeAlias

import numpy as np

INDICATOR_CODE: Final[Literal["main_force_mirror_v0"]]
INDICATOR_VERSION: Final[Literal["designed-v0"]]
MainForceMirrorState: TypeAlias = Literal[
    "entry", "wash", "pull_up", "distribute", "exit", "lure"
]

@dataclass(frozen=True)
class MainForceMirrorResult:
    datetimes: np.ndarray
    score: np.ndarray
    state: np.ndarray
    ready: np.ndarray
    caution: np.ndarray
    caution_level: np.ndarray
    flow: np.ndarray
    range_position: np.ndarray
    metadata: dict[str, Any]

def classify_main_force_mirror_state(
    range_position: float,
    flow: float,
    flow_delta: float,
    price_delta: float,
) -> MainForceMirrorState: ...

def compute_main_force_mirror(
    datetimes: Sequence[Any],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    *,
    volume_window: int = ...,
    flow_ema_period: int = ...,
    range_window: int = ...,
    caution_high_window: int = ...,
    caution_quiet_window: int = ...,
    flow_clip: float = ...,
    score_scale: float = ...,
    exit_lure_scale: float = ...,
    caution_level: float = ...,
) -> MainForceMirrorResult: ...
