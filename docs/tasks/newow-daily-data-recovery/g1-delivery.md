# G1 审计链路续接记录

日期：2026-09-16。范围仅为 D1 审计入口与结果捕获的隔离工程收口；未运行生产审计、RQData、
Canonical/DB/Redis 写入、Runtime、通知、main/tag/release 或 Broker 操作。

## 已冻结工程合同

- 正式入口：`python -m scripts.newow_daily_recovery_verification`。
- 内部完整 operational D1 audit：`matrix=false`、`frequency_scope=[1d]`、`max_work=10000`、
  deadline 300 秒；父进程 timeout 330 秒。
- 已知执行使用 exact campaign/execution hash；零普通目标仅允许 completed、零分母、零 child campaign
  使用 `--execution-not-required`，不生成空 execution receipt。
- timeout、非 0/1 return code、结果缺失、空文件和损坏 JSON 分别 fail-closed；不覆盖旧观察、不 retry，
  不把空文件或宿主 `exit=-1` 解释为业务成功。
- return code 必须与 verification status/完成布尔值一致；JSON/Markdown 仅在临时文件完整写入并 fsync 后
  以原子 no-replace 发布，并发同名目标不会被覆盖；JSON 随即结构化回读。零目标 D1 `apply` 在创建
  attempt 前拒绝。

## 下一次现场只读审计的具体范围

下一次只能作为 G2-A 的新单次观察意图执行：目标工作站为现有归一量化本地工作站；执行根必须是本次
develop 集成后读回的 exact commit 的干净冻结 checkout；品种固定为 `operational_products.txt` 的完整集合及
其 hash；只审 `1d`，固定一个新的带时区 `as_of`，`matrix=false`、`max_work=10000`、audit deadline 300 秒；
使用一个新的持久 evidence root/observation id。运行后必须同时保留命令终态、真实 return code、非空
`verification.json`，并校验 schema、readonly、provider_requests=0、writes=0、完整枚举、预算状态和 Comparator
证明。锁忙、超时、结果缺失/损坏或身份漂移均停止，不扩大预算、不重复启动、不生成 prepare/apply。

该范围仍需 owner 对 exact commit、`as_of`、evidence root 和 observation id 给出新的 G2-A 单次意图；
G1 完成不自动授权这次现场读取。
