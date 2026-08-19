# Alert Fixed Recipients Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单 `owner` 的 Clawbot 微信直聊通知扩展为最多 5 个固定接收人：HTDY 通知全部 active aliases，SuBing 仍只通知 `owner`，并以逐 Event、逐 alias 的持久化 Attempt 保持 at-most-once。

**Architecture:** 在 Alert Application Domain 中新增 additive `alert_notification_attempts` 表和 `AlertDeliveryCoordinator`；Git 外 v2 recipients 文件在 Alert Runtime 构造时一次性验证并冻结，外部发送前先提交 `STARTED` Attempt。Node single-shot seam 仍每次只处理一个 direct recipient、最多调用一次 `sendMessageWeixin()`，失败不 retry、queue、replay、backfill 或 fallback。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy 2、PostgreSQL、Alembic、Node.js、pinned `openclaw-weixin 2.4.6`、pytest、Node test、launchd shell/plist validation。

**Spec:** `docs/superpowers/specs/2026-08-19-alert-fixed-recipients-design.md`

## Global Constraints

- 实施基线为 `develop`；开始前重新确认 branch、HEAD、dirty state、`STATUS.md` 与本 Spec，保留所有无关用户修改。
- Tasks 1–8 只允许仓库代码、测试和文档变更；不得执行 production migration、私有 recipients 写入、bootstrap、canary、真实通知、Scope mutation、release/tag、Runtime promotion 或订单操作。
- active transport 仍精确为 `clawbot-openclaw-weixin`；不得恢复 WeCom、Courier、public OpenClaw message-send 或 provider fallback。
- `htdy_original_15m -> all active aliases`；`subing_entry_signal_v1 -> owner only`。未知 Rule fail-closed，未来 Rule 不继承接收人。
- active recipient count 必须为 `1..5` 且包含唯一 `owner`；发送顺序固定为 `owner` 优先、其余 alias 字典序。
- active alias 与 target 的绑定不可原地修改。换人必须停用旧 alias，并以从未使用的新 alias 重新 bootstrap；retired alias 永久不可复用。
- v2 recipients 文件只在 Alert Runtime 构造时加载一次并冻结；运行中不热重载。任何新增、停用或换配置只有在新的精确 Runtime switch Gate 后才影响新 Event。
- v2 首次建档必须由专用 init 命令从已验证的 v1 owner 文件原子复制 owner 身份；若 v2 已存在则 fail-closed，不删除或改写 v1 文件，不输出私有 ID。
- bootstrap 每个 alias 只允许一个未过期 staging；prepare 使用 exclusive create，confirm 必须对同一安全打开的 staging 做 lstat/fstat 一致性校验，任何并发替换都 fail-closed。
- recipients、staging 与 v1 owner 的 parent 必须是 `0700/current uid/real directory/no symlink`；文件必须是 `0600/current uid/regular file/O_NOFOLLOW`。
- PostgreSQL 只保存公开 alias、channel、状态、时间和稳定错误码；不得保存 account ID、target ID、token/context、正文、姓名、手机号、私有路径、SQL 或 stack trace。
- Event 必须先 commit；每个 recipient 的 `STARTED` Attempt 必须再独立 commit，之后才允许启动一个 Node child 和一次 provider primitive。
- `STARTED` 的只读投影为 `UNKNOWN`，不得自动判断、恢复或重发。一个 recipient 的正常失败不阻塞后续 recipient；进程级崩溃不恢复剩余投递。
- `alert_events.notification_attempted_at` 保留为 legacy DB/API 字段。新 Runtime 不写它；新投递状态只从 `alert_notification_attempts` 的只读 read model/CLI 获取，不把 legacy NULL 解释成“未发生 Attempt”。
- canary 必须精确选择单个 alias，一次命令最多一条消息；canary 不创建 Event/Attempt，不进入连续授权。
- HTDY 文本增加精确 footer `研究观察，非交易指令`；SuBing 文本与路由零变化；`auto_order=false` 始终成立。
- 每个 Task 采用 RED→GREEN、定向测试、diff/secret 自检和单一职责 commit；完整验证与独立 Review 只在 Task 8 一次性执行。

---

## File Structure

### Create

- `services/quant-api/alembic/versions/20260819_0040_alert_notification_attempts.py` — additive Attempt 表、约束与索引。
- `services/quant-api/app/alerts/recipients.py` — v2 recipients schema、安全 I/O、路由和 v1→v2 首次建档。
- `services/quant-api/app/alerts/recipient_bootstrap.py` — fingerprint staging、prepare/confirm、停用操作。
- `services/quant-api/app/alerts/delivery.py` — Attempt repository、read model 与 `AlertDeliveryCoordinator`。
- `services/quant-api/tests/alembic/test_alert_notification_attempts_migration.py` — isolated PostgreSQL migration 证据。
- `services/quant-api/tests/test_alert_recipients.py` — v2 配置、路由、init 和停用合同。
- `services/quant-api/tests/test_alert_recipient_bootstrap.py` — prepare/confirm 和并发替换合同。
- `services/quant-api/tests/test_alert_delivery.py` — Attempt 状态机、去重和故障隔离。

