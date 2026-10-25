"""SPI mixin: layer before a logged-in SPI class; never auto-registers/reconnects."""

from datetime import datetime, UTC


class Callbacks:
    """Host sets execution_adapter; drain on its controlled main loop, not here."""

    def _stage(self, method, *args):
        try:
            method(*args, datetime.now(UTC))
        except Exception:
            self.execution_adapter._faulted = True
            # Adapter already persisted a fixed fault. Never leak raw C++ callback errors.
            return

    def OnRtnOrder(self, row):
        self._stage(self.execution_adapter.order_callback, row)

    def OnRtnTrade(self, row):
        self._stage(self.execution_adapter.trade_callback, row)

    def OnRspOrderInsert(self, row, info, request_id, last):
        self._stage(
            self.execution_adapter.response,
            "SUBMIT",
            row,
            int(info.ErrorID) if info is not None else -1,
            request_id,
        )

    def OnErrRtnOrderInsert(self, row, info):
        self.OnRspOrderInsert(row, info, row.RequestID, True)

    def OnRspOrderAction(self, row, info, request_id, last):
        self._stage(
            self.execution_adapter.response,
            "CANCEL",
            row,
            int(info.ErrorID) if info is not None else -1,
            request_id,
        )

    def OnErrRtnOrderAction(self, row, info):
        self.OnRspOrderAction(row, info, row.RequestID, True)

    def OnFrontDisconnected(self, reason):
        self._stage(self.execution_adapter.disconnected)
        parent = getattr(super(), "OnFrontDisconnected", None)
        if parent is not None:
            parent(reason)
