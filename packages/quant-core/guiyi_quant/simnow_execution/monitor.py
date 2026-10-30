"""Atomic observer index and strictly read-only journal reader. Never broker I/O."""

from contextlib import contextmanager
from pathlib import Path
import json
import os
import re
import sqlite3
import tempfile
from ..htdy_account_execution import codec
from .inventory import Snapshot, at, native_hash

VERSION = "simnow_monitor_v1"
MAX_FILE = 64 * 1024 * 1024


class MonitorError(ValueError):
    pass


class MonitorPublisher:
    def __init__(self, root, account_id, run_id, product=None):
        self.root = Path(root)
        self.account_id = account_id
        self.run_id = run_id
        self.product = product
        self.failed = False

    def publish(
        self,
        status,
        now,
        *,
        connection="UNKNOWN",
        native_source_id=None,
        ledger_hash=None,
        mode=None,
        opening_enabled=False,
        host_status=None,
        observe_reconciliation=None,
        account_takeover_pending=False,
    ):
        """Best effort observer only. Never change order decisions on publication error."""
        target = None
        lock_fd = None
        try:
            if (
                re.fullmatch(r"[a-f0-9]{64}", self.account_id) is None
                or status not in ("STARTING", "READING", "ACTIVE", "STOPPED", "ERROR")
                or connection
                not in ("UNKNOWN", "LOGGED_IN", "DISCONNECTED", "RELEASED")
            ):
                raise MonitorError("MONITOR_INDEX_INVALID")
            if now.tzinfo is None or self.root.is_symlink():
                raise MonitorError("MONITOR_ROOT_INVALID")
            if (
                mode is not None
                and mode not in ("observe", "manage", "trade")
                or type(account_takeover_pending) is not bool
                or (account_takeover_pending and opening_enabled)
                or type(opening_enabled) is not bool
                or opening_enabled
                and mode != "trade"
                or host_status is not None
                and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", host_status) is None
            ):
                raise MonitorError("MONITOR_INDEX_INVALID")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.root.stat().st_mode & 0o077:
                raise MonitorError("MONITOR_ROOT_NOT_PRIVATE")
            import fcntl

            lock_fd = os.open(
                self.root / ".monitor.lock",
                os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            dest = self.root / "monitor.json"
            if dest.is_symlink():
                raise MonitorError("MONITOR_INDEX_INVALID")
            if dest.exists():
                prior = _index(self.root)
                if prior["account_id"] != self.account_id:
                    raise MonitorError("MONITOR_ACCOUNT_CONFLICT")
                if native_source_id is None or ledger_hash is None:
                    # Retain a pair; never combine a new source with an unrelated
                    # old ledger hash. Current run/connection status is separate.
                    native_source_id = prior.get("native_source_id")
                    ledger_hash = prior.get("ledger_hash")
            payload = dict(
                version=VERSION,
                account_id=self.account_id,
                run_id=self.run_id,
                status=status,
                published_at=now.isoformat(),
                connection=connection,
                product=self.product,
                native_source_id=native_source_id,
                ledger_hash=ledger_hash,
            )
            if mode is not None:
                payload.update(
                    mode=mode,
                    opening_enabled=opening_enabled,
                    host_status=host_status,
                    account_takeover_pending=account_takeover_pending,
                )
            if observe_reconciliation is not None:
                proof = observe_reconciliation
                if (
                    mode != "observe"
                    or not isinstance(proof, dict)
                    or proof.get("run_id") != self.run_id
                    or proof.get("account_id") != self.account_id
                    or proof.get("native_source_id") != native_source_id
                    or proof.get("ledger_hash") != ledger_hash
                ):
                    raise MonitorError("MONITOR_OBSERVE_BINDING_INVALID")
                payload["observe_reconciliation"] = proof
            fd, target = tempfile.mkstemp(prefix=".monitor-", dir=self.root)
            with os.fdopen(fd, "w") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(target, dest)
            target = None
            return True
        except Exception:
            self.failed = True
            return False
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            if target is not None:
                try:
                    os.unlink(target)
                except OSError:
                    pass


def _private(path):
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_mode & 0o077
        or path.stat().st_size > MAX_FILE
    ):
        raise MonitorError("MONITOR_SOURCE_INVALID")


