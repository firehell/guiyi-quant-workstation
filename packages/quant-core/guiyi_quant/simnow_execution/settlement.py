"""Connection-bound settlement proof; Gateway validates matching complete replies.

ConfirmDate is retained as reported. A successful confirmation response proves
the current login's confirmation, even when its civil date differs from TradingDay.
"""

from datetime import datetime

from ..htdy_account_execution.codec import digest

VERSION = "native_settlement_confirmation_v2"


class SettlementConfirmation:
    def __init__(self, gateway, account_id, trading_day):
        self.gateway = gateway
        self.account_id = account_id
        self.trading_day = trading_day
        self.session = dict(gateway.native_session)
        self.front = gateway.front
        self.source_id = None
        self.queried = self.attempted = self.failed = False
        self.diagnostic = dict(schema=VERSION, status="NOT_CHECKED", trading_day=trading_day)
        self._identity()

    def _identity(self):
        if (
            self.gateway.failed
            or self.gateway.result.get("account_fingerprint") != self.account_id
            or self.gateway.result.get("trading_day") != self.trading_day
            or self.gateway.native_session != self.session
            or self.gateway.front != self.front
        ):
            self.failed = True
            self.diagnostic["status"] = "FAILED"
            raise ValueError("NATIVE_SETTLEMENT_IDENTITY_MISMATCH")

    def _query(self, kind):
        self._identity()
        self.diagnostic.update(kind=kind, status="QUERYING")
        for field in ("request_id", "confirm_date", "confirm_time"):
            self.diagnostic.pop(field, None)
        try:
            # The production Gateway verifies request ID, account, terminal
            # callback and SDK/response success before returning any rows.
            rows = self.gateway.query(kind)
            self._identity()
            if len(rows) > 1 or kind == "confirm" and len(rows) != 1:
                raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
            if not rows:
                self.diagnostic["status"] = "UNCONFIRMED"
                return None
            row = rows[0]
            date = row.get("ConfirmDate")
            time = row.get("ConfirmTime")
            if type(date) is not str or len(date) != 8 or not date.isascii() or not date.isdigit():
                raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
            datetime.strptime(date, "%Y%m%d")
            if time is not None:
                if type(time) is not str or len(time) != 8:
                    raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
                datetime.strptime(time, "%H:%M:%S")
            self.diagnostic.update(confirm_date=date, confirm_time=time)
            queries = getattr(self.gateway, "query_diagnostics", ())
            if queries and queries[-1].get("kind") == kind:
                request_id = queries[-1].get("request_id")
                if type(request_id) is int and request_id >= 0:
                    self.diagnostic["request_id"] = request_id
            return dict(confirm_date=date, confirm_time=time)
        except Exception:
            self.failed = True
            self.diagnostic["status"] = "FAILED"
            raise

    def _prove(self, kind, row):
        self.source_id = "native-settlement:v2:" + digest(dict(
            schema=VERSION, account_id=self.account_id, trading_day=self.trading_day,
            session=self.session, front=self.front, kind=kind, confirmation=row,
            request_id=self.diagnostic.get("request_id"),
        ))
        self.diagnostic["status"] = "CONFIRMED"

    def read_confirmed(self):
        self._identity()
        if self.failed:
            raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
        if self.queried:
            return self.source_id is not None
        self.queried = True
        row = self._query("settlement")
        # Retain the conservative existing-record shortcut. A civil-date
        # mismatch needs a current successful confirm, never an inferred match.
        if row and row["confirm_date"] == self.trading_day:
            self._prove("settlement", row)
        return self.source_id is not None

    def confirm(self):
        self._identity()
        if self.failed or not self.queried:
            raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
        if self.source_id is not None:
            return
        if self.attempted:
            raise ValueError("NATIVE_SETTLEMENT_CONFIRMATION_REQUIRED")
        self.attempted = True  # Unknown results cannot acquire a second attempt.
        row = self._query("confirm")
        self._prove("confirm", row)
