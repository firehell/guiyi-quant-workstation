# Newow 四周期只读盘点（2026-09-24）

## 结论与固定口径

本次固定 `operational_products.txt` 的 60 个品种，目标频率为 1m/15m/30m/60m，形成 **240 个品种×周期**与 **720 个品种×周期×策略**（趋势、震荡、主升浪）的完整分母。历史与参考统计输入目标起点为交易日 `2023-01-01`，当前已完成交易日 `2026-09-24` 为目标末端。2023 起点与现有 P9 历史源审计一致，不因短历史品种自动后移。最新统一审计 `as_of=2026-09-25T00:00:33.267970+08:00`（数据库 repeatable-read 快照）：9/24 当日 MDS 240/240 均被缺失 rank1 阻断，因此目标 `2023-01-01..2026-09-24` 没有可证明全就绪品种。以下将截至 9/23 的历史输入基线与 9/24 新鲜度分开列示，不拼成同快照全量通过。

MDS 对每个请求窗口逐品种、逐周期验证权威 Calendar/Session、rank1、Catalog/Parquet 和 expected endpoint；`WINDOW_READABLE` 只证明该**逻辑 owner 窗口**输入可读，不证明单物理合约从上市开始的计算前缀、策略预热、Reference 构建、页面能力或正式开放。四周期完成水位仍须独立计算。最新 9/24 探针使用单个 repeatable-read/read-only transaction；精确快照时间、代码、脚本与 universe 哈希在 [唯一机器矩阵](../../outputs/newow-four-period-audit-20260924/matrix.json) 中。该文件每个品种×周期同时记录最新日、历史、近月和上市后状态，并单列 720 个策略案例；未运行公式者均为 `NOT_EVALUATED`。

| 层次 | 结果 | 边界 |
| --- | --- | --- |
| 最新完成日 9/24 | 0/240 可读；240/240 `MAIN_CONTRACT_MAP_MISSING` | 独立 SQL 回读：9/24 Calendar=5 交易所、Session=60 品种、rank1=0；未证明来源 1m 缺失 |
| 近月 9/23 基线 | 240/240 `WINDOW_READABLE` | 仅 2026-08-24..09-23，不能推导全历史或 9/24 新鲜度 |
| 历史/统计 9/23 基线 | 196/240 `WINDOW_READABLE`（49 品种）；44/240 `TRADING_SESSION_MISSING`（11 品种） | 11 品种于 2023-01-01 尚未上市；完整矩阵未保存精确事务时间，不能与 9/24 快照拼成同快照 READY |
| 11 品种上市后输入 | 44/44 `LIFECYCLE_WINDOW_READABLE` | 独立诊断，不替换固定目标窗口 |
| 三策略计算 | 0/720 已验证，720 `NOT_EVALUATED` | Newow 尚无完整四周期产品合同与逐策略预热验证 |
| 页面/正式能力 | 0/240 已开放 | develop 仅枚举 1w/1d/60m，60m 关闭；1m/15m/30m 未枚举 |
| Runtime 与自然验收 | 未评估 | 数据读回、发布、Runtime、自然运行分属不同 Gate |

**49 个截至 9/23 历史窗口四周期均可读品种（并列最近条件组，当前均受 9/24 rank1 阻断）：** a、ag、al、ap、au、b、bu、c、cf、cj、cu、eb、eg、fg、fu、hc、i、j、jd、jm、l、lh、m、ma、ni、oi、p、pb、pf、pg、pk、pp、rb、rm、rs、ru、sa、sc、sf、si、sm、sn、sr、ss、ta、ur、v、y、zn。这里的“并列”只针对已证明的历史逻辑输入窗口；没有证据将其中任何品种称为当前四周期产品 READY。

**11 个固定窗口受生命周期起点阻断品种：** ao（2023-06-19）、bz（2025-07-08）、ec（2023-08-18）、lc（2023-07-21）、pd（2025-11-27）、pl（2025-07-22）、pr（2024-08-30）、ps（2024-12-26）、pt（2025-11-27）、px（2023-09-15）、sh（2023-09-15）。日期为读回的最早合约上市日，Session 与 rank1 起点一致；矩阵的 `lifecycle_window` 验证这 44 项在各自上市后至 2026-09-23 可读。不能据此把 2023 固定目标窗口缩短后算作通过。

## 阻塞分类与未证事实

| 类别 | 当前证据 |
| --- | --- |
| 来源 1m 缺失 | 9/23 基线 49 个可读品种未见来源缺口；11 个 2023 前置段属未上市。9/24 rank1 缺失使来源无法独立判定。全物理合约前缀未验证，缺失总数 **UNKNOWN**。 |
| 仅派生缺失 | 9/23 基线无已证明的“1m 可读而目标派生缺失”案例；9/24 受共同 Map 阻断，不能据此填零。全物理前缀合计 **UNKNOWN**。 |
| Calendar/Session/Map/lifecycle | 最新 9/24 rank1 0/60，240 项共同阻断；9/23 历史起点早于 11 品种上市/Session/Map 起点，另有 44 项生命周期阻断。上市后单独探针 44/44 可读。不能将这些阻断记为待下载来源。 |
| 预热不足 | 三策略逐周期最小 Bar 数、同物理合约前缀与 owner 展示窗口关系未冻结和验算，720 项 `NOT_EVALUATED`。 |
| 产品/适配/能力 | 1m/15m/30m 无 Newow `ProductFrequency` 身份；60m 产品身份存在但正式关闭。240 项均非正式页面能力。 |
| 身份或质量冲突 | 已读目标窗口未由 MDS 报出冲突；来源 revision 与派生失效、跨合约预热、物理全前缀仍待独立核验，不能填零。 |
| 不可读/未验证 | 最初隔离工作树的 Canonical 根未指向主树，240 项均报 `PARTITION_INTEGRITY_INVALID`；这是无效配置探针，后续指定现有 Canonical 根后近月 240/240 可读。全窗带 300 秒总预算的复查仅 173 可读、44 生命周期受阻、23 未评估，故不用其未完成行替代先前完整基线。生产 persisted reader、worker 与自然运行未由本盘点验证。 |

