"""Version and deployment identity for the Market Foundation component."""
import re

MARKET_TAG_PREFIX = "market-foundation/v"
APPLICATION_TAG = r"v[0-9]+\.[0-9]+\.[0-9]+"

MARKET_SERVICES = frozenset({
    "market-feed", "live", "after-market", "late-provider-recovery", "weekly-audit",
})


def market_release_version(tag: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"market-foundation/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag)
    return tuple(map(int, match.groups())) if match else None


def valid_release_tag(tag: str) -> bool:
    return bool(re.fullmatch(APPLICATION_TAG, tag) or market_release_version(tag) is not None)
