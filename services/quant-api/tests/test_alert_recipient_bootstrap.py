from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from app.alerts.clawbot import ClawbotContext
from app.alerts.recipient_bootstrap import (
    BootstrapConfirmResult,
    BootstrapPrepareResult,
    RecipientBootstrap,
    RecipientBootstrapError,
    RecipientRetireResult,
)


ACCOUNT_ID = "fixture-account"
OWNER_TARGET = "fixture-owner@im.wechat"
FRIEND_TARGET = "fixture-friend@im.wechat"
NOW = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


def _private_directory(tmp_path: Path, *, retired: tuple[str, ...] = ()) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    path = parent / "recipients.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "channel": "openclaw-weixin",
                "account_id": ACCOUNT_ID,
                "active_recipients": [
                    {"alias": "owner", "target_user_id": OWNER_TARGET}
                ],
                "retired_aliases": list(retired),
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


class SnapshotRunner:
    def __init__(self, snapshots: list[tuple[ClawbotContext, ...]]) -> None:
        self._snapshots = iter(snapshots)
        self.calls = 0

    def snapshot_contexts(self) -> tuple[str, tuple[ClawbotContext, ...]]:
        self.calls += 1
        return ACCOUNT_ID, next(self._snapshots)


def _bootstrap(
    path: Path,
    runner: SnapshotRunner,
    *,
    now: datetime = NOW,
) -> RecipientBootstrap:
    return RecipientBootstrap(
        runner,
        path,
        now=lambda: now,
        nonce_factory=lambda: b"n" * 32,
    )


def test_prepare_writes_one_exclusive_private_fingerprint_snapshot(tmp_path: Path) -> None:
    path = _private_directory(tmp_path)
    runner = SnapshotRunner(
        [
            (
                ClawbotContext(OWNER_TARGET, "fixture-owner-context"),
                ClawbotContext(FRIEND_TARGET, "fixture-friend-context"),
            )
        ]
    )
    bootstrap = _bootstrap(path, runner)

    result = bootstrap.prepare("alice")

    assert result == BootstrapPrepareResult(alias="alice", baseline_candidate_count=2)
    staging = path.with_name(".recipients.json.alice.staging")
    assert staging.stat().st_mode & 0o777 == 0o600
    payload = json.loads(staging.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "alias",
        "prepared_at",
        "expires_at",
        "nonce",
        "fingerprints",
    }
    assert payload["expires_at"] == (NOW + timedelta(minutes=10)).isoformat()
    serialized = json.dumps(payload)
    assert ACCOUNT_ID not in serialized
    assert OWNER_TARGET not in serialized
    assert FRIEND_TARGET not in serialized
    assert "fixture-owner-context" not in serialized
    assert "fixture-friend-context" not in serialized
    with pytest.raises(RecipientBootstrapError, match="^CLAWBOT_RECIPIENT_STAGING_EXISTS$"):
        bootstrap.prepare("alice")
    assert runner.calls == 1


