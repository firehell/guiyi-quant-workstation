"""Bind HTDY's owned Live queue to already-proven H1 routes."""

from guiyi_quant.compute import REGISTRY

from .runtime import ComputeRuntime


class HTDYLiveCompute:
    """The sole HTDY socket owner serially submits its verified windows."""

    def __init__(self, products):
        self._products = frozenset(product.lower() for product in products)
        self._days = {}

    def submit_owned_live(self, commit, *, owner, run):
        scope = commit.scope
        day = scope.trading_day
        if scope.consumer != "htdy_simulation" or scope.product not in self._products:
            raise ValueError("HTDY_LIVE_SCOPE_UNPROVEN")
        if day not in self._days:
            if len(self._days) == 2:
                oldest = min(self._days)
                if day < oldest:
                    raise ValueError("HTDY_LIVE_DAY_RETIRED")
                self._days.pop(oldest).close()
            self._days[day] = ComputeRuntime(REGISTRY, max_checkpoints=len(self._products))
        runtime = self._days[day]
        runtime.admit_htdy_scope(scope)
        return runtime.submit_owned_live(commit, owner=owner, run=run)

    def close(self):
        for runtime in self._days.values():
            runtime.close()
        self._days.clear()