def _index(root):
    if root.is_symlink():
        raise MonitorError("MONITOR_ROOT_INVALID")
    path = root / "monitor.json"
    _private(path)
    value = json.loads(path.read_text())
    if (
        value.get("version") != VERSION
        or re.fullmatch(r"[a-f0-9]{64}", value.get("account_id", "")) is None
    ):
        raise MonitorError("MONITOR_INDEX_INVALID")
    if value.get("status") not in (
        "STARTING",
        "READING",
        "ACTIVE",
        "STOPPED",
        "ERROR",
    ) or value.get("connection") not in (
        "UNKNOWN",
        "LOGGED_IN",
        "DISCONNECTED",
        "RELEASED",
    ):
        raise MonitorError("MONITOR_INDEX_INVALID")
    at(value["published_at"])
    if "mode" in value and (
        value["mode"] not in ("observe", "manage", "trade")
        or type(value.get("account_takeover_pending", False)) is not bool
        or (
            value.get("account_takeover_pending", False)
            and value.get("opening_enabled")
        )
        or type(value.get("opening_enabled")) is not bool
        or value["opening_enabled"]
        and value["mode"] != "trade"
        or value.get("host_status") is not None
        and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", str(value["host_status"])) is None
    ):
        raise MonitorError("MONITOR_INDEX_INVALID")
    return value


@contextmanager
def _ro(path):
    _private(path)
    # These execution journals use rollback journaling. Refuse WAL before opening:
    # SQLite mode=ro can otherwise create a missing shared-memory sidecar.
    with path.open("rb") as stream:
        header = stream.read(20)
    if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
        raise MonitorError("MONITOR_JOURNAL_MODE_UNSUPPORTED")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


def _snapshot(payload, source, account):
    value = json.loads(payload)
    snapshot = Snapshot(
        value["account_id"],
        value["trading_day"],
        at(value["started_at"]),
        at(value["at"]),
        value["source_id"],
        value["payload_json"],
    )
    expected = (
        "ctp-inventory:"
        + snapshot.trading_day
        + ":"
        + native_hash(
            (account, snapshot.trading_day, snapshot.data, snapshot.at.isoformat())
        )
    )
    if (
        snapshot.account_id != account
        or snapshot.source_id != source
        or source != expected
        or snapshot.started_at > snapshot.at
    ):
        raise MonitorError("MONITOR_NATIVE_IDENTITY_INVALID")
    return snapshot


