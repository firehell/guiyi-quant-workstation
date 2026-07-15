# GUIYI-DEMO-001 只读 Plan（PLAN 阶段产物）

> 本文件是 **PLAN 阶段** 的只读分析产物，不修改代码文件，仅生成流程文档。
> 状态：PLAN_READY，等待人工 APPROVE 后才进入 DEV。
> 生成时间：2026-07-11
> 关联任务单：docs/tasks/GUIYI-DEMO-001.md

---

## 1. 仓库现状（只读核实结果）

| 项 | 核实结果 |
|---|---|
| 当前分支 | `feature/lean-v1-demo`（非 `main`，满足"不在 main 执行 DEV"） |
| 后端框架 | FastAPI（`services/quant-api/app/main.py`，`FastAPI(title="归一量化 API", version="0.1.0")`） |
| 健康检查接口 | `app/main.py:63-70`，`@app.get("/health")` 与 `@app.get("/api/health")` 共用 `health_check()` |
| 接口返回体 | `{"status": "ok", "service": "guiyi-quant-api", "version": "0.1.0"}` |
| 现有测试 | `services/quant-api/tests/test_health.py`（2 个用例） |
| 测试框架 | pytest 9.x，`pythonpath=["."]`，`tests/conftest.py` 无 fixture（无 autouse 干扰） |
| 运行方式 | `cd services/quant-api && python -m pytest tests/test_health.py -v` |

### 现有测试覆盖逐条核对（对照要求 3）

| 要求 3 断言 | 现有 `test_health.py` 是否覆盖 | 说明 |
|---|---|---|
| HTTP 200 | ✅ 部分 | `test_health_endpoint_returns_ok` 对 `/health` 断言 200；`/api/health` **未测** |
| `status == "ok"` | ✅ 部分 | 对 `/health` 断言；`/api/health` **未测** |
| `service == "guiyi-quant-api"` | ❌ 未覆盖 | 全仓库无任何测试断言该字段 |
| `version` 字段存在且非空字符串 | ❌ 未覆盖 | 全仓库无任何测试断言该字段 |

**结论**：现有测试**非等效测试**（仅 2/4 断言，且未覆盖 `/api/health` 路由）。
按任务要求 4 → **不重复实现新文件**，提出**最小必要改动**：在 `tests/test_health.py` 内扩展。

---

## 2. 最小必要改动方案（DEV 阶段将执行的内容，此处仅为描述）

**唯一改动文件**：`services/quant-api/tests/test_health.py`（新增断言 + 新增 1 个用例）

改动 A —— 扩展现有用例，补充 `service` 与 `version` 断言：

```python
def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "guiyi-quant-api"
    version = payload.get("version")
    assert isinstance(version, str) and version != ""
```

改动 B —— 新增 `/api/health` 路由的完整断言（任务明确点名该路由）：

```python
def test_api_health_endpoint_returns_full_payload() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "guiyi-quant-api"
    version = payload.get("version")
    assert isinstance(version, str) and version != ""
```

**不改动**：`app/main.py` 的 `health_check()`（接口行为保持不变，新断言对当前实现必然通过）。
**不新建**文件（避免重复实现，符合任务要求 4）。

---

## 3. 验证预判（只读静态分析，未在 PLAN 阶段执行测试）

- 接口当前实现已返回 `service="guiyi-quant-api"`、`version="0.1.0"`，故上述新增断言**预期全部通过**，无需修改接口。
- 现有 `test_healthz_endpoint_returns_local_workstation_payload` 保持原样，**不受影响**（不在本任务范围）。
- 测试无 DB 依赖（纯 `TestClient`），不会触发数据库/行情/策略业务逻辑。

> 说明：按流程 TASK→PLAN→APPROVE→DEV→TEST→RESULT，本 PLAN 阶段**只做只读分析与方案描述，不运行 pytest、不修改代码文件，仅生成流程文档**。测试执行属于 TEST 阶段，待 APPROVED_DEV 后由 CodeBuddy/Codex 在 Mac mini 执行。

---

## 4. 测试命令（TEST 阶段使用）

```bash
cd services/quant-api
python -m pytest tests/test_health.py -v
```

预期结果：`test_health_endpoint_returns_ok`、`test_api_health_endpoint_returns_full_payload`、`test_healthz_endpoint_returns_local_workstation_payload` 全部 PASSED。

---

## 5. 风险说明（R1–R6）

