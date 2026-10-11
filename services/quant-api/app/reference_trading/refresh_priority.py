"""Local scheduling permission; the Catalog lease still authorizes source reads."""
from contextlib import contextmanager
from threading import Condition, Event


class RefreshPriority:
    def __init__(self, *, wait_seconds: float = 2):
        self._condition = Condition()
        self._yield = Event()
        self._active = False
        self._permit = False
        self._foreground = 0
        self._urgent = 0
        self._wait_seconds = wait_seconds

    def grant(self) -> None:
        with self._condition:
            if not self._active and not self._foreground:
                self._permit = True

    def can_run(self) -> bool:
        with self._condition:
            return self._permit and not self._active and not self._foreground

    def begin(self) -> bool:
        with self._condition:
            if not self.can_run():
                return False
            self._permit = False
            self._active = True
            self._yield.clear()
            return True

    def finish(self) -> None:
        with self._condition:
            self._active = False
            self._yield.clear()
            self._condition.notify_all()

    def yield_requested(self) -> bool:
        return self._yield.is_set()

    def withdraw(self) -> None:
        with self._condition:
            self._permit = False

    @contextmanager
    def observation(self):
        with self._condition:
            self._urgent += 1
            self._permit = False
            if self._active:
                self._yield.set()
        try:
            yield
        finally:
            with self._condition:
                self._urgent -= 1

    @contextmanager
    def foreground(self):
        with self._condition:
            self._foreground += 1
            self._permit = False
            if self._active:
                if self._urgent:
                    self._yield.set()
                # Expiry only stops waiting. It never releases a lease or
                # asserts the background operation has completed.
                self._condition.wait_for(lambda: not self._active, timeout=self._wait_seconds)
        try:
            yield
        finally:
            with self._condition:
                self._foreground -= 1


def historical_rest_allowed(session_factory, products, *, now):
    """Resolve the existing authority; unknown or imminent sessions defer history."""
    from datetime import timedelta
    from app.db.readonly import readonly_transaction
    from app.market_data.market_phase import MarketPhase, MarketPhaseResolver
    if len(set(products)) != 60:
        return False
    with session_factory() as session, readonly_transaction(session, timeout_seconds=15):
        resolver = MarketPhaseResolver(session)
        for product in products:
            phase = resolver.resolve(product, now)
            if (phase.phase not in (MarketPhase.BREAK, MarketPhase.CLOSED)
                    or phase.next_session_start is None
                    or phase.next_session_start <= now + timedelta(seconds=140)):
                return False
    return True