class MonitorReader:
    def __init__(self, root, *, expected_account_id=None):
        self.root = Path(root)
        self.expected_account_id = expected_account_id

    def load(self, now):
        if self.root.is_symlink() or (self.root / "monitor.json").is_symlink():
            raise MonitorError("MONITOR_ROOT_INVALID")
        if not (self.root / "monitor.json").exists():
            return None
        index = _index(self.root)
        if (
            self.expected_account_id is not None
            and index["account_id"] != self.expected_account_id
        ):
            raise MonitorError("MONITOR_ACCOUNT_BINDING_MISMATCH")
        if at(index["published_at"]) > now:
            raise MonitorError("MONITOR_FUTURE_INDEX")
        if (
            not isinstance(index.get("native_source_id"), str)
            or re.fullmatch(
                r"ctp-inventory:\d{8}:[a-f0-9]{64}", index["native_source_id"]
            )
            is None
            or not isinstance(index.get("ledger_hash"), str)
            or re.fullmatch(r"[a-f0-9]{64}", index["ledger_hash"]) is None
        ):
            raise MonitorError("MONITOR_SOURCE_BINDING_REQUIRED")
        account = index["account_id"]
        folder = self.root / account
        if folder.is_symlink() or not folder.is_dir() or folder.stat().st_mode & 0o077:
            raise MonitorError("MONITOR_ACCOUNT_ROOT_INVALID")
        with _ro(folder / "account.sqlite") as db:
            if db.execute(
                "SELECT value FROM metadata WHERE key='schema'"
            ).fetchone() != ("htdy_local_account_journal_v1",):
                raise MonitorError("MONITOR_LEDGER_SCHEMA_INVALID")
            sequence, payload = db.execute(
                "SELECT sequence,payload FROM projection WHERE id=1"
            ).fetchone()
            state = codec.load(payload)
            initial = db.execute(
                "SELECT value FROM metadata WHERE key='initial'"
            ).fetchone()
            tail = db.execute(
                "SELECT sequence,after_hash FROM commands ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if (
                state.account_id != account
                or len(state.receipts)
                != sequence + len(codec.load(initial[0]).receipts)
                or (tail is None and sequence != 0)
                or tail is not None
                and tail != (sequence, codec.digest(state))
            ):
                raise MonitorError("MONITOR_LEDGER_IDENTITY_INVALID")
            if (
                index["ledger_hash"] != codec.digest(codec.load(initial[0]))
                and db.execute(
                    "SELECT 1 FROM commands WHERE after_hash=? LIMIT 1",
                    (index["ledger_hash"],),
                ).fetchone()
                is None
            ):
                raise MonitorError("MONITOR_LEDGER_BINDING_INVALID")
        with _ro(folder / "dispatch.sqlite") as db:
            if db.execute("SELECT account,schema FROM identity").fetchall() != [
                (account, "simnow_dispatch_v1")
            ]:
                raise MonitorError("MONITOR_DISPATCH_IDENTITY_INVALID")
            actions = []
            for order, kind, payload, intent in db.execute(
                "SELECT order_id,kind,payload,intent FROM actions ORDER BY id"
            ):
                raw = json.loads(payload)
                if raw.get("account_id") != account:
                    raise MonitorError("MONITOR_DISPATCH_IDENTITY_INVALID")
                actions.append(dict(order_id=order, kind=kind, payload=raw))
            rows = db.execute(
                "SELECT rowid,event_id,payload,received_at FROM events ORDER BY rowid DESC LIMIT 10001"
            ).fetchall()
            events = [
                (event, json.loads(payload), at(observed))
                for _, event, payload, observed in reversed(rows[:10000])
            ]
            event_revision = rows[0][0] if rows else 0
            truncated = len(rows) > 10000
        with _ro(folder / "native-evidence.sqlite") as db:
            if db.execute("SELECT account FROM owner").fetchall() != [(account,)]:
                raise MonitorError("MONITOR_NATIVE_IDENTITY_INVALID")
            bound = db.execute(
                "SELECT rowid FROM snapshots WHERE source=?",
                (index["native_source_id"],),
            ).fetchone()
            if bound is None:
                raise MonitorError("MONITOR_NATIVE_BINDING_INVALID")
            first = db.execute(
                "SELECT source,payload FROM snapshots ORDER BY rowid LIMIT 1"
            ).fetchone()
            rows = db.execute(
                "SELECT source,payload FROM snapshots WHERE rowid<=? ORDER BY rowid DESC LIMIT 5001",
                (bound[0],),
            ).fetchall()
            snapshots = [
                _snapshot(payload, source, account)
                for source, payload in reversed(rows[:5000])
            ]
            baseline = _snapshot(first[1], first[0], account) if first else None
            latest_native = db.execute(
                "SELECT source FROM snapshots ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if index.get("observe_reconciliation") is not None and latest_native != (
                index["native_source_id"],
            ):
                raise MonitorError("MONITOR_OBSERVE_SOURCE_CHANGED")
            truncated = truncated or len(rows) > 5000
        if not snapshots or baseline is None:
            raise MonitorError("MONITOR_NATIVE_MISSING")
        if any(s.at > now for s in snapshots):
            raise MonitorError("MONITOR_FUTURE_NATIVE")
        from .observe_reconciliation import verify_proof

        try:
            observe_reconciliation = verify_proof(
                index.get("observe_reconciliation"), index, state, snapshots[-1], now
            )
        except (ValueError, TypeError, KeyError):
            raise MonitorError("MONITOR_OBSERVE_PROOF_INVALID") from None
        revision = codec.digest(
            (
                account,
                sequence,
                codec.digest(state),
                snapshots[-1].source_id,
                event_revision,
            )
        )
        return dict(
            index=index,
            state=state,
            observe_reconciliation=observe_reconciliation,
            actions=actions,
            events=events,
            snapshots=snapshots,
            baseline=baseline,
            snapshot=revision,
            truncated=truncated,
        )

    def overview(self, now):
        from .monitor_projection import overview

        try:
            data = self.load(now)
            return overview(data, now)
        except Exception:
            if self.expected_account_id is not None:
                raise MonitorError("MONITOR_SOURCE_UNAVAILABLE") from None
            return overview(None, now, error=True)

    def records(
        self,
        now,
        *,
        kind="all",
        product="",
        status="",
        start_day=None,
        end_day=None,
        cursor=None,
    ):
        from .monitor_projection import records_page

        try:
            data = self.load(now)
        except Exception:
            raise MonitorError("MONITOR_SOURCE_UNAVAILABLE") from None
        return records_page(data, kind, product, status, start_day, end_day, cursor)

    def detail(self, now, identity):
        from .monitor_projection import detail

        try:
            data = self.load(now)
        except Exception:
            raise MonitorError("MONITOR_SOURCE_UNAVAILABLE") from None
        return detail(data, identity)