### Modify

- `services/quant-api/app/alerts/models.py` — 新增 `AlertNotificationAttempt` ORM 与 relationship。
- `services/quant-api/app/models/__init__.py` — 导入新 ORM，保持 migration/model guard 可见。
- `services/quant-api/app/alerts/service.py` — `AlertEventCreate` 不再要求/写入 legacy timestamp。
- `services/quant-api/app/alerts/runtime.py` — Event commit 后调用 coordinator，不再直接调用 sender。
- `services/quant-api/app/alerts/composition.py` — Runtime 启动时冻结 RecipientDirectory，并注入 coordinator。
- `services/quant-api/app/alerts/clawbot.py` — runner 接受 `ClawbotRecipient`；单 alias canary/preflight。
- `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs` — direct target probe/send 与 bootstrap context snapshot action。
- `services/quant-api/app/alerts/notification.py` — 只修改 HTDY footer，SuBing formatter 保持不变。
- `services/quant-api/app/guiyi_cli/main.py` — recipients init/bootstrap/retire/preflight/canary/status 命令。
- `services/quant-api/app/services/runtime_health.py` — 公开接收人数与 ready 人数，不公开 alias/ID/path。
- `services/quant-api/app/schemas/runtime.py` — 为现有 typed health surface 增加接收人数与 transport 字段。
- `deploy/launchd/com.guiyi.quant-api.plist.template`、`deploy/launchd/com.guiyi.quant-alert.plist.template` — owner path 替换为 recipients path。
- `scripts/ops/macos/run-local-service.sh`、`scripts/ops/macos/install-local-services.sh`、`scripts/ops/macos/local-services-status.sh` — 精确 v2 环境变量和只读身份检查。
- `services/quant-api/tests/test_alert_models.py`
- `services/quant-api/tests/test_alert_service.py`
- `services/quant-api/tests/test_alert_runtime.py`
- `services/quant-api/tests/test_alert_clawbot.py`
- `services/quant-api/tests/test_alert_notification.py`
- `services/quant-api/tests/test_alert_cli.py`
- `services/quant-api/tests/test_runtime_health.py`
- `services/quant-api/tests/test_migration_test_guard.py`
- `tests/engineering/openclaw_weixin_single_shot.test.mjs`
- `tests/engineering/test_alert_runtime_launchd.py`、`tests/engineering/test_market_runtime_launchd.py` — 更新 v2 path assertions。
- `TESTING.md`、`AGENTS.md` — 同步 canonical、命令和外部 Gate 边界。
- `STATUS.md` — 仅在 Task 8 全量验证与独立 Review 通过后记录真实 code/test 状态。

---

### Task 1: Additive Attempt Model and Migration

**Files:**
- Create: `services/quant-api/alembic/versions/20260819_0040_alert_notification_attempts.py`
- Create: `services/quant-api/tests/alembic/test_alert_notification_attempts_migration.py`
- Modify: `services/quant-api/app/alerts/models.py`
- Modify: `services/quant-api/app/models/__init__.py`
- Modify: `services/quant-api/tests/test_alert_models.py`
- Modify: `services/quant-api/tests/test_migration_test_guard.py`

**Interfaces:**
- Produces ORM `AlertNotificationAttempt` with statuses `STARTED`, `PROVIDER_ACCEPTED`, `FAILED`.
- Produces unique identity `(event_id, recipient_alias, channel)` consumed by Task 4.

- [ ] **Step 1: Write model RED tests**

Add assertions for exact columns, timezone-aware timestamps, `String(32)` alias, `String(64)` channel/error, relationship, unique/check constraints and both indexes:

```python
assert set(AlertNotificationAttempt.__table__.c) == {
    "id", "event_id", "recipient_alias", "channel", "status",
    "attempted_at", "completed_at", "error_code", "created_at", "updated_at",
}
assert AlertNotificationAttempt.__table__.c.event_id.nullable is False
assert {item.name for item in AlertNotificationAttempt.__table__.constraints} >= {
    "uq_alert_notification_attempts_event_alias_channel",
    "ck_alert_notification_attempts_status",
    "ck_alert_notification_attempts_completion",
}
```

- [ ] **Step 2: Run model tests and confirm RED**

Run:

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_models.py
```

Expected: collection/import failure because `AlertNotificationAttempt` does not exist.

- [ ] **Step 3: Implement ORM and relationships**

Use this public shape:

```python
class AlertNotificationAttempt(Base):
    __tablename__ = "alert_notification_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("alert_events.id"), nullable=False)
    recipient_alias: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