def test_confirm_accepts_exactly_one_new_direct_candidate_and_removes_staging(
    tmp_path: Path,
) -> None:
    path = _private_directory(tmp_path)
    runner = SnapshotRunner(
        [
            (ClawbotContext(OWNER_TARGET, "owner-context"),),
            (
                ClawbotContext(FRIEND_TARGET, "friend-context"),
                ClawbotContext(OWNER_TARGET, "owner-context"),
            ),
        ]
    )
    bootstrap = _bootstrap(path, runner)
    bootstrap.prepare("alice")

    result = bootstrap.confirm("alice")

    assert result == BootstrapConfirmResult(alias="alice", candidate_count=1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["active_recipients"] == [
        {"alias": "owner", "target_user_id": OWNER_TARGET},
        {"alias": "alice", "target_user_id": FRIEND_TARGET},
    ]
    assert not path.with_name(".recipients.json.alice.staging").exists()


def test_confirm_treats_one_unbound_context_token_rotation_as_the_candidate(
    tmp_path: Path,
) -> None:
    path = _private_directory(tmp_path)
    runner = SnapshotRunner(
        [
            (
                ClawbotContext(FRIEND_TARGET, "old-context"),
                ClawbotContext(OWNER_TARGET, "owner-context"),
            ),
            (
                ClawbotContext(FRIEND_TARGET, "new-context"),
                ClawbotContext(OWNER_TARGET, "owner-context"),
            ),
        ]
    )
    bootstrap = _bootstrap(path, runner)
    bootstrap.prepare("alice")

    assert bootstrap.confirm("alice").candidate_count == 1
    assert json.loads(path.read_text(encoding="utf-8"))["active_recipients"][1] == {
        "alias": "alice",
        "target_user_id": FRIEND_TARGET,
    }


@pytest.mark.parametrize(
    ("current", "code"),
    [
        ((ClawbotContext(OWNER_TARGET, "owner-context"),), "CLAWBOT_RECIPIENT_CANDIDATE_INVALID"),
        (
            (
                ClawbotContext("a@im.wechat", "a-context"),
                ClawbotContext("b@im.wechat", "b-context"),
                ClawbotContext(OWNER_TARGET, "owner-context"),
            ),
            "CLAWBOT_RECIPIENT_CANDIDATE_INVALID",
        ),
        (
            (
                ClawbotContext(OWNER_TARGET, "changed-owner-context"),
            ),
            "CLAWBOT_RECIPIENT_TARGET_BOUND",
        ),
    ],
)
def test_confirm_failures_leave_recipients_unchanged(
    tmp_path: Path,
    current: tuple[ClawbotContext, ...],
    code: str,
) -> None:
    path = _private_directory(tmp_path)
    original = path.read_bytes()
    runner = SnapshotRunner(
        [(ClawbotContext(OWNER_TARGET, "owner-context"),), current]
    )
    bootstrap = _bootstrap(path, runner)
    bootstrap.prepare("alice")

    with pytest.raises(RecipientBootstrapError, match=f"^{code}$"):
        bootstrap.confirm("alice")

    assert path.read_bytes() == original


def test_expired_staging_fails_without_changing_recipients(tmp_path: Path) -> None:
    path = _private_directory(tmp_path)
    runner = SnapshotRunner(
        [
            (ClawbotContext(OWNER_TARGET, "owner-context"),),
            (
                ClawbotContext(FRIEND_TARGET, "friend-context"),
                ClawbotContext(OWNER_TARGET, "owner-context"),
            ),
        ]
    )
    _bootstrap(path, runner).prepare("alice")
    original = path.read_bytes()

    with pytest.raises(RecipientBootstrapError, match="^CLAWBOT_RECIPIENT_STAGING_EXPIRED$"):
        _bootstrap(path, runner, now=NOW + timedelta(minutes=11)).confirm("alice")
    assert path.read_bytes() == original


def test_confirm_rejects_staging_inode_replacement_during_snapshot(
    tmp_path: Path,
) -> None:
    path = _private_directory(tmp_path)
    staging = path.with_name(".recipients.json.alice.staging")

    class ReplacingRunner:
        calls = 0

        def snapshot_contexts(self) -> tuple[str, tuple[ClawbotContext, ...]]:
            self.calls += 1
            if self.calls == 2:
                replacement = staging.with_name("replacement.staging")
                replacement.write_bytes(staging.read_bytes())
                replacement.chmod(0o600)
                replacement.replace(staging)
                return ACCOUNT_ID, (
                    ClawbotContext(FRIEND_TARGET, "friend-context"),
                    ClawbotContext(OWNER_TARGET, "owner-context"),
                )
            return ACCOUNT_ID, (ClawbotContext(OWNER_TARGET, "owner-context"),)

    original = path.read_bytes()
    bootstrap = RecipientBootstrap(
        ReplacingRunner(),
        path,
        now=lambda: NOW,
        nonce_factory=lambda: b"n" * 32,
    )
    bootstrap.prepare("alice")

    with pytest.raises(RecipientBootstrapError, match="^CLAWBOT_RECIPIENT_STAGING_INVALID$"):
        bootstrap.confirm("alice")

    assert path.read_bytes() == original

    staging = path.with_name(".recipients.json.alice.staging")
    staging.write_text(staging.read_text(encoding="utf-8"), encoding="utf-8")
    staging.chmod(0o644)
    with pytest.raises(RecipientBootstrapError, match="^CLAWBOT_RECIPIENT_STAGING_INVALID$"):
        _bootstrap(path, SnapshotRunner([])).confirm("alice")
    assert path.read_bytes() == original


@pytest.mark.parametrize("alias", ["owner", "former_friend"])
def test_prepare_rejects_active_or_retired_alias(tmp_path: Path, alias: str) -> None:
    path = _private_directory(tmp_path, retired=("former_friend",))
    runner = SnapshotRunner([])

    with pytest.raises(RecipientBootstrapError, match="^CLAWBOT_RECIPIENT_ALIAS_UNAVAILABLE$"):
        _bootstrap(path, runner).prepare(alias)

    assert runner.calls == 0


def test_retire_removes_private_target_and_permanently_records_public_alias(
    tmp_path: Path,
) -> None:
    path = _private_directory(tmp_path)
    runner = SnapshotRunner(
        [
            (ClawbotContext(OWNER_TARGET, "owner-context"),),
            (
                ClawbotContext(FRIEND_TARGET, "friend-context"),
                ClawbotContext(OWNER_TARGET, "owner-context"),
            ),
        ]
    )
    bootstrap = _bootstrap(path, runner)
    bootstrap.prepare("alice")
    bootstrap.confirm("alice")

    result = bootstrap.retire("alice")

    assert result == RecipientRetireResult(alias="alice", active_recipient_count=1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["active_recipients"] == [
        {"alias": "owner", "target_user_id": OWNER_TARGET}
    ]
    assert payload["retired_aliases"] == ["alice"]
    assert FRIEND_TARGET not in path.read_text(encoding="utf-8")
    with pytest.raises(RecipientBootstrapError, match="^CLAWBOT_RECIPIENT_RETIRE_INVALID$"):
        bootstrap.retire("owner")
