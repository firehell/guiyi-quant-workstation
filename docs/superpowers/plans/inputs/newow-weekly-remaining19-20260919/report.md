# 剩余 19 品种牛哇周线只读盘点

日期：2026-09-19。状态：只读调查完成；原生 readiness 为 `incomplete`，不允许据此开放剩余 19 品种。

## 检查身份与边界

- 主工作区：develop@a23475c3d08debabc416f1300c8b58e0984c7ab4；已有用户计划文档未修改。
- 全量审计使用正式 v1.10.17@305cf36b94121dff37d6ce280f98869d979a2b8b 的代码与既有私有配置。
- 统一截止：2026-09-18T07:00:00.000001+00:00（北京时间 15:00:00.000001）。
- 一次 REPEATABLE READ / READ ONLY 事务；审计前、事务结束及新事务读回的 Catalog 修订一致。
- 修订：`e8450448b08f833ee7f4990856dc9f9937c35aa3fad040c89e172526e3ffa64c`。
- 耗时约 270 秒，无预算耗尽，provider_requests=0、writes=0。完整报告及未知错误诊断分别保存，不覆盖原始失败。

## 第一项：首批 41 品种部署后首载验收

- STATUS.md、已归档任务“设计周线质量链后续方案”末轮和原始 32 条报告均未证明当前 Runtime 本机/公网各 123 页通过。发布与 Runtime promotion 已完成，但首载 Gate 尚未关闭。
- 本次 API 只读读回 version=1.10.17、status=ok、readonly=true；沙箱内初次连接失败不能推断服务停机。
- 本次补跑随后由审计者主动停止，以保留本轮证据核对及 19 品种盘点范围；7 个组合通过，1 个正在进行的组合被中断，其余未检。中断不归因于产品故障，不计作 123/123。
- 本机既有 project.env 及当前环境未配置 PUBLIC_BASE_URL/BASIC_AUTH_USER/BASIC_AUTH_PASS；未取得本轮公网验收证据。
- 第二项自然 Live、盘后、weekly audit、完整新周及换月接续继续等待各自自然证据。本次未触发定时任务。

## 第三项：全量结果

- 19/19 品种均已进入审计；784 条依赖记录包含 chart/reference 不同截止，不能当成 784 个物理合约。
- DATA_READY 154、NOT_APPLICABLE 20、端点缺失 500、完整性冲突 40、来源异常 8、UNKNOWN 62。
- 正式周线三策略 57/57 为 UNOPENED；没有绕过产品开关生成策略或页面通过结论。
- 0/19 达到全部消费历史依赖通过；这不意味着每个当前物理合约都缺失。

下表按物理合约去重计数，各列可重叠；0 仅表示本次该分类未报告，不保证消除先前错误后没有后续缺口。

| 品种 | 已知端点缺口合约 | W1/D1 数值冲突合约 | 旧 reader 解析异常合约 | 非正源价合约 | 原生补齐提案/待审 |
|---|---:|---:|---:|---:|---|
| B | 0 | 7 | 0 | 0 | 0 / 0 |
| BZ | 2 | 3 | 0 | 0 | 2 / 0 |
| CJ | 0 | 8 | 0 | 1 | 0 / 0 |
| EB | 30 | 1 | 0 | 0 | 30 / 0 |
| EG | 3 | 1 | 0 | 0 | 3 / 0 |
| J | 5 | 0 | 0 | 0 | 5 / 0 |
| OI | 11 | 0 | 2 | 0 | 11 / 0 |
| PF | 34 | 0 | 6 | 0 | 0 / 34 |
| PG | 25 | 0 | 0 | 0 | 25 / 0 |
| PK | 17 | 0 | 1 | 0 | 14 / 3 |
| PL | 1 | 0 | 4 | 0 | 0 / 1 |
| PR | 9 | 0 | 6 | 0 | 1 / 8 |
| PX | 8 | 0 | 3 | 0 | 3 / 5 |
| RS | 8 | 0 | 1 | 2 | 0 / 8 |
| SF | 25 | 0 | 3 | 0 | 5 / 20 |
| SH | 8 | 0 | 2 | 0 | 5 / 3 |
| SI | 25 | 0 | 0 | 0 | 25 / 0 |
| SM | 17 | 0 | 2 | 0 | 9 / 8 |
| SR | 14 | 0 | 0 | 0 | 13 / 1 |

## 已定位原因与处理顺序

1. **先处理质量类型兼容和周线消费合同。** OI、PF、PK、PL、PR、PX、RS、SF、SH、SM 的 62 条 UNKNOWN 去重为 31 个合约/截止依赖。现役代码均在 PriceUnavailableFact.from_record 抛出 SOURCE_QUALITY_EVIDENCE_INVALID；当前 develop 定向只读复现为 30 项 SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED、1 项 OI2609 的 REPLAY_ENDPOINTS_MISSING。develop 已有 NONPOSITIVE_CLOSE 类型，但既有 W1 的 D1 入口明确只接受 PriceUnavailableFact。不能靠重新下载或放宽校验消除；先确定 W1 对新来源质量事实的处理合同，再实现并独立验证。定向 develop 诊断不替代新版完整矩阵或发布。

2. **核对 20 个合约的 W1/D1 冲突。** B 7、BZ 3、CJ 8、EB 1、EG 1；逐项复现均为 WEEKLY_SOURCE_BAR_CONFLICT，触发位置是现存 W1 与权威 D1 周聚合值不相等。应比较 OHLCV/成交额/持仓量及来源修订，确认差异原因后冻结修复目标，不直接覆盖。具体合约及首个冲突日见 summary.json / readiness-full.json。

3. **保留来源异常事实。** CJ2305、RS2309、RS2311 的非正源价需按物理合约、日期及来源分类处理；不能当普通缺口补成有效行情。

4. **按品种组织补齐批次。** J、PG、SI 目前为较清晰的缺口组：分别 5/25/25 个原生 PROPOSED 合约提案，估算请求分别 80/538/438；SR 14 个缺口合约中仍有 1 项 REVIEW_REQUIRED。其他品种需与前述质量/冲突项合并审查。原生全量共 151 个 PROPOSED、91 个 REVIEW_REQUIRED；151 项估算 2826 次请求只是现有提案量，不是已批准下载预算，也不是全部缺口总预算。真实写入需重新冻结精确合约、窗口、目标及 plan hash，并包含恢复与幂等边界。

5. **修复后再验能力。** 同截点重验全部 19 数据依赖，再以隔离候选完成 19×3=57 的主图、辅助、参考交易及页面默认首载，保留合法预热和中断；随后集成、发布、Runtime 和自然接续分别验收。

## 验证及产物

- audit_remaining19.py：正式 exact-tag 原生只读审计，命令退出 0；readiness 状态 incomplete，不冒充通过。
- diagnose_unknown.py：正式 reader 31 项有界复现。
- diagnose_unknown_develop.py：develop 同依赖复现；30 项不支持的质量分类，1 项端点缺口。
- diagnose_integrity.py：正式 reader 20 个冲突合约全部复现为 WEEKLY_SOURCE_BAR_CONFLICT。
- readiness-full.json：完整原生报告，包含精确合约、消费窗口、目标分区及可用的 plan hash。
- summary.json：逐品种聚合，不另查询数据；audit-identity.json 保存统一截点和修订校验。
- 本次只新增任务证据，未改变 STATUS.md、能力开关、源码、Canonical、生产数据库或 Runtime。

**最小下一步：收敛 W1 对 NONPOSITIVE_CLOSE 来源质量事实的消费合同与兼容处理，再冻结数据修复批次。剩余 19 品种正式开放：阻塞。**