```

Define one three-branch completion check exactly matching the Spec and add `AlertEvent.notification_attempts` with `back_populates`.

- [ ] **Step 4: Write migration RED tests**

Test upgrade from `20260815_0039` to head in an isolated PostgreSQL DB and assert:

```python
assert revision == "20260819_0040"
assert down_revision == "20260815_0039"
assert "alert_notification_attempts" in inspector.get_table_names()
assert "notification_attempted_at" in {c["name"] for c in inspector.get_columns("alert_events")}
```

Insert legal STARTED/accepted/failed rows; assert illegal status/completion combinations and duplicate identities raise `IntegrityError`. Assert no backfill rows are created for existing Events.

- [ ] **Step 5: Implement additive migration**

Create only the new table, FK, constraints and indexes. `downgrade()` drops the new table only; it must not modify either existing Alert table.

- [ ] **Step 6: Run Task 1 GREEN tests**

Run:

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/alembic/test_alert_notification_attempts_migration.py \
  services/quant-api/tests/test_migration_test_guard.py
```

Expected: all selected tests pass against an isolated PostgreSQL identity.

- [ ] **Step 7: Commit Task 1**

```bash
git add services/quant-api/alembic/versions/20260819_0040_alert_notification_attempts.py services/quant-api/app/alerts/models.py services/quant-api/app/models/__init__.py services/quant-api/tests/alembic/test_alert_notification_attempts_migration.py services/quant-api/tests/test_alert_models.py services/quant-api/tests/test_migration_test_guard.py
git commit -m "feat(alert): add recipient attempt ledger"
```

---

### Task 2: Frozen v2 Recipient Directory and Safe Initialisation

**Files:**
- Create: `services/quant-api/app/alerts/recipients.py`
- Create: `services/quant-api/tests/test_alert_recipients.py`
- Modify: `services/quant-api/app/alerts/clawbot.py`
- Modify: `services/quant-api/tests/test_alert_clawbot.py`

**Interfaces:**
- Produces `ClawbotRecipient(alias, account_id, target_user_id)` and immutable `RecipientDirectory`.
- Produces `load_recipient_directory(path)` and `initialize_recipients_from_owner(owner_path, recipients_path)`.

- [ ] **Step 1: Write recipient schema RED tests**

Cover exact keys, `schema_version == 2`, channel, one shared account, owner required, alias regex, direct target suffix, duplicate alias/target, `1..5`, retired collision/reuse, extra fields, invalid modes/uid/symlink and secret-safe errors.

Representative contract:

```python
directory = load_recipient_directory(path)
assert directory.aliases == ("owner", "alice", "bob")
assert [item.alias for item in directory.recipients_for("htdy_original_15m")] == [
    "owner", "alice", "bob",
]
assert [item.alias for item in directory.recipients_for("subing_entry_signal_v1")] == ["owner"]
```

Assert unknown Rule raises public `CLAWBOT_RECIPIENT_RULE_INVALID` and errors never contain fixture IDs or paths.

- [ ] **Step 2: Run recipient tests and confirm RED**

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_alert_recipients.py
```

Expected: import failure because `app.alerts.recipients` does not exist.

- [ ] **Step 3: Implement strict immutable models and loader**

Use frozen dataclasses and exact routing:

```python
@dataclass(frozen=True, slots=True)
class ClawbotRecipient:
    alias: str
    account_id: str
    target_user_id: str

class RecipientDirectory:
    def recipients_for(self, rule_code: str) -> tuple[ClawbotRecipient, ...]:
        if rule_code == "htdy_original_15m":
            return self._recipients
        if rule_code == "subing_entry_signal_v1":
            return (self._owner,)
        raise ClawbotRecipientError("CLAWBOT_RECIPIENT_RULE_INVALID")
```

Load once through `lstat -> os.open(O_RDONLY|O_NOFOLLOW) -> fstat`, validate exact inode/type/mode/uid, and return an immutable tuple ordered owner-first then alias.

- [ ] **Step 4: Write v1→v2 init RED tests**

Assert init:

- reads a valid v1 owner with the existing safe loader;
- creates exact v2 JSON atomically with only owner active;
- fsyncs file and parent, then reloads v2;
- refuses if v2 exists, parent/file is unsafe, or v1 is invalid;
- never deletes/modifies v1 and never returns/logs IDs.

Expected payload from the command layer in Task 3:

```python
{
    "channel": "openclaw-weixin",
    "recipient_count": 1,
    "active_aliases": ["owner"],
    "recipients_written": True,
}
```

- [ ] **Step 5: Implement atomic initializer**

Write `schema_version`, `channel`, shared `account_id`, owner-only `active_recipients`, and empty `retired_aliases` to a `0600` temp file in the validated `0700` parent; call `os.replace`, fsync parent and reload. Never overwrite an existing v2 path.

- [ ] **Step 6: Adapt Clawbot dependency to recipients path**

Replace the active environment key with:

```python
CLAWBOT_RECIPIENTS_PATH_ENV = "GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH"
```

Keep v1 owner functions only for the explicit initializer and old exact-tag rollback; the new sender/composition path must not fall back to it.

- [ ] **Step 7: Run Task 2 GREEN tests**

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_recipients.py \
  services/quant-api/tests/test_alert_clawbot_owner.py \
  services/quant-api/tests/test_alert_clawbot.py
```

