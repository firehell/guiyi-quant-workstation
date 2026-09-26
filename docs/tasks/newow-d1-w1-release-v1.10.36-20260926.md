# 牛哇日周发布与本机切换（2026-09-26）

最终发布 `v1.10.36@4d25ed21bcf51adb662ec44757ac8974f8c24e44`，PR #401。
正式根 `/Users/zhangzhao/Library/Application Support/GuiyiQuant/runtime-v1.10.36`，独立 Git 存储，detached、clean。
Release：https://github.com/firehell/guiyi-quant-workstation/releases/tag/v1.10.36

## 发布过程与确认修复

初次发布 v1.10.35（PR #400）后的真实 RS 日线默认入口返回 500。
只读对比证实：默认 daily-snapshot 仍使用 V1，遇到正式 DAILY_V2 来源质量事实报
SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED；同一真实输入以 DAILY_V2 可正常解析9/24。
补丁为默认日线 resolver/reader/chart service 绑定正式政策，与 strategy-detail 一致；
没有改公式、数据、预热、周线或增加 fallback。v1.10.35 tag 未挪动，Release 说明标为已被替代。
新回归保留真正 builder 与 resolve，避免旧 lambda *_args 绕过政策传递。

发布合并保留已验收 develop 应用/测试/canonical 的一致身份；逐文件独立核对现役
节假日晚到恢复、一次重试、夜盘 Session authority 已在该实现，不退回历史 API/类型。
后续真实 RS 回读揭示默认D1政策链漏接，已单独修复并在最终版验收，不以初次352测试证明该入口通过。

## 最终验证及证据

证据目录 `outputs/newow-release-v1.10.36-20260926/`；初次发布过程保留在对应v1.10.35目录。

- 初次候选352后端、714前端通过（1跳过）；最终补丁259定向测试通过，独立178通过。
- 正式路由+真实数据只读60/60默认日线快照HTTP200/current，截至9/24；RS三策略均通过。
  精确候选 `4c3fcbb4a0fb7302fdec519638dcfa290a062393` 与最终tag源码树无差异。
- 最终独立root冻结依赖安装、vue-tsc/生产build/入口拓扑通过；四个版本事实源均1.10.36。
- 两轮独立Review通过；secret scan唯一命中为合成Reader.token测试标识，已独立判为误报，未冒称原始scan passed。
- promotion前及market安装器内部预检passed/non_trading_interval，operational60、snapshot0。
- 实际安装base/market/alert/weekly各exit0；reference worker仍disabled，不增加Scope或受众。
- `runtime-readback-final.log`：API/Web/Live/Alert running，同exact root/commit；after-market/late-provider schedule-only idle正常。
  API/Web HTTP200、Runtime ok readonly=true；没有手工运行盘后、延后恢复、周审计或发通知。
- 正式API五组JM D1/W1、RS震荡D1/W1、AO W1三层均same token/as_of9/24。
  JM三层READY；RS三层WARMING；AO主图/参考READY、辅助WARMING；没有强行READY。
- 正式浏览器JM日周正常，RS日线500已消失、日周保持正常积累预热；AO当前可计算与历史预热正确区分。
- 当前报价如显示可用，明确为9/24已完成日线收盘、非实时；未更新历史保留场景沿用独立D1/W1受控验收。

## 保留的边界与恢复

本次完成RELEASED及Runtime切换/现场页面读回；尚不声明自然RUNTIME_READY。
9/28下一交易日的completed Bar与自然盘后增量仍待发生；新根weekly audit结果尚未知。
旧v1.10.34根的自然全历史周审计有3条RS2609 EXPECTED_PARTITION_MISSING（2025-11、2026-08、2026-09），
本次未修这些旧合约全生命周期审计finding，不把日周策略窗口验收说成所有历史零缺口。
P9持久化“统一参考交易”面板503仍保留；牛哇页面参考投影已通过，二者不混称。
小时及综合解释维持既有未开放边界，RS样本不足正常每日增量积累。
没有migration、生产DB/Canonical改写、provider下载或reference-worker激活。
旧v1.10.34/35根与状态保留；v1.10.34为原可用恢复基线，v1.10.35仅保留发布失败诊断，
不能把含RS默认入口问题的v1.10.35当作已完全验收回退版本。
切换前两个旧根均无待处理late-provider状态，无未消费延后检查被丢弃；没有复制自然after-market/weekly状态冒充新根验收。

唯一下一步：核对9/28自然日周增量与页面持续更新，保持现有运行范围。
