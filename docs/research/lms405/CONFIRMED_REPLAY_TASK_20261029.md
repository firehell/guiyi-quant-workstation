# 人工确认连续研究回放任务

基线 develop 2576cf890；只本地提交，不推送、发布或切 Runtime。新身份 `lms-confirmed-replay-v1`；复用既有关键K及建议公式，不恢复私有规则。

## 批次与验收

1. 确认合同与核心：无 ACCEPT 不推进，精确前像、严格时序、下一 completed Bar 过期、幂等和 checkpoint；先失败测试。
2. 离线工具：逐 Bar 揭示，决定草稿导出→CLI验证→重开报告；建议、决定、转换分开。零默认确认，拒绝覆盖。
3. 边界与恢复：LMS 定向测试、进程稳定、拒覆盖、页面操作及未参与实现的独立 Review。
4. 固定样本：A 旧hash，B JM2701 2026-09-21至10-09，C SH2701 2026-10-26至27；仅 MDS 5m，缺失记录阻断，不修复或替代。均开发检查，非OOS。
5. 手册收敛与剩余规则矩阵：人工确认选择已确定；下一项首次入场与退出独立候选合同。

## 检查点

- 现场 branch/HEAD/worktree 已核对，原型不重做；原冻结产物保持。
- 样本只读查询及源条目重算结果见 `output/lms-confirmed-samples-20261029/availability.json`。
- 工程实现、测试、Review最终结果由主执行者在本文件补录。

## 2026-10-29实际交付检查点

- 新核心 `packages/quant-core/guiyi_quant/lms_confirmed_replay.py` 与离线 CLI `scripts/research/lms_confirmed_replay.py` 已实现。确认只使用生成建议的动作；精确状态、版本、合约、时区、strict-after、下一Bar过期（等时过期优先）、同刻冲突、幂等与迟到保护均显式校验。状态只在known_at推进，原方向不变；Fill/performance=null、executable=false。
- checkpoint采用完整输入前缀重算校验后接续，不信任文件中的状态。恢复需提供原始Bar前缀；这是本地小规模研究的简单恢复合同，不是增量性能优化。
- 页面逐Bar揭示，Python预算各前缀；JS仅编辑草稿。导出包含当前可信决定前缀及新增草稿，导入不应用状态。历史研究游标时间与实际recorded_at分开。CLI以新目录输出、拒覆盖、INCOMPLETE/COMPLETE区分中断，绑定输入、确认原文件、checkpoint与四份源码hash。
- 独立Review发现并修复：后到ID篡改撤销历史接受、非法ID类型异常、显式错误公式版本未拒绝、页面连续导出遗漏既有决定。另补显式completed/start校验及原确认文件hash。各修正均有回归；既有关键K/建议公式未改。
- 第一轮沙箱Catalog访问失败只代表网络访问阻断。宿主批准精确只读复核后，B/C均可读；权威Session/request identity/coverage与新CSV在`output/lms-confirmed-samples-provenance-20261029/`，逐行比对原始JSON一致。未下载或修复行情。
- 最终报告根：`output/lms-confirmed-final-verified-20261029/`。A、JM2701、SH2701均为开发/跨样本检查，不是盲测或OOS；默认LONG单位初始前像，人工确认0、转换0。各首Bar ibar因无前像不可判定1，未把unknown当匹配。

| 样本 | Bar | ibar | pinbar | 建议 | 过期 | 用户确认 | 转换 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A JM2509 |138|21|7|5|5|0|0|
| B JM2701 |573|61|55|21|21|0|0|
| C SH2701 |138|10|10|3|3|0|0|

A独立TEST_FIXTURE演示接受1次、转换1次，用户操作计数仍0；另有篡改状态指纹拒绝演示。完整多→锁→多、空→锁→空使用合成fixture测试，不计市场匹配分母。作者可对齐样本仍0，准确率/Fill/收益仍null。

验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core:scripts/research services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/lms405` → 158 passed、1 skipped（API环境缺matplotlib）；系统Python单跑`test_keybar_replay.py`补真实渲染。`/tmp/lms_final_evidence.py`运行两个独立CLI进程逐文件字节一致、拒覆盖前后原字节不变、fixture及篡改拒绝路径；`node --check output/lms-confirmed-final-verified-20261029/ui.js`通过。

实际页面点击/下载尚未验：宿主拒绝file://，仅允许http/https，并明确禁止用替代路径或浏览器规避同目标，因此未绕过。静态JS语法和CLI验证不能冒充实际点击验收；此项保留`EXTERNAL_GATE_PENDING`，本批工程为PARTIAL，不声明完整浏览器闭环。

归档现场重算：`docs/research/lms-source-archive/index.csv`126条、91张独立图片可读并hash；`lms405/sources.csv`另58条，分母不混用，未重启300天归档。

唯一研究下一项仍为首次入场与退出独立候选合同；当前交付只覆盖人工确认连续研究工具，不是完整原版复刻、Paper、实盘或收益闭环。未推送、发布、切Runtime、通知或接Broker。

## 本地复算入口

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/quant-core:scripts/research services/quant-api/.venv/bin/python scripts/research/lms_confirmed_replay.py --input output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv --input-sha256 71c668cc3874cfdcb1c52b47c26615a89ed455977bfb5c80883a9e18b3cb91b3 --initial-state output/lms-confirmed-replay-20261029/initial-long.json --output /tmp/lms-confirmed-new-report
```

输出路径必须全新。页面导出后在同一命令增加`--decisions /精确路径/research-decisions.json`并更换output。恢复可另加`--checkpoint /先前报告/checkpoint.json`，仍需完整相同Bar前缀；晚于checkpoint的新决定才允许追加，不回写历史。没有确认文件则不传decisions。B/C使用provenance目录内对应CSV与initial JSON，hash取provenance记录，不能沿用A hash。

最终独立Review复核：核心与CLI独立运行31 passed，未发现重要Confirmed Issue。系统Python真实渲染实际5 passed；ruff与secret scan及最终现场检查结果随本地提交保存。本阶段允许本地提交，不包含远程集成或发布授权。