MDS 成功严格校验所请求 owner 窗口，不等于 `SOURCE_READY`、`PRODUCT_READY` 或 `RUNTIME_READY`。D1/W1 的 `PRICE_UNAVAILABLE`/`NO_TRADE` 豁免未用于分钟。合法 Session 短尾被视为完成 Bar，真正缺分钟仍由 MDS expected endpoint 检查；本次没有自行以“60m 缺口×60”估算 1m。

## 试点推荐

**当前没有四周期全就绪品种。** 9/24 全部受共同 rank1 缺失阻断。49 个品种只在截至 9/23 的历史逻辑输入可读性上并列；以下顺序使用**已有统一 Reference 历史 RB 验收经验**与边界覆盖降低工程成本，不把工程便利冒充数据质量差异。全部仍须 9/24 Map/新鲜度、物理全前缀、预热、三策略和页面 Gate。

| 角色 | 品种 | 本次四周期窗口/末端 | 已证明输入与最小阻塞 | 推荐理由 |
| --- | --- | --- | --- | --- |
| 首选 | RB | 2023-01-03 首 Bar 至 2026-09-23 15:00 CST；1m/15m/30m/60m 为 309000/20600/10752/6280 根 | 截至 9/23 四项可读；9/24 rank1、产品/预热/物理前缀阻断 | P9 已有 RB 历史验收样本，可复用统一 Reference 验收入口；覆盖夜盘与换月。Newow 分钟 stream 身份仍须新建。 |
| 长夜盘备选 | AU、AG、SC | 同上末端；每项 1m/15m/30m/60m 为 493800/32920/16912/9800 根 | 截至 9/23 四项可读；9/24 rank1、产品/预热/物理前缀阻断 | 检验跨午夜及长夜盘 Session、短尾和完成水位。三者在本次输入证据上并列。 |
| 日盘边界 | AP | 同上末端；1m/15m/30m/60m 为 203400/13560/7232/4520 根 | 截至 9/23 四项可读；9/24 rank1、产品/预热/物理前缀阻断 | 日盘与夜盘试点形成端点对照；不能预设其数据优于 RB。 |
| 短历史补充 | PD、PT | 2025-11-27 上市至 2026-09-23 15:00 CST，上市后四项可读 | 2023 目标起点受生命周期阻断，9/24 rank1 缺失 | 用于 `WARMING`、上市边界与不缩窗的页面解释；暂不作为首个完整历史试点。 |

JM 的 2023 逻辑窗口四项可读，但 `STATUS.md` 已记录物理合约历史缺口仍是外部数据 Gate，因此不作为第一试点。49 品种之间的真正优先级仍须物理全前缀、策略预热和当前日 Map/来源新鲜度证据才能进一步区分。

## 身份、命令与复核

- 工作树：`codex/newow-four-period-audit`，基线 `develop@ff4e50bfb65ab6d60e6d97412406c06369defe44`；主树用户文件未触碰。代码产品能力为 `newow_product_capabilities_v22`，生产 DB 身份读回 `guiyi_quant` / Alembic `20260919_0047`。`STATUS.md` 的正式 Runtime 身份与本次数据查询分开。
- 生产库只读回读 RB 历史 Reference stream 共 10 条，均 disabled：Newow 三策略各 D1/W1、SuBing 15m/30m/60m/D1；forward stream 为 0。生产 persisted reader 配置与 worker 安装状态未读回，仍为未验证 Gate。
- 权威集合：`data/universe/operational_products.txt`（60 项，哈希见机器明细）。现有主树 Canonical 根由只读环境配置指定；密钥未输出。MDS 使用 `ActualDominantTradingDayQuery`，并由 `readonly_transaction` 设 repeatable-read、read-only、statement timeout、结束 rollback；无 provider、维护锁、apply、DB/Canonical/Redis 写入。
- 实际运行：`scripts/newow_four_period_readonly_audit.py --since 2023-01-01 --trading-day 2026-09-23 --timeout-seconds 300 --output ...`（现有项目环境与 Canonical 根作为进程配置）；带总预算复跑 23 项 `NOT_EVALUATED`，历史基线采用之前同入口完成的 240 项结果。另运行 2026-08-24..09-23 近月窗口、11 品种上市后窗口与 2026-09-24 当前日窗口。将这些只读结果合并到 [唯一机器矩阵](../../outputs/newow-four-period-audit-20260924/matrix.json)，其中 `baseline_limit` 与 `budgeted_repeat` 保留不同快照和超时边界；当前日 240/720 为本报告统一 `as_of` 状态。
- 最初工作树 Canonical 根误配的探针无效；正确根后的单日/近月结果已重读。独立只读 SQL 对 9/23 与 9/24 的 Map/Calendar/Session 回读分别为 `60/5/60` 与 `0/5/60`（rank1 行 / 交易所 Calendar 行 / 有效 Session 品种），支持 9/24 共同 Map 阻断分类。没有从缺失 Map 推断 1m 来源缺失。

路线图在 [四周期权威规划](../superpowers/plans/2026-09-19-newow-intraday-roadmap.md)；本盘点未执行真实下载、补数、派生、migration、Reference build、reader/worker 启用、发布或 Runtime 切换。
