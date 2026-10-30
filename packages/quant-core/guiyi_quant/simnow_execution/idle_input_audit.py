"""One native query stage per idle turn; no connection or execution permission."""

from datetime import timedelta
import re
from .input_evidence import VERSION

# Existing Gateway.query: 1.1 seconds pacing + 15 seconds terminal wait.
# Reserve an additional 3.9 seconds before the earliest natural decision boundary.
AUDIT_STAGE_RESERVE_SECONDS = 20


class IdleInputAudit:
    def __init__(self):
        self.cursor = 0
        self.pending = None
        self.scope = None
        self.day = None

    def next(
        self, native, products, market, day, *, idle, obligations_pending, next_boundary
    ):
        products = tuple(products)
        if (
            not products
            or len(products) > 60
            or len(set(products)) != len(products)
            or any(
                not isinstance(p, str) or re.fullmatch(r"[A-Z]{1,3}", p) is None
                for p in products
            )
        ):
            raise ValueError("AUDIT_SCOPE_INVALID")
        now = native.now()
        gateway = native.gateway
        login_done = getattr(gateway, "login_done", None)
        connected = (
            gateway is not None
            and not gateway.failed
            and login_done is not None
            and login_done.is_set()
            and not native.transport_failed
        )
        try:
            window = now < next_boundary - timedelta(
                seconds=AUDIT_STAGE_RESERVE_SECONDS
            )
        except (TypeError, ValueError):
            window = False
        if (
            idle is not True
            or obligations_pending is not False
            or not connected
            or not window
        ):
            self.pending = None
            return dict(status="DEFERRED", purpose="audit", execution_permitted=False)
        if self.scope != products or self.day != day:
            self.pending = None
            self.scope, self.day, self.cursor = products, day, 0
        if self.pending is None:
            product = products[self.cursor % len(products)]
            self.cursor += 1
            self.pending = dict(product=product, stage="instrument")
            native.book_diagnostic = {}
            native.stage = "AUDIT_INPUT"
            native.input_checks[product] = dict(
                schema=VERSION,
                status="AUDIT_PENDING",
                purpose="audit",
                checked_at=now.isoformat(),
                qualification="FACTS_ONLY_NOT_ORDER_PERMISSION",
            )
        item = self.pending
        product = item["product"]
        try:
            stage = item["stage"]
            if stage == "instrument":
                item["bound"], item["metadata"] = native.binding(
                    product, None, market, now, day
                )
                item["stage"] = "margin"
            elif stage in {"margin", "commission"}:
                native.stage = "NATIVE_" + stage.upper()
                bound = item["bound"]
                if not bound.at <= native.now() < bound.valid_until:
                    raise ValueError("AUDIT_BINDING_EXPIRED")
                rows = gateway.query(stage, bound.native, exchange=bound.exchange)
                if len(rows) != 1:
                    raise ValueError("NATIVE_RATE_FACTS_INCOMPLETE")
                item[stage] = rows[0]
                native.rate_times.setdefault(bound.canonical, {})[stage] = (
                    native.now().isoformat()
                )
                item["stage"] = "commission" if stage == "margin" else "book"
            else:
                if not item["bound"].at <= native.now() < item["bound"].valid_until:
                    raise ValueError("AUDIT_BINDING_EXPIRED")
                native.finish_facts(
                    (
                        item["bound"],
                        item["metadata"],
                        item["margin"],
                        item["commission"],
                    ),
                    market,
                    day,
                    opening=True,
                    purpose="audit",
                )
            if native.now() >= next_boundary:
                raise ValueError("AUDIT_WINDOW_ELAPSED")
            if (
                gateway.failed
                or not gateway.login_done.is_set()
                or native.transport_failed
            ):
                raise ValueError("NATIVE_GATEWAY_FAILED")
            if stage == "book":
                self.pending = None
                return dict(
                    status="CHECKED",
                    product=product,
                    purpose="audit",
                    execution_permitted=False,
                )
        except Exception as exc:
            native._input_failure(product, exc, purpose="audit")
            self.pending = None
            return dict(
                status="FAILED",
                product=product,
                purpose="audit",
                execution_permitted=False,
            )
        return dict(
            status="IN_PROGRESS",
            product=product,
            stage=item["stage"],
            purpose="audit",
            execution_permitted=False,
        )
