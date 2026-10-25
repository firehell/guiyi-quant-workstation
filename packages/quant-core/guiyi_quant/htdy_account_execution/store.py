"""Private, account-serialized SQLite command journal; effects commit before return.

This is local offline persistence, not the production/PostgreSQL execution ledger
or a sender. Reopening requires native recovery before a new command can mutate.
"""

from dataclasses import dataclass, replace
from contextlib import contextmanager
import os
import json
from pathlib import Path
import sqlite3
import threading
from . import codec, model as m
from .reducer import apply, validate


class StoreError(ValueError):
    """Fixed public codes only; no SQL, paths, credentials or stack context."""


@dataclass(frozen=True)
class Commit:
    state: m.State
    effects: tuple[m.Effect, ...]
    sequence: int
    duplicate: bool


class LocalStore:
    def __init__(self, path, initial=None):
        self.path = Path(path)
        self._mutex = threading.RLock()
        self._uncertain = False
        self._needs_recovery = initial is None
        if initial is not None:
            validate(initial)
            if initial.orders or initial.fills or initial.reservations:
                raise StoreError("INITIAL_JOURNAL_MUST_HAVE_NO_ORDERS")
            fd = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            os.close(fd)
        elif (
            self.path.is_symlink()
            or not self.path.is_file()
            or self.path.stat().st_mode & 0o077
        ):
            raise StoreError("PRIVATE_LOCAL_STORE_REQUIRED")
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, timeout=5, check_same_thread=False
        )
        try:
            self._conn.execute("PRAGMA foreign_keys=ON")
            if initial is not None:
                self._initialize(initial)
            self._conn.execute("BEGIN")
            self._verify()
            self._conn.execute("ROLLBACK")
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            self._conn.close()
            raise StoreError("LOCAL_STORE_INVALID") from None

    def _initialize(self, state):
        self._conn.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE projection (id INTEGER PRIMARY KEY CHECK(id=1), sequence INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE commands (sequence INTEGER PRIMARY KEY, command_id TEXT NOT NULL UNIQUE,
          command_hash TEXT NOT NULL, command_payload TEXT NOT NULL, effects_payload TEXT NOT NULL,
          before_hash TEXT NOT NULL, after_hash TEXT NOT NULL,
          recovery_mode INTEGER NOT NULL CHECK(recovery_mode IN (0,1)));
        CREATE TRIGGER immutable_commands_update BEFORE UPDATE ON commands BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
        CREATE TRIGGER immutable_commands_delete BEFORE DELETE ON commands BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
        CREATE TRIGGER immutable_metadata_update BEFORE UPDATE ON metadata BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
        CREATE TRIGGER immutable_metadata_delete BEFORE DELETE ON metadata BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;
        COMMIT;
        """)
        self._conn.execute("BEGIN IMMEDIATE")
        self._conn.execute(
            "INSERT INTO metadata VALUES (?,?)",
            ("schema", "htdy_local_account_journal_v1"),
        )
        payload = codec.checkpoint(state)
        self._conn.execute("INSERT INTO metadata VALUES (?,?)", ("initial", payload))
        self._conn.execute("INSERT INTO projection VALUES (1,0,?)", (payload,))
        self._conn.execute("COMMIT")

    def close(self):
        with self._mutex:
            self._conn.close()

    def _projection(self):
        row = self._conn.execute(
            "SELECT sequence,payload FROM projection WHERE id=1"
        ).fetchone()
        if row is None:
            raise StoreError("PROJECTION_MISSING")
        sequence, payload = row
        state = codec.load(payload)
        tail = self._conn.execute(
            "SELECT sequence,after_hash FROM commands ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        initial_row = self._conn.execute(
            "SELECT value FROM metadata WHERE key=?", ("initial",)
        ).fetchone()
        baseline_count = len(codec.load(initial_row[0]).receipts) if initial_row else -1
        if (
            len(state.receipts) != sequence + baseline_count
            or (tail is None and sequence != 0)
            or tail is not None
            and tail != (sequence, codec.digest(state))
        ):
            raise StoreError("PROJECTION_JOURNAL_MISMATCH")
        return sequence, state

    def _verify(self):
        schema = self._conn.execute(
            "SELECT value FROM metadata WHERE key=?", ("schema",)
        ).fetchone()
        if schema != ("htdy_local_account_journal_v1",):
            raise StoreError("STORE_SCHEMA_INVALID")
        rebuilt = self.replay()
        _, current = self._projection()
        if rebuilt != current:
            raise StoreError("JOURNAL_REPLAY_MISMATCH")

    def current(self):
        with self._mutex:
            self._conn.execute("BEGIN")
            try:
                _, state = self._projection()
            finally:
                self._conn.execute("ROLLBACK")
            if self._needs_recovery:
                return replace(
                    state,
                    phase="BLOCKED"
                    if state.unresolved_fill_ids
                    else "RECOVERY_REQUIRED",
                    readback_valid=False,
                )
            return state

    @contextmanager
    def dispatch_guard(self):
        """Hold the account writer lock across bounded SDK request admission.

        Native callbacks must only stage facts in a separate journal until exit.
        No account mutation or automatic sending is performed here.
        """
        with self._mutex:
            if self._uncertain or self._needs_recovery:
                raise StoreError("NATIVE_RECOVERY_REQUIRED")
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                _, state = self._projection()
                yield state
            finally:
                self._conn.execute("ROLLBACK")

    def receipt(self, key):
        """Read-only inspection after uncertain commit; never returns sendable effects."""
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True
        )
        try:
            row = connection.execute(
                "SELECT sequence,command_hash FROM commands WHERE command_id=?", (key,)
            ).fetchone()
            return None if row is None else {"sequence": row[0], "command_hash": row[1]}
        finally:
            connection.close()

    def _commit(self):
        self._conn.execute("COMMIT")

    def execute(self, key, command, *, unsent_proof=None):
        m.text(key)
        with self._mutex:
            if self._uncertain:
                raise StoreError("COMMIT_OUTCOME_REQUIRES_READ_ONLY_CHECK")
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                sequence, state = self._projection()
                if (
                    self._conn.execute(
                        "SELECT value FROM metadata WHERE key=?", ("initial",)
                    ).fetchone()
                    is None
                ):
                    raise StoreError("INITIAL_STATE_MISSING")
                row = self._conn.execute(
                    "SELECT command_hash FROM commands WHERE command_id=?", (key,)
                ).fetchone()
                payload_hash = codec.digest(command)
                if row is not None:
                    if row[0] != payload_hash:
                        raise StoreError("COMMAND_IDENTITY_CONFLICT")
                    self._conn.execute("ROLLBACK")
                    if self._needs_recovery:
                        state = replace(
                            state,
                            phase="BLOCKED"
                            if state.unresolved_fill_ids
                            else "RECOVERY_REQUIRED",
                            readback_valid=False,
                        )
                    return Commit(state, (), sequence, True)
                if self._needs_recovery and type(command) not in (
                    m.Recover,
                    m.AbortUnsent,
                    m.Fill,
                    m.NativeFill,
                    m.Disconnect,
                    m.OrderUpdate,
                ):
                    raise StoreError("NATIVE_RECOVERY_REQUIRED")
                recovery_mode = int(
                    self._needs_recovery
                    and type(command)
                    in (
                        m.Fill,
                        m.NativeFill,
                        m.OrderUpdate,
                        m.Disconnect,
                        m.AbortUnsent,
                    )
                )
                execution_state = (
                    replace(
                        state,
                        phase="BLOCKED"
                        if state.unresolved_fill_ids
                        else "RECOVERY_REQUIRED",
                        readback_valid=False,
                    )
                    if recovery_mode
                    else state
                )
                if type(command) is m.AbortUnsent:
                    if unsent_proof is None or unsent_proof(state) is not True:
                        raise StoreError("ATOMIC_UNSENT_PROOF_REQUIRED")
                tx = apply(execution_state, key, command)
                next_sequence = sequence + 1
                self._conn.execute(
                    "INSERT INTO commands VALUES (?,?,?,?,?,?,?,?)",
                    (
                        next_sequence,
                        key,
                        payload_hash,
                        codec.json_text(codec.encode(command)),
                        codec.json_text(codec.encode(tx.effects)),
                        codec.digest(state),
                        codec.digest(tx.state),
                        recovery_mode,
                    ),
                )
                self._conn.execute(
                    "UPDATE projection SET sequence=?,payload=? WHERE id=1",
                    (next_sequence, codec.checkpoint(tx.state)),
                )
            except sqlite3.Error:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise StoreError("LOCAL_TRANSACTION_FAILED") from None
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            try:
                self._commit()
            except (sqlite3.Error, OSError):
                self._uncertain = True
                self._conn.close()
                raise StoreError("COMMIT_OUTCOME_UNKNOWN") from None
            if type(command) is m.Recover:
                self._needs_recovery = (
                    not tx.state.readback_valid or tx.state.phase != "READY"
                )
            return Commit(tx.state, tx.effects, next_sequence, False)

    def replay(self):
        """Rebuild and compare every accepted command/effect/hash, without side effects."""
        with self._mutex:
            row = self._conn.execute(
                "SELECT value FROM metadata WHERE key=?", ("initial",)
            ).fetchone()
            if row is None:
                raise StoreError("INITIAL_STATE_MISSING")
            state = codec.load(row[0])
            for expected_sequence, row in enumerate(
                self._conn.execute(
                    "SELECT sequence,command_id,command_hash,command_payload,effects_payload,before_hash,after_hash,recovery_mode FROM commands ORDER BY sequence"
                ),
                1,
            ):
                (
                    sequence,
                    key,
                    command_hash,
                    payload,
                    effects,
                    before,
                    after,
                    recovery_mode,
                ) = row
                command = codec.decode(json.loads(payload))
                if (
                    sequence != expected_sequence
                    or codec.digest(command) != command_hash
                    or codec.digest(state) != before
                ):
                    raise StoreError("JOURNAL_CHAIN_INVALID")
                if (
                    recovery_mode not in (0, 1)
                    or recovery_mode
                    and type(command)
                    not in (
                        m.Fill,
                        m.NativeFill,
                        m.OrderUpdate,
                        m.Disconnect,
                        m.AbortUnsent,
                    )
                ):
                    raise StoreError("JOURNAL_RECOVERY_MODE_INVALID")
                execution_state = (
                    replace(
                        state,
                        phase="BLOCKED"
                        if state.unresolved_fill_ids
                        else "RECOVERY_REQUIRED",
                        readback_valid=False,
                    )
                    if recovery_mode
                    else state
                )
                tx = apply(execution_state, key, command)
                if (
                    codec.json_text(codec.encode(tx.effects)) != effects
                    or codec.digest(tx.state) != after
                ):
                    raise StoreError("JOURNAL_RESULT_INVALID")
                state = tx.state
            return state