Expected: all pass; existing v1 owner tests remain green as rollback compatibility evidence.

- [ ] **Step 8: Commit Task 2**

```bash
git add services/quant-api/app/alerts/recipients.py services/quant-api/app/alerts/clawbot.py services/quant-api/tests/test_alert_recipients.py services/quant-api/tests/test_alert_clawbot.py
git commit -m "feat(alert): add frozen recipient directory"
```

---

### Task 3: Two-Phase Bootstrap, Retirement and CLI Boundaries

**Files:**
- Create: `services/quant-api/app/alerts/recipient_bootstrap.py`
- Create: `services/quant-api/tests/test_alert_recipient_bootstrap.py`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `services/quant-api/tests/data_foundation/test_cli.py`
- Modify: `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs`
- Modify: `tests/engineering/openclaw_weixin_single_shot.test.mjs`

**Interfaces:**
- Produces `prepare_recipient(alias)`, `confirm_recipient(alias)` and `retire_recipient(alias)` mutations.
- Produces Node action `snapshot_contexts` that returns private data only to the Python child caller; CLI output remains alias/count only.

- [ ] **Step 1: Characterize the pinned context snapshot seam with Node RED tests**

Add a fixture context set and assert `snapshot_contexts`:

```javascript
assert.deepEqual(result, {
  status: "ready",
  action: "snapshot_contexts",
  account_id: "fixture-account",
  contexts: [
    { user_id: "a@im.wechat", context_token: "token-a" },
    { user_id: "b@im.wechat", context_token: "token-b" },
  ],
});
```

Reject group/non-direct IDs, duplicate users, empty tokens, malformed persisted state and more than `MAX_CONTEXT_CANDIDATES = 64`. The Node process must not read or return message bodies.

- [ ] **Step 2: Run Node RED test**

```bash
node --test tests/engineering/openclaw_weixin_single_shot.test.mjs
```

Expected: the new action fails because it is not accepted by `readInput()`.

- [ ] **Step 3: Implement exact `snapshot_contexts` action**

Extend only the fixed action allowlist and pinned inbound module usage. Sort by user ID, validate every direct ID/token, and write one JSON object to stdout. Do not add a watcher, inbound handler, polling loop, reply, Agent, LLM, slash or tool path.

- [ ] **Step 4: Write Python bootstrap RED tests**

Cover prepare/confirm with a fixed clock and deterministic fingerprint key:

```python
prepared = bootstrap.prepare("alice")
assert prepared == BootstrapPrepareResult(alias="alice", baseline_candidate_count=2)

confirmed = bootstrap.confirm("alice")
assert confirmed == BootstrapConfirmResult(alias="alice", candidate_count=1)
```

Assert new user and existing-user token rotation each work; 0 or >1 candidates fail; active/retired alias, target already bound, expired staging, unsafe modes, alias mismatch, concurrent inode replacement and a second prepare while staging exists all fail without changing recipients.

- [ ] **Step 5: Implement staging and atomic mutations**

Use a per-alias staging filename derived only after regex validation. Generate 32 random bytes and compute HMAC-SHA256 fingerprints for `user_id` and `user_id + NUL + token`; store only nonce, fingerprints, alias, prepared/expiry times and exact schema. Use a fixed short expiry constant of 10 minutes. Confirm safely reopens the same inode, computes the set difference, requires exactly one candidate, writes recipients atomically, then unlinks and fsyncs the staging entry.

Enforce alias immutability:

```python
if alias in active_aliases or alias in retired_aliases:
    raise ClawbotRecipientError("CLAWBOT_RECIPIENT_ALIAS_UNAVAILABLE")
```

Retirement must reject owner, remove exactly one active alias, append/sort retired aliases, discard the private target from the file and preserve all DB facts.

- [ ] **Step 6: Add exact CLI commands and readonly classification**

Add:

```text
guiyi runtime clawbot-recipients-init --confirm-write-recipients
guiyi runtime clawbot-recipient-bootstrap prepare --alias ALIAS
guiyi runtime clawbot-recipient-bootstrap confirm --alias ALIAS
guiyi runtime clawbot-recipient-retire --alias ALIAS --confirm-retire
```

`init`, `prepare`, `confirm` and confirmed retire are `readonly=false`; parser-only errors use the existing safe CLI envelope. Success outputs only command, status, readonly, channel, alias/count fields and mutation boolean.

