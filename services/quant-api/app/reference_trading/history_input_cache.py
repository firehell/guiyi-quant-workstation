"""Reuse verified Newow market reads only inside an exclusive maintenance lease.

The caller groups one product's plan/build work in ``scope`` and supplies its
real Canonical maintenance guard. Strategy snapshots, identities, fingerprints,
formula outputs and reference manifests are always built by their original
readers. This cache never survives the lease or changes default composition.
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields


class HistoricalMarketReadCache:
    def __init__(self, maintenance_guard, *, cancelled=lambda: False):
        self._maintenance_guard = maintenance_guard
        self._cancelled = cancelled
        self._product = None
        self._active = False
        self._values = {}

    @contextmanager
    def scope(self, product=None):
        if self._active:
            raise ValueError("REFERENCE_INPUT_LEASE_ALREADY_HELD")
        if product is not None and (
            not isinstance(product, str)
            or not product.isalpha()
            or product != product.lower()
        ):
            raise ValueError("NEWOW_INVALID_PRODUCT")
        with self._maintenance_guard():
            self._product = product
            self._active = True
            try:
                yield
            finally:
                self._values.clear()
                self._product = None
                self._active = False

    @contextmanager
    def guard(self):
        """Nested input-reader guards reuse the outer lease; ordinary calls acquire."""
        if not self._active:
            with self._maintenance_guard():
                yield
        else:
            yield

    def _read(self, product, key, operation, *, mutable=False):
        if self._cancelled():
            from app.market_data.newow.product_reader import NewowProductReadCancelled

            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
        if not self._active:
            return operation()
        if self._product is None:
            self._product = product
        if product != self._product:
            raise ValueError("REFERENCE_INPUT_LEASE_PRODUCT_CONFLICT")
        if key not in self._values:
            # Keep this a bounded single-product helper, not a process-wide cache.
            if len(self._values) >= 32:
                raise ValueError("REFERENCE_INPUT_CACHE_BUDGET_EXCEEDED")
            self._values[key] = operation()
        return deepcopy(self._values[key]) if mutable else self._values[key]

    def reader(self, reader, *, policy_key):
        """Wrap pure market methods, with explicit quality/context policy identity.

        NewowProductReader.load returns immutable ProductReadSet and never reads
        query.strategy. All other query fields remain in the key. The caller
        must include its input quality and context frequency/policy scope in
        policy_key; different readers with different policies cannot alias.
        """
        hash(policy_key)
        cache = self

        class Reader:
            def load(self, query, as_of):
                key = (
                    "load",
                    policy_key,
                    as_of,
                    tuple(
                        (field.name, getattr(query, field.name))
                        for field in fields(query)
                        if field.name != "strategy"
                    ),
                )
                return cache._read(
                    query.product, key, lambda: reader.load(query, as_of)
                )

            def historical_input_bound(self, **kwargs):
                key = (
                    "historical_input_bound",
                    policy_key,
                    tuple(sorted(kwargs.items())),
                )
                return cache._read(
                    kwargs["product"],
                    key,
                    lambda: reader.historical_input_bound(**kwargs),
                )

            def historical_metadata_evidence(self, **kwargs):
                return self._proof("historical_metadata_evidence", kwargs)

            def historical_source_evidence(self, **kwargs):
                return self._proof("historical_source_evidence", kwargs)

            def _proof(self, method, kwargs):
                key = (method, policy_key, tuple(sorted(kwargs.items())))
                return cache._read(
                    kwargs["product"],
                    key,
                    lambda: getattr(reader, method)(**kwargs),
                    mutable=True,
                )

            def __getattr__(self, name):
                return getattr(reader, name)

        return Reader()
