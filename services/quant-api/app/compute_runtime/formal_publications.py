"""Formal receipt poller with explicit, bounded research subscriptions."""

from datetime import date
import json
from contextlib import ExitStack

from guiyi_quant.compute import FeatureRequest

from app.market_data.after_market_history import _bytes
from app.market_data.market_archive import RECEIPT_DIRECTORY

from .artifact import require_locked_core
from .canonical_publications import CanonicalPublicationCompute, CanonicalResearchWindow
from .contracts import ComputeScope


def configured_windows(root):
    try:
        rows = json.loads(_bytes(root / "canonical-compute-windows.json", max_bytes=65536))
    except FileNotFoundError:
        return ()
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("COMPUTE_CANONICAL_SUBSCRIPTION_INVALID")
    windows = []
    try:
        for row in rows:
            if set(row) != {"product", "contract", "frequency", "features", "since", "through"}:
                raise ValueError
            contract = row["contract"]
            features = row["features"]
            if (not isinstance(features, list) or not 1 <= len(features) <= 16
                    or any(not isinstance(name, str) or not name for name in features)):
                raise ValueError
            windows.append(CanonicalResearchWindow(
                ComputeScope("canonical_research", row["product"], contract, f"contract:{contract}",
                             row["frequency"], tuple(FeatureRequest(name) for name in features)),
                date.fromisoformat(row["since"]), date.fromisoformat(row["through"]),
            ))
    except (KeyError, TypeError, ValueError):
        raise ValueError("COMPUTE_CANONICAL_SUBSCRIPTION_INVALID") from None
    return tuple(windows)


class FormalCanonicalPublications(ExitStack):
    def __init__(self, engine, canonical, *, now):
        super().__init__()
        self._engine = engine
        self._canonical = canonical
        self._now = now
        self._bound = None
        self._accepted = None

    def poll(self, root, receipt, *, stop_requested=lambda: False):
        if self._bound is None:
            windows = configured_windows(root)
            if not windows:
                return "disabled"
            require_locked_core()
            runtime = self.enter_context(CanonicalPublicationCompute(
                self._engine, self._canonical, windows, now=self._now, archive_root=root,
            ))
            self._bound = (root, runtime)
        expected_root, runtime = self._bound
        if root != expected_root:
            raise ValueError("COMPUTE_CANONICAL_ARCHIVE_BINDING_CHANGED")
        if receipt is None:
            return "waiting_archive"
        if receipt.identity != self._accepted:
            runtime.accept(root / RECEIPT_DIRECTORY / f"{receipt.identity}.json", receipt.trading_day,
                           stop_requested=stop_requested)
            self._accepted = receipt.identity
        return "current"