- [ ] **Step 7: Run Task 3 GREEN tests**

```bash
node --test tests/engineering/openclaw_weixin_single_shot.test.mjs
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_recipient_bootstrap.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/data_foundation/test_cli.py
```

Expected: all pass with no private fixture values in stdout/stderr assertions.

- [ ] **Step 8: Commit Task 3**

```bash
git add services/quant-api/app/alerts/recipient_bootstrap.py services/quant-api/app/guiyi_cli/main.py services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs services/quant-api/tests/test_alert_recipient_bootstrap.py services/quant-api/tests/test_alert_cli.py services/quant-api/tests/data_foundation/test_cli.py tests/engineering/openclaw_weixin_single_shot.test.mjs
git commit -m "feat(alert): add recipient bootstrap commands"
```

---

### Task 4: Attempt Repository and Delivery Coordinator

**Files:**
- Create: `services/quant-api/app/alerts/delivery.py`
- Create: `services/quant-api/tests/test_alert_delivery.py`
- Modify: `services/quant-api/app/alerts/service.py`
- Modify: `services/quant-api/app/alerts/runtime.py`
- Modify: `services/quant-api/tests/test_alert_service.py`
- Modify: `services/quant-api/tests/test_alert_runtime.py`

**Interfaces:**
- Consumes `RecipientDirectory.recipients_for(rule_code)` and `ClawbotRunner.send_text(recipient, text)`.
- Produces `AlertDeliveryCoordinator.deliver(event: AlertEvent, message: str)` and read-only `list_delivery_status(trading_day)`.

- [ ] **Step 1: Write repository/state-machine RED tests**

Use an isolated SQLAlchemy session factory and assert:

```python
started = repository.start(event_id, "owner", "clawbot-openclaw-weixin", attempted_at)
assert started.status == "STARTED"
repository.complete(started.id, status="PROVIDER_ACCEPTED", completed_at=completed_at)
```

Duplicate start must return a duplicate outcome and never call sender. Invalid transitions, private error text and naive timestamps must fail. A failed terminal write after provider acceptance must leave the separately committed row as STARTED.

- [ ] **Step 2: Write coordinator RED tests**

Test exact call order with spies:

```text
commit STARTED(owner) -> send owner -> mark accepted
commit STARTED(alice) -> send alice -> mark failed
commit STARTED(bob)   -> send bob   -> mark accepted
```

Assert insert/commit failure prevents that recipient send; one explicit send failure continues; duplicate attempt skips; process-level exception is not retried; outputs contain only alias/status/error code.

- [ ] **Step 3: Implement repository and coordinator**

Use a fresh short-lived session per `start()` and per `complete()` call. Map only an allowlist of stable errors:

```python
PUBLIC_DELIVERY_ERRORS = {
    "CLAWBOT_CONTEXT_UNAVAILABLE",
    "CLAWBOT_CHILD_FAILED",
    "CLAWBOT_SEND_FAILED",
    "ALERT_NOTIFICATION_TRANSPORT_NOT_READY",
}
```

Unknown exceptions become `CLAWBOT_SEND_FAILED`; never persist `str(exc)`. Catch per-recipient normal failures, but do not wrap process termination or create recovery work.

- [ ] **Step 4: Remove legacy timestamp from new Event creation**

Change the request contract to:

```python
@dataclass(frozen=True, slots=True)
class AlertEventCreate:
    rule_id: int
    symbol: str
    contract: str
    trading_day: date
    frequency: str
    bar_end: datetime
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool
    detected_at: datetime
```

Create new Events with `notification_attempted_at=None`; preserve serialization and historical rows unchanged.

- [ ] **Step 5: Integrate Event commit -> immutable text -> coordinator**

Keep evaluation/session work unchanged. After a created Event commits, format exactly one message and append `(event, text)` to an in-memory delivery list. Outside the evaluation DB session, call `coordinator.deliver(event, text)` once per created Event. Coordinator immediately copies the loaded `event.id` and resolves Rule identity in its own short-lived DB session; it must not lazy-load from the detached Event. Existing duplicate Event behavior must continue to produce no delivery call.

- [ ] **Step 6: Implement read-only delivery status**

Join Attempt→Event→Rule, filter exact `trading_day`, order by Event bar/rule/symbol then owner-first/alias, and project DB `STARTED` as public `UNKNOWN`. Do not mutate stale STARTED rows.

- [ ] **Step 7: Run Task 4 GREEN tests**

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_delivery.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_execution_review_service.py \
  services/quant-api/tests/test_alert_api.py
