# 2026-09-21—2026-09-22 盘后恢复只读计划

生成时间：2026-09-22 22:45 CST。

## 身份与边界

- 现役 Runtime：`/Volumes/扩展盘/guiyi-quant-runtime-v1.10.18-r1`
- 现役身份：`v1.10.18@ec1dd21f7bed7b04018350058edd3f2bc94cbabf`
- 盘后状态 SHA-256：`b810c75ede127cc001819fb55cfeb65ada2e16f78c8fb0face4df58f9634ea10`
- 候选 Runtime：`/Volumes/扩展盘/guiyi-quant-runtime-v1.10.19-r1`
- 候选身份：`v1.10.19@879f76e4c115cc87bd9de78331002f084465fe33`
- operational 数量：60；顺序化 JSON SHA-256：`f71bd64943beecb0e01dd420add827e3f7f9402f020c45c6988192b7e56da2c6`
- 正式周期：`1m`、`5m`、`15m`、`30m`、`60m`、`1d`、`1w`
- 本文件只冻结只读现场证据；不授权或执行 provider、Canonical、Catalog、Redis、Runtime 写入。

## 官方 dry-run 结果

现役 v1.10.18 与候选 v1.10.19 的 `data daily-recovery --through 2026-09-22` 均在计划生成前返回：

```text
status=error
readonly=true
error.code=CLI_INTERNAL_ERROR
error.type=ValueError
```

因此当前没有合法的 `plan_sha256`、完整 expected/missing bar-end hash 或可供 `--apply` 使用的 CAS 计划。
不得根据下面的范围清单执行恢复。

## 2026-09-22 权威冻结范围

- 合约权威：immutable Live subscription snapshot，60/60。
- MainContractMap 候选映射 SHA-256：`fccaec3b9c14e7a5e23933e0db7939e295ddc34136d4c960e3096e70c654e040`
- 七周期、2026-09 月物理月分区：420 个；目标清单 SHA-256：`aea69753e5b3ad8bb83dd7faf769e52178a6997f66442f723dccb4f2f95d9b68`

```text
a=A2611 ag=AG2610 al=AL2611 ao=AO2701 ap=AP2701 au=AU2610
b=B2611 bu=BU2610 bz=BZ2610 c=C2611 cf=CF2701 cj=CJ2701
cu=CU2610 eb=EB2611 ec=EC2610 eg=EG2610 fg=FG2701 fu=FU2611
hc=HC2701 i=I2701 j=J2701 jd=JD2611 jm=JM2701 l=L2701
lc=LC2701 lh=LH2611 m=M2701 ma=MA2610 ni=NI2610 oi=OI2701
p=P2701 pb=PB2611 pd=PD2612 pf=PF2611 pg=PG2611 pk=PK2611
pl=PL2611 pp=PP2701 pr=PR2611 ps=PS2611 pt=PT2612 px=PX2611
rb=RB2701 rm=RM2611 rs=RS2701 ru=RU2701 sa=SA2701 sc=SC2611
sf=SF2611 sh=SH2611 si=SI2611 sm=SM2611 sn=SN2610 sr=SR2701
ss=SS2611 ta=TA2701 ur=UR2701 v=V2701 y=Y2701 zn=ZN2611
```

每个映射项对应上述七个频率的 `2026/09` contract dataset 月分区；实际 expected/missing bar ends 仍必须由成功的官方 dry-run 冻结。

## 2026-09-21 非权威候选范围

- 当日 immutable subscription snapshot 已缺失。
- 从 60 个品种残留 1m Live Bar provenance 各恢复到唯一物理合约，60/60，无多合约冲突。
- provenance 映射 SHA-256：`6c00fe56b7b7e8ff4e78da4ccc6b4412cc8fa8cc2aab3e141424c6fd1df25fe1`
- 七周期、2026-09 月候选物理月分区：420 个；候选清单 SHA-256：`4e39fcc5cd2daeccd5048987000c871f34d08bbb1f8f81f1108d5831989ca30b`

