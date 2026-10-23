"""Disposable, explicitly stale homepage display cache; never current authority."""
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
import json
from threading import RLock
from time import monotonic


class HomeDisplayCache:
    def __init__(self, *, max_entries=60, max_bytes=10 * 1024 * 1024, ttl=7 * 86400, clock=monotonic):
        self._entries = OrderedDict()
        self._max_entries, self._max_bytes, self._ttl = max_entries, max_bytes, ttl
        self._clock, self._lock = clock, RLock()

    def _prune(self):
        for key in list(self._entries):
            if self._clock() - self._entries[key][0] >= self._ttl:
                del self._entries[key]
        while len(self._entries) > self._max_entries or sum(entry[2] for entry in self._entries.values()) > self._max_bytes:
            self._entries.popitem(last=False)

    def put(self, card, saved_at):
        # A failed/incomplete read cannot replace a successful display snapshot.
        if any(fact.get('status') not in {'ready', 'warming'} for periods in card['strategies'].values() for fact in periods.values()):
            return
        card = deepcopy(card)
        for periods in card['strategies'].values():
            for fact in periods.values():
                fact.pop('snapshot_token', None)
                fact.pop('page_performance', None)
                fact.pop('snapshot_context', None)
        item = {'product': card['product'], 'saved_at': saved_at, 'card': card}
        size = len(json.dumps(item).encode())
        if size > self._max_bytes:
            return
        with self._lock:
            prior = self._entries.get(card['product'])
            if prior and datetime.fromisoformat(prior[1]['saved_at']) > datetime.fromisoformat(saved_at):
                return
            self._entries.pop(card['product'], None)
            self._entries[card['product']] = (self._clock(), item, size)
            self._prune()

    def read(self):
        with self._lock:
            self._prune()
            return {'schema_version': 'newow_home_display_cache_v1', 'stale': True,
                    'executable': False, 'read_at': datetime.now(UTC).isoformat(),
                    'items': deepcopy([entry[1] for entry in self._entries.values()])}