```

Expected: new coordinator tests and all legacy Alert/Execution Review read contracts pass; new Runtime Events expose legacy timestamp as NULL.

- [ ] **Step 8: Commit Task 4**

```bash
git add services/quant-api/app/alerts/delivery.py services/quant-api/app/alerts/service.py services/quant-api/app/alerts/runtime.py services/quant-api/tests/test_alert_delivery.py services/quant-api/tests/test_alert_service.py services/quant-api/tests/test_alert_runtime.py
git commit -m "feat(alert): coordinate per-recipient delivery"
```

---

### Task 5: Direct-Recipient Single-Shot Send, Preflight and Canary

**Files:**
- Modify: `services/quant-api/app/alerts/clawbot.py`
- Modify: `services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs`
- Modify: `services/quant-api/tests/test_alert_clawbot.py`
- Modify: `tests/engineering/openclaw_weixin_single_shot.test.mjs`
- Modify: `services/quant-api/app/guiyi_cli/main.py`
- Modify: `services/quant-api/tests/test_alert_cli.py`

**Interfaces:**
- Produces `ClawbotRunner.probe(recipient)` and `send_text(recipient, text)` for one direct target.
- Produces `guiyi runtime clawbot-preflight`, `alert-canary --recipient-alias`, and `alert-delivery-status --trading-day`.

- [ ] **Step 1: Write single-recipient seam RED tests**

Assert the Node `probe`/`send` actions accept a direct target that differs from the account's historical owner target, but only when `getContextToken(accountId, targetUserId)` returns a token. Assert group IDs, missing contexts and a mismatched account fail before `sendMessageWeixin()`.

For a successful send assert exactly:

```javascript
assert.equal(sendCalls.length, 1);
assert.equal(sendCalls[0].to, "alice@im.wechat");
assert.equal(sendCalls[0].opts.contextToken, "alice-context");
```

- [ ] **Step 2: Implement direct-recipient seam**

Rename `loadFrozenOwner` to `loadFrozenRecipient`; retain account token validation but remove only the equality that incorrectly restricts target to the v1 owner. Continue to require `@im.wechat`, an exact context token and pinned module/version shape.

- [ ] **Step 3: Adapt Python runner and sender contracts**

`ClawbotRunner` accepts `ClawbotRecipient`; one `send_text` invocation still calls `_invoke()` once. Replace the owner-only sender with coordinator injection rather than an internal recipient loop, so only `AlertDeliveryCoordinator` controls fan-out and attempt ordering.

- [ ] **Step 4: Add all-recipient zero-send preflight**

Load one frozen `RecipientDirectory`, probe each recipient in deterministic order, return alias/ready/error code, and fail overall if any active alias is unavailable. It may start a bounded Node child per recipient but must never use action `send`.

- [ ] **Step 5: Add exact single-alias canary and delivery-status CLI**

Parser contracts:

```text
guiyi runtime alert-canary --recipient-alias ACTIVE_ALIAS
guiyi runtime alert-delivery-status --trading-day YYYY-MM-DD
```

Canary resolves exactly one active alias and calls one primitive. Delivery status is readonly and consumes Task 4 read model; it produces Event identity, public alias/channel/times/status/error only.

- [ ] **Step 6: Run Task 5 GREEN tests**

```bash
node --test tests/engineering/openclaw_weixin_single_shot.test.mjs
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_clawbot.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_alert_delivery.py
```

Expected: all pass; assertions prove one alias means one child/primitive and preflight/status never send.

- [ ] **Step 7: Commit Task 5**

```bash
git add services/quant-api/app/alerts/clawbot.py services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs services/quant-api/app/guiyi_cli/main.py services/quant-api/tests/test_alert_clawbot.py services/quant-api/tests/test_alert_cli.py tests/engineering/openclaw_weixin_single_shot.test.mjs
git commit -m "feat(alert): send to one frozen recipient"
```

---

### Task 6: Runtime Composition, Health and launchd Identity

**Files:**
- Modify: `services/quant-api/app/alerts/composition.py`
- Modify: `services/quant-api/app/services/runtime_health.py`
- Modify: `services/quant-api/app/schemas/runtime.py`
- Modify: `deploy/launchd/com.guiyi.quant-api.plist.template`
- Modify: `deploy/launchd/com.guiyi.quant-alert.plist.template`
- Modify: `scripts/ops/macos/run-local-service.sh`
- Modify: `scripts/ops/macos/install-local-services.sh`
- Modify: `scripts/ops/macos/local-services-status.sh`
- Modify: `services/quant-api/tests/test_alert_cli.py`
- Modify: `services/quant-api/tests/test_runtime_health.py`
- Modify: `tests/engineering/test_alert_runtime_launchd.py`
- Modify: `tests/engineering/test_market_runtime_launchd.py`

**Interfaces:**
- Consumes frozen directory and coordinator from Tasks 2/4/5.
- Produces one Runtime composition that refuses startup unless all active recipients preflight ready.

- [ ] **Step 1: Write composition RED tests**

Assert `build_alert_runtime()` loads recipients exactly once, probes each exactly once before Redis subscription, injects one coordinator and never sends during construction. Missing/invalid config or one failed alias must raise `ALERT_NOTIFICATION_TRANSPORT_NOT_READY` before Runtime starts.

- [ ] **Step 2: Implement frozen Runtime composition**

Construction sequence must be:

```text
activation marker -> dependency/version validation -> load v2 directory once
-> zero-send probe every recipient -> construct coordinator/session factory
-> construct AlertRuntime -> subscribe/run only after caller enters run_forever
```

Do not reread recipients per Event and do not retain v1 owner fallback.

- [ ] **Step 3: Write health RED tests**

For configured valid recipients assert additive public fields:

```python
assert health["notification"] == {
    "transport": "clawbot-openclaw-weixin",
    "recipient_configured": True,
    "recipient_count": 3,
    "ready_recipient_count": 3,
    "would_send": False,
}
```

Structure-only health must not spawn a child or contact provider. Test missing/invalid config with zero counts and a stable error type; fixture IDs/paths must not appear.

- [ ] **Step 4: Implement structure-only health**

Read/validate manifest and recipients metadata without probing contexts. Live readiness remains the responsibility of explicit preflight and Runtime construction. Preserve dependency injection so unrelated tests never read the real workstation config.

- [ ] **Step 5: Replace launchd/runtime environment identity**

Replace only active source key:

```text
GUIYI_ALERT_CLAWBOT_OWNER_PATH
→ GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH
```

Update installer validation, rendered plist assertions and `local-services-status.sh` readback. The status script may print counts/ready booleans but never the recipients path or private IDs. Keep v1 path readable only by the explicit init command's operator environment, not active launchd templates.

- [ ] **Step 6: Run Task 6 GREEN tests**

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_runtime_health.py
uv run --project services/quant-api pytest -q tests/engineering -k 'launchd or local_services'
bash -n scripts/ops/macos/run-local-service.sh scripts/ops/macos/install-local-services.sh scripts/ops/macos/local-services-status.sh
plutil -lint deploy/launchd/com.guiyi.quant-api.plist.template deploy/launchd/com.guiyi.quant-alert.plist.template
```

