# TASK-GUIYI-DEMO-001：为 GET /api/health 补充自动化测试

> TASK_ID: GUIYI-DEMO-001
> 任务状态：RESULT_READY
> 生成时间：2026-07-11
> 关联 Plan：.ai/results/GUIYI-DEMO-001/plan_result.md

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | GUIYI-DEMO-001 |
| GitHub Issue | #8 |
| Branch | feature/lean-v1-demo |
| PR | 待创建 |
| Status | RESULT_READY |
| Created At | 2026-07-11 |
| Updated At | 2026-07-11 |
| Owner | WorkBuddy |

> **Issue Gate 说明**：已创建 GitHub Issue #8（https://github.com/firehell/guiyi-quant-workstation/issues/8）。
> `codex_dev.sh` Issue Gate 正则 `^#[0-9]+$` 接受 `#8`，Gate 通过。

---

## 1. 任务状态
RESULT_READY（DEV + TEST + RESULT 已完成，等待人工验收）

## 2. 任务类型
接口自动化测试补充（测试体系 / 普通功能开发-测试代码）
- 允许进入 CodeBuddy/Codex 开发阶段：**是**（仅新增/完善测试文件，不碰业务代码）

## 3. 参与角色
- **必须参与**：项目经理/流程调度员（状态与拆分）、后端开发负责人（出 Prompt/写测试代码）、测试专家/QA Lead（代码开发必参）、交付专家（交付验收）
- **可选参与**：安全与权限专家（确认测试不泄漏密钥/不越权，本任务 trivially 满足）、产品负责人（轻量确认验收目标对齐）
- **不需要参与**：量化业务专家、策略研究员、量化架构师、数据工程师、交互视觉专家、DevOps/本地运维（无 UI/无行情/无部署/无密钥变更）

## 4. 背景
`GET /api/health` 是 V1 系统基础健康探针（Mac mini 长期运行、企业微信巡检依赖）。接口当前已实现并返回 `{"status":"ok","service":"guiyi-quant-api","version":"0.1.0"}`，但仓库现有 `tests/test_health.py` 仅断言了 `200` 与 `status=="ok"`，未覆盖 `service`/`version` 字段，且 `/api/health` 路由本身完全未被测试。Lean V1 端到端验证任务要求补齐这层最小断言，作为后续半自动开发流程的样板。

## 5. 目标
为 `GET /api/health`（含共用的 `/health`）补充自动化测试，稳定验证其返回健康状态信息，断言覆盖：HTTP 200、`status=="ok"`、`service=="guiyi-quant-api"`、`version` 存在且为非空字符串。

## 6. 不做事项
- 不改 `app/main.py` 接口业务行为
- 不改 `.env` / token / webhook / 密钥
- 不改交易 / 策略 / 行情 / 数据库业务逻辑
- 不改部署配置
- 不 push / merge / deploy
- 不新建测试文件（避免重复实现，见要求 4）

## 7. 涉及模块
- 仅：`services/quant-api/tests/test_health.py`
- 不涉及：`services/quant-api/app/main.py`（只读参考）、任何业务/数据/策略模块

## 8. 产品需求
验收目标（对齐要求 3）：
1. HTTP 状态码 == 200
2. `status` == "ok"
3. `service` == "guiyi-quant-api"
4. `version` 字段存在且为**非空字符串**

## 9. 量化业务规则
不适用（健康检查接口无行情/合约/交易日语义）。

## 10. 数据影响
无。测试纯内存 `TestClient`，不触达数据库 / RQData / 行情。

## 11. 技术方案
最小改动：在现有 `tests/test_health.py` 内
- 扩展 `test_health_endpoint_returns_ok`：补充 `service` 与 `version` 断言
- 新增 `test_api_health_endpoint_returns_full_payload`：对 `/api/health` 做完整四断言

接口无需任何修改（当前实现已返回所需字段，新断言对实现必然通过）。

## 12. 交互视觉要求
不适用（无 UI / 无企业微信消息格式变更）。

## 13. 安全权限要求
- 严禁读取/修改 `.env` / token / webhook / 密钥
- 测试不得打印或断言任何敏感字段
- 仅本地测试，不真实发送任何外部请求
- 本任务不触发安全专家一票否决（无凭证变更）

## 14. 开发步骤（DEV 阶段，待 APPROVE 后执行）
1. 在 `feature/lean-v1-demo` 分支工作（确认非 main）
2. 编辑 `services/quant-api/tests/test_health.py`：
   - 在 `test_health_endpoint_returns_ok` 增加 `service`/`version` 断言
   - 新增 `test_api_health_endpoint_returns_full_payload` 对 `/api/health`
3. 不改动其他任何文件
4. 不提交、不 push，完成后生成 Result Bundle，等待人工处理

