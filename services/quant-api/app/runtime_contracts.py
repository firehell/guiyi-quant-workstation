"""Runtime service identities shared by bindings and ownership control.

This contract module performs no configuration, filesystem or Runtime access.
"""

SERVICES = frozenset({
    "api", "web", "live", "market-feed", "alert", "reference-worker",
    "after-market", "weekly-audit", "late-provider-recovery", "log-rotate",
})