Expected: all selected tests/checks pass without reading or mutating real private configuration.

- [ ] **Step 7: Commit Task 6**

```bash
git add services/quant-api/app/alerts/composition.py services/quant-api/app/services/runtime_health.py services/quant-api/app/schemas/runtime.py deploy/launchd/com.guiyi.quant-api.plist.template deploy/launchd/com.guiyi.quant-alert.plist.template scripts/ops/macos/run-local-service.sh scripts/ops/macos/install-local-services.sh scripts/ops/macos/local-services-status.sh services/quant-api/tests/test_alert_cli.py services/quant-api/tests/test_runtime_health.py tests/engineering/test_alert_runtime_launchd.py tests/engineering/test_market_runtime_launchd.py
git commit -m "feat(alert): compose recipient-aware runtime"
```

---

### Task 7: Message Contract, Canonical Documentation and Regression Boundaries

**Files:**
- Modify: `services/quant-api/app/alerts/notification.py`
- Modify: `services/quant-api/tests/test_alert_notification.py`
- Modify: `AGENTS.md`
- Modify: `TESTING.md`

**Interfaces:**
- Produces exact HTDY research footer and documents the three-table Alert Application Domain.
- Does not change SuBing formatter, evaluator, Scope or public Rule registry.

- [ ] **Step 1: Write message RED tests**

Assert exact HTDY text including trailing footer:

```python
assert format_alert_message(htdy_message).endswith("\n\n研究观察，非交易指令")
```

Freeze the current SuBing owner-only message as a full-string characterization test and assert no alias/count/recipient information appears in either body.

- [ ] **Step 2: Implement the minimal formatter change**

Branch only on exact HTDY Rule and append the approved footer once. Do not alter product, contract, boundary time, direction labels or canary text.

- [ ] **Step 3: Update canonical documentation**

After executable tests are green:

- `AGENTS.md`: Alert Application Domain becomes three tables; continuous authorization template distinguishes HTDY exact alias set from SuBing owner-only; all external Gates remain independent.
- `TESTING.md`: add exact targeted pytest, Node, migration, CLI dry/read-only and launchd validation commands; label init/bootstrap/retire/canary/migration/Runtime commands as external Gates.

