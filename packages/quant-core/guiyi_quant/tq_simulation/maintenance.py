"""Narrow recovery for the pinned SDK's terminal maintenance disconnect."""
from importlib.metadata import version
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .transport import DIRECT_HOSTS


class MaintenanceDisconnect(Exception):
    """The SDK connection task terminated, so update alone cannot recover it."""


def is_terminal_maintenance(error, now):
    if type(error) is not Exception or version("tqsdk") != "3.10.4":
        return False
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if local.hour != 19 or local.minute > 30:
        return False
    from tqsdk.connect import TqConnect

    trace = error.__traceback__
    if trace is None:
        return False
    while trace.tb_next:
        trace = trace.tb_next
    if trace.tb_frame.f_code is not TqConnect._run.__code__:
        return False
    values = trace.tb_frame.f_locals
    connection, url = values.get("self"), values.get("url")
    if type(connection) is not TqConnect or not isinstance(url, str):
        return False
    expected_host = dict(zip(("md", "td_0"), DIRECT_HOSTS)).get(connection._conn_id)
    try:
        parsed = urlsplit(url)
        valid = (expected_host is not None and parsed.scheme == "wss"
                 and parsed.hostname == expected_host and parsed.port in (None, 443)
                 and parsed.username is None and parsed.password is None)
    except ValueError:
        return False
    return (valid and connection._first_connect is True
            and values.get("in_ops_time") is True
            and error.args == (f"与 {url} 的连接失败，每日 19:00-19:30 为日常运维时间，请稍后再试",))


def resume_after(now):
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    return local.replace(hour=19, minute=31, second=0, microsecond=0).astimezone(now.tzinfo)


def require_settled(controller):
    """Never cold-close a client with an uncertain send/cancel/fill obligation."""
    if controller.store is None:
        raise ValueError("TQ_MAINTENANCE_ACCOUNT_UNPROVEN")
    state = controller.store.current()
    known = {o.order_id for o in state.orders if o.reconciled}
    claims = {row[0] for row in controller.journal.db.execute("SELECT order_id FROM claims")}
    if (any(not o.reconciled for o in state.orders) or state.unresolved_fill_ids
            or any(not r.released for r in state.reservations) or not claims <= known):
        raise ValueError("TQ_MAINTENANCE_OBLIGATIONS_PENDING")
