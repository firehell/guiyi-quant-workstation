"""Presentation bounds for new exact plans, clamped only to authoritative listing."""
from datetime import date

FLOORS = {'1d': date(2023, 1, 1), '1w': date(2023, 1, 1), '60m': date(2025, 9, 25),
          '5m': date(2025, 9, 25), '15m': date(2025, 9, 25), '30m': date(2025, 9, 25)}


def new_plan_since(identity, historical_storage_start):
    """Use NewowProductReader's existing coverage seam, never earliest map data.

    This chooses a valid request boundary. The original reader/planner must still
    prove every rank1/session/physical input after that boundary without fallback.
    Frozen plans do not call this helper and retain their exact hash and bytes.
    """
    if identity.frequency not in FLOORS:
        raise ValueError('HISTORY_FREQUENCY_UNSUPPORTED')
    listed = historical_storage_start(identity.product)
    if type(listed) is not date:
        raise ValueError('HISTORY_LISTING_DATE_UNAVAILABLE')
    return max(FLOORS[identity.frequency], listed)
