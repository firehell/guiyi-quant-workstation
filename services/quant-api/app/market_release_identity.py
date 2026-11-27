"""Version and deployment identity for the Market Foundation component."""
import re

MARKET_TAG_PREFIX = "market-foundation/v"
MARKET_VERSION_PATH = "services/quant-api/app/market_version.py"
APPLICATION_TAG = r"v[0-9]+\.[0-9]+\.[0-9]+"

MARKET_SERVICES = frozenset({
    "market-feed", "live", "after-market", "late-provider-recovery", "weekly-audit",
})


def market_release_version(tag: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"market-foundation/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag)
    return tuple(map(int, match.groups())) if match else None


def valid_release_tag(tag: str) -> bool:
    return bool(re.fullmatch(APPLICATION_TAG, tag) or market_release_version(tag) is not None)


def declared_market_release_tag(source: str) -> str | None:
    lines = source.splitlines()
    if len(lines) != 3 or lines[:2] != ['"""Release version for the Market Foundation component."""', ""]:
        return None
    version = re.fullmatch(r'MARKET_RELEASE_VERSION = "([0-9.]+)"', lines[2])
    if version is None:
        return None
    tag = MARKET_TAG_PREFIX + version[1]
    return tag if market_release_version(tag) is not None else None