- [ ] **Step 4: Run Task 7 GREEN checks**

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_registry.py
rg -n 'three tables|三张表|recipient|接收人|owner-only|owner only' AGENTS.md TESTING.md
```

Expected: formatter/registry/runtime tests pass and docs retain explicit no-order/no-retry/external-Gate boundaries.

- [ ] **Step 5: Commit Task 7**

```bash
git add services/quant-api/app/alerts/notification.py services/quant-api/tests/test_alert_notification.py AGENTS.md TESTING.md
git commit -m "docs(alert): define fixed recipient boundaries"
```

---

### Task 8: Complete Verification, Self-Review and Independent Review

**Files:**
- Modify: `STATUS.md`
- Modify only additional files required to repair findings inside the approved scope.

**Interfaces:**
- Consumes all Tasks 1–7.
- Produces `CODE_COMPLETE / TEST_COMPLETE`; no external Gate status.

- [ ] **Step 1: Run focused Alert/Execution Review suite**

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_alert_models.py \
  services/quant-api/tests/test_alert_recipients.py \
  services/quant-api/tests/test_alert_recipient_bootstrap.py \
  services/quant-api/tests/test_alert_delivery.py \
  services/quant-api/tests/test_alert_clawbot_owner.py \
  services/quant-api/tests/test_alert_clawbot.py \
  services/quant-api/tests/test_alert_notification.py \
  services/quant-api/tests/test_alert_service.py \
  services/quant-api/tests/test_alert_runtime.py \
  services/quant-api/tests/test_alert_cli.py \
  services/quant-api/tests/test_alert_api.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_execution_review_service.py \
  services/quant-api/tests/test_execution_review_api.py \
  services/quant-api/tests/alembic/test_alert_notification_attempts_migration.py
node --test tests/engineering/openclaw_weixin_single_shot.test.mjs
```

Expected: all pass with no real config, provider or production DB access.

- [ ] **Step 2: Run complete backend and engineering verification once**

Use the exact current commands from `TESTING.md`, including isolated PostgreSQL identity proof, full backend pytest, engineering pytest, Ruff, Mypy, shell syntax, plist render/lint, secret scan and diff check. Do not substitute SQLite for the migration suite.

- [ ] **Step 3: Run forbidden-path and privacy scans**

```bash
rg -n 'WECOM_WEBHOOK_URL|Courier|queue|retry|replay|backfill|fallback|sendMessageWeixin' services/quant-api/app deploy scripts/ops tests/engineering
rg -n 'GUIYI_ALERT_CLAWBOT_OWNER_PATH' services/quant-api/app deploy/launchd scripts/ops
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

Expected: `sendMessageWeixin` appears only in the fixed single-shot seam/tests; forbidden active provider/queue paths are absent; old owner env is absent from new active composition/templates; secret finding count is 0; diff check is clean.

- [ ] **Step 4: Self-review against every Spec section**

Record a checklist mapping Sections 4–15 to code/tests. Explicitly verify:

- owner-first deterministic routing and max 5;
- v1→v2 init, alias immutability and Runtime-start freeze;
- DB-before-send and unique-conflict no-send;
- STARTED→UNKNOWN with no retry;
- SuBing owner-only and legacy timestamp semantics;
- no private values in DB/logs/CLI/health;
- no external mutation performed.

- [ ] **Step 5: Request independent standards and spec review**

Review the cumulative diff from the pre-Task-1 commit. Acceptance requires `Critical=0` and `Important=0`; repair any finding coherently, rerun affected tests, then rerun the complete applicable verification once.

- [ ] **Step 6: Record verified status and commit final repairs/status**

Update `STATUS.md` with actual fresh counts and `DEVELOP CODE_COMPLETE / TEST_COMPLETE`; retain the current production exact-tag, single-owner Runtime facts and every external Gate as pending. Run `git diff --name-only`, stage `STATUS.md` plus each listed in-scope repair file by its literal path, and never use `git add -A` or stage unrelated files. Then commit:

```bash
git commit -m "fix(alert): close fixed recipient review findings"
```

The status change makes this a non-empty closeout commit even when review required no code repair.

- [ ] **Step 7: Close implementation status without external claims**

Report:

```text
CODE_COMPLETE
TEST_COMPLETE
EXTERNAL_GATES_PENDING = G1 release, G2 production migration, G3 private init/bootstrap,
G4 zero-send preflight, G5 per-alias canary, G6 bounded continuous authorization,
G7 Runtime promotion, G8 natural acceptance
```

Do not push, release, migrate, bootstrap, canary, send, switch Runtime or mutate Scope unless a later user request gives a fresh exact single-use execution intent for that specific Gate.

---

## External Rollout Boundary (Not Executed by This Plan)

After Task 8 and a separate user decision, external work must retain this order:

```text
G1 exact release/tag
→ G2 additive production migration
→ G3 v1→v2 init, then each new alias prepare/confirm
→ G4 all-recipient zero-send preflight
→ G5 one separately authorized canary per new alias
→ G6 exact HTDY Rule + current Scope + exact aliases + transport authorization
→ G7 exact-tag Alert Runtime promotion/readback
→ G8 natural HTDY Event read-only acceptance
```

No Gate authorizes the next Gate, a retry, a changed alias/Scope/transport, or any order path.
