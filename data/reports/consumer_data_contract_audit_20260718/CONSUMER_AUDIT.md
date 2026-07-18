# CONSUMER-DATA-CONTRACT-AUDIT-001

生成时间：2026-07-18

状态：`COMPLETED / CONSUMER_CONTRACT_GAPS_IDENTIFIED`

## 结论

阶段 B 的 `DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT` 只证明 canonical 资产和 active bindings 可进入消费者契约阶段，不证明消费者已经统一使用它们。本次只读审计确认：Market 的显式 Profile 浏览路径已能返回 lineage，live-confirmed Signal 也有严格质量 Gate；但 Backtest、historical Signal、Review、Market indicator 原子一致性和 actual mapping 仍存在 formal escape paths。

本目录的三个 CSV 是本报告的逐行证据源：

- `consumer_escape_paths.csv` 记录入口、文件行号、逃生模式和七类分类；
- `formal_consumer_matrix.csv` 记录消费者的 formal 属性与契约结论；
- `unsafe_bypass_register.csv` 用 `unsafe_id` 回链所有 `unsafe_bypass`，并给出最小修复文件、风险、测试和建议阶段。

审计未修改 Service、ORM、API、Web、数据库、Parquet、manifest、Profile binding、历史报告或行情资产。

## 八个重点问题

### 1. generic `/api/backtests/tasks` 是否允许任意本地路径

是。公开端点直接接收 `BacktestTaskConfig`，其字段包含 `bar_data_path` 和 `auxiliary_bar_data_paths`，随后由 `BacktestService` 持久化并由 runner 直接读取。`extra="forbid"` 只能阻止未知字段，不能阻止这两个已声明路径。见 `BT-01`、`BT-04` 和 `U-BT-01`。

### 2. fixed JM task 是否绕过 Profile

是。fixed builders 调用 `_latest_formal_file()`，按 rqdata/bars/jm/JM.MAIN/period/primary/passed 查询并以 end time、created time、id 倒序取一行；它不验证 `ProfileActiveBinding`。因此“passed”不等于“当前 Profile 绑定”。见 `BT-02` 和 `U-BT-02`。

### 3. task/report 是否保存 Profile binding snapshot

否。migration `20260712_0023` 已在数据库层为 task/report 增加 nullable `profile_id`、`market_data_file_id`，但当前 ORM、schema、service 未映射和写入；数据库和模型均没有 Backtest `binding_snapshot` 列。见 `BT-03`、`U-BT-03`。

### 4. Signal formal event 是否保存完整 asset lineage

否。事件保存 provider、source、data_role、quality、contract 和时间窗口等描述字段，但 0023 的 Profile/file 列未映射，事件创建与 serializer 也未写入，并且不存在 immutable binding snapshot。live-confirmed Gate 本身严格，但不能弥补落库 lineage 缺失。见 `SIG-04` 至 `SIG-06`。

### 5. Review 是否能回到原 bar/binding

不能可靠回到。Review 可以回链 report/trade ID 和描述性 symbol/contract/period/time，但 report 没有原始 file/snapshot；Web 还会猜测 `${symbol}.MAIN` 并在失败时去掉 provider 重试。binding 切换后无法证明展示的是原回测行情。见 `REV-01`、`REV-02`。

### 6. Market bars 与 indicator 是否可能使用不同 binding

可能。页面分别发起 bars 与 indicator 请求，服务端分别 resolve/read；两次请求之间 active binding 可以切换，且 indicator 响应不提供足以与 bars 对账的 immutable file snapshot。见 `MKT-02`。

### 7. warning/failed/partial 是否可能进入严格 consumer

存在风险：

- generic Backtest 配置允许 warning override；inline 和 batch 公开接口也允许客户端开启 warning；
- formal `run-su-bing-backtest` CLI 同样允许 warning override，不解析 Profile，unchecked 也可继续；
- historical Signal 允许 warning override，且无 quality report 时形成的 unchecked 状态不会 fail-closed；
- vn.py runner 对缺少 `data_role`、`quality_status` 的行分别默认 `primary`、`passed`；
- failed 在现有多处路径会被拒绝，但这不足以形成 passed-only；
- live-confirmed Signal 单独要求 passed、零 warnings、confirmed bar、rqdata 和 actual contract，因此该 Gate 会阻止 warning/failed/partial。

见 `BT-05` 至 `BT-08`、`SIG-01`、`SIG-03`、`SIG-06`、`CLI-01`。

### 8. actual contract mapping 是否统一

否。Market dominant reader、live target resolver、historical Signal target selection 和 Signal contract context 使用不同的选择/推断路径。fixed JM 的行情文件选择问题与 actual mapping kernel 是两个问题；本轮 Backtest 修复不得顺手修改 mapping 内核。见 `MKT-04`、`U-MKT-02`。

## 分类边界

本审计只使用题目给定的七类：

- `formal_production_research`：正式研究链中已具备严格 Gate 的局部路径；
- `legacy_frozen`：report 14 等历史冻结链，仅保留复核，不升级为新 formal 入口；
- `experiment_only`：可直接读路径但不得写 formal task/report；
- `admin_internal`：数据运维、inventory、导出或修复工具；
- `test_fixture`：被 hash/window/row count 固定的测试输入；
- `safe_browser_mode`：允许展示 warning/unchecked，但明确不作为严格研究输入；
- `unsafe_bypass`：能绕开 Profile、passed-only 或 immutable lineage 的 formal 路径，或能将实验路径写入 formal persistence。

## 阶段建议

最小修复顺序为：

1. `BACKTEST-PROFILE-CONTRACT-002`：封闭公开路径、fixed JM latest-file、task/report snapshot 和 runner 默认 lineage；
2. `C-SIGNAL-PROFILE-CONTRACT`：historical scan passed-only 与事件 lineage；
3. `C-REVIEW-PROFILE-CONTRACT`：从 report snapshot 回原行情；
4. `C-MARKET-INDICATOR-CONTRACT`：bars/indicator 同一资产；
5. `C-ACTUAL-CONTRACT-MAPPING`：统一 actual mapping 使用与 mapping lineage。

本次审计验收标志：`CONSUMER_CONTRACT_GAPS_IDENTIFIED`。
