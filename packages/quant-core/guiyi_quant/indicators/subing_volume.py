"""Completed physical-bar volume comparison, independent of entry decisions."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


VERSION = 'subing_volume_d1_gt1_m30_tiers_v2'


@dataclass(frozen=True)
class VolumeObservation:
    current: Decimal | None
    previous: Decimal | None
    ratio: Decimal | None
    previous_end: datetime | None
    reason: str | None
    effective: bool | None = None
    tier: str | None = None


@dataclass(frozen=True)
class VolumeState:
    identity: tuple[str, str]
    previous: Decimal | None = None
    last_end: datetime | None = None


def initial_state(contract: str, frequency: str) -> VolumeState:
    if not contract or frequency not in ('1d', '30m'):
        raise ValueError('VOLUME_IDENTITY_INVALID')
    return VolumeState((contract, frequency))


def observe(state: VolumeState, *, contract: str, frequency: str, bar_end: datetime,
            volume: Decimal | None) -> tuple[VolumeState, VolumeObservation]:
    """Caller validates completed-bar coverage; never skip a missing predecessor."""
    if state.identity != (contract, frequency):
        raise ValueError('VOLUME_IDENTITY_CHANGED')
    if bar_end.tzinfo is None or bar_end.utcoffset() is None or (state.last_end is not None and bar_end <= state.last_end):
        raise ValueError('VOLUME_TIME_INVALID')
    if not isinstance(volume, Decimal) or not volume.is_finite() or volume < 0:
        return VolumeState(state.identity, None, bar_end), VolumeObservation(None, state.previous, None, state.last_end, 'INPUT_INVALID')
    new = VolumeState(state.identity, volume, bar_end)
    if state.previous is None:
        return new, VolumeObservation(volume, None, None, state.last_end, 'PREVIOUS_UNAVAILABLE')
    ratio = volume/state.previous if state.previous > 0 else None
    effective = volume > state.previous
    tier = None
    if frequency == '30m':
        if not effective:
            tier = 'NOT_EXPANDED'
        elif state.previous == 0:
            tier = 'ZERO_BASELINE'
        elif volume < state.previous * Decimal('2'):
            tier = 'TIER_1'
        elif volume < state.previous * Decimal('3'):
            tier = 'TIER_2'
        else:
            tier = 'TIER_3'
    return new, VolumeObservation(volume, state.previous, ratio, state.last_end, None, effective, tier)
