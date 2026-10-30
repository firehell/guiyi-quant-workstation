"""Explicit dispatch baseline identity; never changes an account or its capital."""

from dataclasses import dataclass
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

from ..htdy_account_execution.codec import digest

LEGACY = "legacy_100k_v1"
ORIGINAL = "original_anchor_v1"


@dataclass(frozen=True, slots=True)
class AccountProfile:
    profile_id: str = LEGACY
    account_id: str | None = None
    initial_readback_sha256: str | None = None

    def __post_init__(self):
        if self.profile_id == LEGACY:
            valid = self.account_id is None and self.initial_readback_sha256 is None
        else:
            valid = self.profile_id == ORIGINAL and all(
                isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value)
                for value in (self.account_id, self.initial_readback_sha256)
            )
        if not valid:
            raise ValueError("ACCOUNT_PROFILE_INVALID")

    @classmethod
    def from_dict(cls, value):
        if (
            type(value) is not dict
            or set(value) != {"profile_id", "account_id", "initial_readback_sha256"}
            or value.get("profile_id") != ORIGINAL
        ):
            raise ValueError("ACCOUNT_PROFILE_INVALID")
        return cls(**value)


def validate_profile(profile, state):
    if profile is None:
        profile = AccountProfile()
    if type(profile) is not AccountProfile:
        raise ValueError("ACCOUNT_PROFILE_INVALID")
    baseline = state.initial_readback
    if profile.profile_id == ORIGINAL:
        if (
            profile.account_id != state.account_id
            or profile.initial_readback_sha256 != digest(baseline)
        ):
            raise ValueError("ACCOUNT_PROFILE_ANCHOR_MISMATCH")
        return
    # Preserve the original bounded 100k profile exactly, including its date gate.
    if (
        baseline.snapshot.balance != Decimal("100000")
        or (
            baseline.source_id.split(":")[1]
            if baseline.source_id.startswith("ctp-inventory:")
            else baseline.snapshot.at.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
                "%Y%m%d"
            )
        )
        < "20261027"
    ):
        raise ValueError("INITIAL_100K_BASELINE_REQUIRED")
