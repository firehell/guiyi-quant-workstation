"""Runtime service identities shared by bindings and ownership control.

This contract module performs no configuration, filesystem or Runtime access.
"""

REQUIRED_SERVICES = frozenset({
    "api", "web", "live", "market-feed", "alert", "reference-worker",
    "after-market", "weekly-audit", "late-provider-recovery", "log-rotate",
})

OPTIONAL_CONTINUOUS = frozenset({"home-projection"})
SERVICES = REQUIRED_SERVICES | OPTIONAL_CONTINUOUS
