"""Freeze identical Newow market reads within one bounded scheduler unit."""

from datetime import datetime


class NewowInputCache:
    def __init__(self):
        self.observed_at: datetime | None = None
        self._values = {}

    def begin(self, observed_at: datetime) -> None:
        self.end()
        self.observed_at = observed_at

    def end(self) -> None:
        self._values.clear()
        self.observed_at = None

    def read(self, key, read):
        if self.observed_at is None:
            return read()
        if key not in self._values:
            self._values[key] = read()
        return self._values[key]

    def live_reader(self, market_read):
        cache = self

        class LiveReader:
            def observation_snapshot(self, query, after, now):
                return cache.read(("live", query, after, now), lambda: market_read.observation_snapshot(query, after, now))

            def __getattr__(self, name):
                return getattr(market_read, name)

        return LiveReader()

    def canonical_reader(self, reader, identity):
        cache = self
        incremental = getattr(reader, "forward_incremental_bar", None)
        if incremental is None:
            return reader

        class CanonicalReader:
            def forward_incremental_bar(self, **kwargs):
                key = ("canonical", identity.futures_adaptation_version, *sorted(kwargs.items()))
                return cache.read(key, lambda: incremental(**kwargs))

            def __getattr__(self, name):
                return getattr(reader, name)

        return CanonicalReader()