- **R1（低）**：测试依赖 `from app.main import app` 完整导入链。现有 `test_health.py` 已成功导入，风险低；若 main.py 顶层导入在未来引入测试环境缺失依赖，会失败——但属现有基线问题，非本任务引入。
- **R2（低/预期保护）**：`version` 为硬编码 `"0.1.0"`。若未来改为动态读取且失败返回 `None`/空，测试将失败——这正是预期监控行为（捕获 version 缺失）。
- **R3（中/护栏）**：DEV 阶段**严禁修改** `app/main.py` 的 `health_check()`。若误改会使新测试失败且破坏现有接口行为，已列入任务"不做事项"。
- **R4（满足）**：当前分支 `feature/lean-v1-demo` ≠ `main`，符合"不在 main 分支执行 DEV"。
- **R5（满足）**：纯测试文件改动，不触碰 `.env`/token/webhook/密钥、不碰交易/策略/行情/数据库逻辑、不改部署配置。
- **R6（流程）**：必须人工 APPROVE 后才进入 DEV；PLAN 阶段不修改代码文件，仅生成流程文档。

---

## 6. 超出范围确认（明确不做）

- ❌ 不改 `app/main.py` 接口行为
- ❌ 不改 `.env` / token / webhook / 密钥
- ❌ 不改交易、策略、行情、数据库业务逻辑
- ❌ 不改部署配置
- ❌ 不 push / merge / deploy
- ❌ 不新建测试文件（避免重复实现）

---

## 7. Result Bundle 模板（RESULT 阶段产出，此处预定义结构）

DEV+TEST 完成后，`collect_result.sh` / WorkBuddy 汇总应包含：

```
{
  "task_id": "GUIYI-DEMO-001",
  "modified_files": ["services/quant-api/tests/test_health.py"],
  "test_command": "cd services/quant-api && python -m pytest tests/test_health.py -v",
  "test_result": "<pytest 输出摘要：N passed, 0 failed>",
  "risks": "R1-R6 摘要（见上）",
  "out_of_scope_confirm": "未改接口/.env/业务/部署；未 push/merge/deploy",
  "approval_gate": "等待人工 APPROVE 后才可 merge/deploy"
}
```

---

## 8. Plan 阶段停止声明

✅ 只读 PLAN 已完成。
⛔ 按任务要求 8，Plan 阶段结束后**停止，不自动进入 DEV**。
➡️ 下一步：等待你（用户）人工确认 → 将任务单状态推进至 `APPROVED_DEV` → CodeBuddy 在 Mac mini 调 Codex CLI 执行 DEV（写入测试断言）→ TEST → RESULT。

---

## 附录 A：PLAN_READY 证据包（2026-07-11 更新）

**A1. `git status --short --branch`**
```
## feature/lean-v1-demo
```
> 工作树仅含本会话产出的流程文档（docs/tasks/ + .ai/results/），无代码文件改动。

**A2. 任务单路径**
`docs/tasks/GUIYI-DEMO-001.md`

**A3. Plan 文件路径**
`.ai/results/GUIYI-DEMO-001/plan_result.md`

**A4. Plan 文件 SHA256**
（见本次输出，由 `shasum -a 256` 计算）

**A5. 本阶段未修改任何代码文件**
- PLAN 阶段不修改代码文件，仅生成流程文档（任务单 + Plan）；
- 未运行 `git add/commit/push`；
- 未运行 pytest / codex。

**A6. 状态字段统一**
- 任务单与 Plan 均标注 `PLAN_READY`；
- 下一状态在两文档中统一为 `APPROVED_DEV`。

**A7. DEV 允许改动范围锁定**
- 仅 `services/quant-api/tests/test_health.py`；
- 任务单 §6 不做事项、§7 涉及模块、§14 开发步骤与 Plan §6 超出范围确认一致；
- `codex_dev.sh` 内置 Scope Gate 依据任务单 §7「涉及模块」校验允许路径，越界即退出码 6。

**A8. 下一步 CodeBuddy 将调用的 codex exec 命令（仅展示，未执行）**
```bash
cd /Volumes/扩展盘/guiyi-quant-workstation
bash scripts/ai/codex_dev.sh --task GUIYI-DEMO-001
```
> 注：`--plan` 未传时，`codex_dev.sh` 默认查找 `.ai/results/GUIYI-DEMO-001/plan_result.md`（本文件所在路径）。

**A8.1 进入 DEV 前须解决的集成缺口**
- **G1 任务文件路径** ✅ 已解决：任务单已迁移到 `docs/tasks/GUIYI-DEMO-001.md`，匹配 `codex_dev.sh` 候选路径。
- **G2 GitHub Issue 字段** ✅ 已解决：已创建 GitHub Issue #8（https://github.com/firehell/guiyi-quant-workstation/issues/8），任务单 §0 元信息更新为 `GitHub Issue | #8`，`codex_dev.sh` Issue Gate 正则 `^#[0-9]+$` 接受 `#8`。
- **G3 审批记录** ⏸ 暂不处理：按用户指示不生成 `.ai/approvals/GUIYI-DEMO-001.json`，待人工 APPROVE 时产出。

**A9. 停止声明**
✅ PLAN_READY 证据包已更新；⛔ 未进入 DEV、未执行任何 codex 命令、未修改代码；➡️ 继续等待人工批准。