```text
a=A2611 ag=AG2610 al=AL2611 ao=AO2701 ap=AP2701 au=AU2610
b=B2611 bu=BU2610 bz=BZ2610 c=C2611 cf=CF2701 cj=CJ2701
cu=CU2610 eb=EB2610 ec=EC2610 eg=EG2610 fg=FG2701 fu=FU2611
hc=HC2701 i=I2701 j=J2701 jd=JD2611 jm=JM2701 l=L2701
lc=LC2701 lh=LH2611 m=M2701 ma=MA2610 ni=NI2610 oi=OI2701
p=P2701 pb=PB2611 pd=PD2610 pf=PF2611 pg=PG2611 pk=PK2611
pl=PL2611 pp=PP2701 pr=PR2611 ps=PS2611 pt=PT2612 px=PX2611
rb=RB2701 rm=RM2611 rs=RS2701 ru=RU2701 sa=SA2701 sc=SC2611
sf=SF2611 sh=SH2611 si=SI2611 sm=SM2611 sn=SN2610 sr=SR2701
ss=SS2611 ta=TA2701 ur=UR2701 v=V2701 y=Y2701 zn=ZN2611
```

该映射只能作为调查候选，不能替代正式 snapshot 或 provider metadata authority，不能直接作为预期 MainContractMap 写入。与 9 月 22 日相比，`eb` 从 `EB2610` 切换到 `EB2611`，`pd` 从 `PD2610` 切换到 `PD2612`。

## Runtime promotion Gate

候选和现役代码分别执行官方 `market-runtime-preflight`，结果一致：

```text
status=blocked
reason=MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE
trading_day=null
operational_count=60
snapshot_count=0
```

现役服务只读状态仍显示 API、Web、Live、Alert 正常运行，after-market 为 schedule-only `not_running`，但 Runtime health 为 failed。按部署合同，在 preflight 未通过前不得调用安装器，故本次没有进行 Runtime promotion。

追加的生产 Catalog 只读核对显示：2026-09-22 有 5 条权威 Calendar、60 个品种共 225 条有效 Session；2026-09-23 的 Calendar 为 0、有效 Session 为 0。当前夜盘阶段无法解析下一交易日 authority，与 preflight 的 `trading_day=null` 一致，是本次 promotion 的直接现场阻断条件。

## 后续解除条件

1. 补齐并验证 2026-09-23 权威 Calendar、Session 与当日 rank1 metadata 需要单独的数据写入授权；本计划不含该授权。
2. 不得用 override、Bar provenance 或 synthetic snapshot 替代 metadata authority。
3. preflight 必须自然返回允许的 `snapshot_ready`、`after_market_complete`、`before_first_session` 或 `non_trading_interval` 之一。
4. promotion 后重新运行官方 `daily-recovery` dry-run；只有取得完整 target windows 与 lowercase `plan_sha256`，才形成可审批的数据恢复计划。

## 22:50 授权后执行结果

Owner 已明确授权 2026-09-23 的 current-day metadata capture 与 Calendar/Session/rank1 写入。按 v1.10.19 三阶段入口执行唯一一次 capture，但命令在 provider 构造和调用之前返回：

```text
status=error
readonly=false
error.code=CLI_INTERNAL_ERROR
error.type=ValueError
snapshot_bytes=0
```

实现核对确认 `RuntimeDataBinding._validate_status` 只接受存在 `current_run` 的运行中状态，或 schema-v5 `AFTER_MARKET_INTERRUPTED` 终态；当前现役状态是 schema-v3 `failed/UPDATE_FAILED`，因此合法失败终态无法进入 current-day metadata recovery。不能改用绕过 Runtime binding 的直接写库脚本，也不能用不写 MainContractMap 的通用 `metadata-repair` 冒充完成。

失败后独立读回：2026-09-23 Calendar=0、有效 Session=0、rank1=0；现役 after-market status SHA-256 仍为 `b810c75ede127cc001819fb55cfeb65ada2e16f78c8fb0face4df58f9634ea10`。本次实际 provider 请求为 0，生产写入为 0。
