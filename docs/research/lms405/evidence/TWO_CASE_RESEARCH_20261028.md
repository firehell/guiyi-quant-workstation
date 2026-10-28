# L.M.S 4.0.5两案研究交付检查点

范围：规则与来源统一、JM2609五月和SH2701十月案例、可重复条件评估及缺口。原版公式未完整复刻；lms-inspired-v1、active策略、Runtime、正式行情和交易配置未修改。只本地提交，不推送。

## 工作包检查点

1. **规则与证据**：既有rule-identification.csv保留规则ID和原列，扩展精确来源URL/版本日期、前置、动作、反例、未知、实现与验证状态。新增两腿合同、两案规则和工具安全约束，非作者规则单独标明。未另造全量来源库。归档起点111条/90图片；新增WRotf7lKhl后112条/90图片，25 VPLUS、35持仓、52单品种；900覆盖行仍20 PARTIAL/880 NOT_STARTED。最早索引2026-10-19，未宣称任何一天完成。300天目标不变，21/22日主序列缺口保留。
2. **定向补证**：JM正常重读G01入口、G02文章和G07/F08详情；按5月20/21日期词、JM2609、JM2609+1223检查作者搜索（日期检索显示既有持仓；合约单词出现8月材料，未将其挪入五月）。SH重读WRouYm67Bc→WRozPmaK10→WRoCCdf0i5及U03正文，日期26/27、SH2701+锁定、烧碱+解锁补搜，新增26日17:33详情WRotf7lKhl。每案新增详情分别0/1，未达20条上限；有限直接引用和关键词入口已检查，没有声称搜索全量穷尽。日期词结果已知漏文章和独立帖；未进行300天归档，也不以“没有更多”证明材料不存在。新线索保留未知，不无限寻找单篇。
3. **行情及重放**：JM冻结CSV哈希匹配，1035根复算与旧geometry完全一致；SH统一MDS读取690根，价格存在-1/+2差异。新casebook沿用旧schema，三项条件评估均INDETERMINATE，旧casebook/结果保持冻结。
4. **验证交付**：命令如下；结果记录于末节。无时序/动作合同变更，原两腿/strict-before实现未改；新增SH专用只读研究脚本复用read_local与daytime_extrema，不新增行情入口。普通证据自审，独立审查另记实际结果。

## 四层结论

- 工具：部分还原的两腿状态、时间隔离、区域观察和外部条件评估；不具备原版自动识别器身份。
- 证据：JM版本和前置区域明确；SH直接引用链及4.0.5锁定自述明确；新SH17:33版本不能自动回填。编辑后文章只有当前可见文本，历史事前可知未知。
- 价格：JM五月21日高1225/低1189.5与作者一致；SH26日白天1511对1512、27日1477对1475冲突。1m不是作者策略周期，价格一致也不证明信号一致。
- 行为：四张JM图和SH端点图都不能拼成成交链；U03有锁定后解锁一批自述，但混合系统与账户关联不足。单位动作合法不计预测成功；合格样本0、匹配率/成交/收益null、executable=false。

## 缺口分类

|类别|JM2609|SH2701|
|---|---|---|
|来源缺口|原始不可变计划版本、信号原始图和完整动作日志|编辑前21:57版本、弱侧评级与锁解锁原始记录|
|图表身份不足|四图同账户、截图时间、周期和信号Bar|SH701月份/账户、图与系统逐行绑定、截图时刻|
|本地数据|本轮冻结输入可复算，无新增下载需求|本轮指定窗口可读；价格差异未解释，不能称无数据质量风险|
|私有公式未披露|VPLUS/BBB、区域算法、站稳及循环失败阈值|弱侧评级、VPLUS、趋势破坏及许可阈值|
|人工决策未恢复|抓M、锁定后选择如何恢复原空向|先锁、解锁、再次保护的具体决策与动作时间|

**唯一下一项最有价值的问题：一次锁定后，作者凭哪个可观察条件决定解锁恢复原趋势？** 所需证据为同一4.0.5账户/物理合约的一组带周期与时间轴的信号前后图、锁定及解锁动作时间/腿方向和作者对该次选择的解释。优先围绕本案SH的10:18至15:16连续记录补证；不足时保持UNKNOWN，不扩成全公式开发或收益回测。

## 可重复命令

从仓库根运行，输出均选不存在的新路径；不覆盖冻结资产。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/research:packages/quant-core \
services/quant-api/.venv/bin/python scripts/research/lms405_jm_may_case.py \
 --input output/lms405-jm2609-may-20261016/market-read-authorized/JM2609_2026-05-20_2026-05-22_1m.csv \
 --output /tmp/lms405-jm-new.json

GUIYI_CANONICAL_DATA_ROOT=/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/canonical \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:scripts/research \
services/quant-api/.venv/bin/python scripts/research/lms405_sh_oct_case.py \
 --env-file .env --output /tmp/lms405-sh-new.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/research:packages/quant-core \
services/quant-api/.venv/bin/python scripts/research/lms405_public_casebook.py \
 --casebook docs/research/lms405/evidence/two-case-condition-casebook-20261028.json \
 --output /tmp/lms405-conditions-new.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core:scripts/research \
services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider services/quant-api/tests/lms405

git diff --check
```

SH首次沙箱内连接为LOCAL_READ_UNVERIFIED/OperationalError，随后同一只读查询在宿主允许本地连接后成功；不把连接失败当Canonical缺失。已保存本轮成功结果，重跑时Canonical修订可能改变指纹，应对比而非覆盖旧结果。脚本不打印配置、SQL或原始异常。

## 实际验证

- 定向pytest：67 passed in 1.42s。首次资料清理后66 passed/1 failed，根因是旧测试把“既有索引”占位文字作为验收条件；改为确认KEYBAR原公式缺口仍存在后67通过。未改原公式或时序合同。
- `python3 /tmp/lms_archive_validate.py`：112来源、90图片SHA256、900覆盖行，元数据/引用/附件/排序/统计一致，通过。
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/research:packages/quant-core services/quant-api/.venv/bin/python /tmp/lms405-20261028/verify.py`：JM冻结结果完全相同；新casebook重复结果与提交JSON相同；三项INDETERMINATE及null口径、来源ID/URL、时间空列、文档链接、三个CLI拒绝覆盖且原字节未变，全部通过。临时验证脚本是本轮检查记录，长期复算使用上节仓库内命令。
- SH同一仓库脚本两次真实MDS只读：均690根，去除实际读取时间后结果完全相同，OHLC SHA256 `a48fea800e76457a521785ca0b82a634c232f79b7ac60e1ae29f924ee70ef3ca`。不代表未来Canonical修订后必然同指纹。
- `services/quant-api/.venv/bin/python -m ruff check scripts/research/lms405_sh_oct_case.py services/quant-api/tests/lms405/test_validation_package.py`：All checks passed。
- `python3 scripts/engineering/secret_scan.py --json docs/research/lms405 docs/research/lms-source-archive scripts/research/lms405_sh_oct_case.py`：0 findings。
- 独立Review发现机器时间表漏U03，已补；K03全部命名来源不足，已降为部分来源关联/名称待核，不假称完整定位。无动作/时序合同变更。以上修正后的定向回归和资料校验已重跑。
- `git -c core.fsmonitor=false diff --check`：通过。Git默认fsmonitor IPC报错，禁用本命令的fsmonitor后读回；未改全局或仓库配置。

本地研究交付验收：COMPLETED，允许继续规则识别研究；不代表原版完全复刻、可执行候选、发布或Runtime验收。远程推送限制仍遵守。