## 15. Codex Plan Prompt（只读）
```
你处于 PLAN 模式（只读，禁止写代码）。
任务：为 services/quant-api 的 GET /api/health（与 /health 共用 health_check()）补充自动化测试。
现状：接口返回 {"status":"ok","service":"guiyi-quant-api","version":"0.1.0"}；
现有 tests/test_health.py 仅断言 200 与 status=="ok"，缺 service/version 断言且 /api/health 未测。
请只做只读分析并输出最小改动方案：
- 列出需新增/修改的断言（HTTP 200、status==ok、service==guiyi-quant-api、version 非空字符串）
- 确认仅改 tests/test_health.py，不碰 app/main.py
- 给出测试命令与预期结果
严禁修改任何文件。输出 plan 后停止。
```

## 16. Codex Dev Prompt（待 APPROVED_DEV 后执行）
```
你在 DEV 模式（允许 workspace-write，仅测试文件）。
打开 services/quant-api/tests/test_health.py：
1. 在 test_health_endpoint_returns_ok 中补充：
   assert payload["service"] == "guiyi-quant-api"
   version = payload.get("version"); assert isinstance(version, str) and version != ""
2. 新增 test_api_health_endpoint_returns_full_payload，对 /api/health 做同等四断言。
严禁修改 app/main.py 及其他文件；严禁触碰 .env/密钥；不 push。
完成后停止，等待 TEST 阶段。
```

## 17. CodeBuddy 执行 Prompt
```
收到任务 GUIYI-DEMO-001（PLAN_READY）。
步骤：
1. 校验状态：必须为 APPROVED_DEV 才执行 DEV；当前若仍为 PLAN_READY 则停止并回报等待人工确认。
2. 护栏自检：若检测到改 .env/密钥/主力业务/main.py health_check/push 动作 → 立即中止。
3. 确认当前分支为 feature/lean-v1-demo（非 main）。
4. 调 codex_dev.sh 执行 DEV Prompt（仅改 tests/test_health.py）。
5. 调 run_tests.sh 执行：cd services/quant-api && python -m pytest tests/test_health.py -v
6. 调 collect_result.sh 汇总 modified_files / test_command / test_result / risks。
7. 回报 WorkBuddy 生成交付报告。不自动 push/merge/deploy。
```

## 18. 测试清单
- [ ] `test_health_endpoint_returns_ok` 对 `/health` 断言 200 + status + service + version
- [ ] 新增 `test_api_health_endpoint_returns_full_payload` 对 `/api/health` 四断言全过
- [ ] 原有 `test_healthz_endpoint_returns_local_workstation_payload` 未被改动且通过
- [ ] 测试独立运行：`pytest tests/test_health.py -v` 无依赖外部服务
- [ ] 不触发数据库 / RQData / 行情连接
- [ ] 测试文件未引入密钥读取或打印
- [ ] 原有全量测试套件不受回归影响（仅加断言）
- [ ] 运行环境为 quant-api venv（fastapi/pytest 已装）

## 19. 验收标准
**Pass（全部满足）**：
- 自动化测试可独立运行并通过（test_health + test_api_health 全 PASSED）
- 原有测试（含 healthz）未受影响
- 仅修改 `services/quant-api/tests/test_health.py`，无超出范围文件改动
- Result Bundle 含 modified_files / test_command / test_result / risks

**Block（任一触发则不通关）**：
- 修改了 `app/main.py` 或任何业务/数据/策略模块
- 触碰 `.env`/token/webhook/密钥
- 在 `main` 分支执行 DEV
- 发生 push/merge/deploy
- 原有测试被破坏或新测试失败

## 20. 风险点
- R1（低）：测试依赖 `app.main.app` 完整导入；现有基线已可导入。
- R2（低/保护）：`version` 硬编码；若未来动态读取失败返回空，测试会失败（预期监控）。
- R3（中/护栏）：DEV 严禁改 `health_check()`，已列入不做事项。
- R4（满足）：分支非 main。
- R5（满足）：纯测试文件，无凭证/业务/部署改动。
- R6（流程）：须人工 APPROVE 才进 DEV；PLAN 阶段不修改代码文件，仅生成流程文档。

## 21. 交付记录
- PLAN_READY：2026-07-11，Plan 见 `.ai/results/GUIYI-DEMO-001/plan_result.md`，PLAN 阶段停止，等待人工 APPROVE。
- APPROVED_DEV：2026-07-11，人工批准，审批记录见 `.ai/approvals/GUIYI-DEMO-001.json`，进入 DEV。
- DEV：2026-07-11，`codex_dev.sh --task GUIYI-DEMO-001` 执行成功（exit 0），codex exec 修改 `services/quant-api/tests/test_health.py`（+18/-1），Scope Gate PASS，HEAD 未变。
- TEST：2026-07-11，`cd services/quant-api && python -m pytest tests/test_health.py -v` → 3 passed in 0.77s（test_health_endpoint_returns_ok + test_api_health_endpoint_returns_full_payload + test_healthz_endpoint_returns_local_workstation_payload 全部 PASSED）。
- RESULT：2026-07-11，Result Bundle 已生成，见 `.ai/results/GUIYI-DEMO-001/result_bundle.json`。未 commit/push/merge/deploy，等待人工验收。
