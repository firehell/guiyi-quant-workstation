# Newow v1.10.37 发布记录

正式身份 `v1.10.37@07cdb4b7b72c1fa003d25bf2b47b3c3de127c8a4`，PR #402。
候选 `0725157a08c7459e387eda3dbc9aed4f05243796` 与 main 发布源码树一致；annotated tag、正式非草稿 Release 和合并关系已回读。
Release：https://github.com/firehell/guiyi-quant-workstation/releases/tag/v1.10.37

本版本汇总 v1.10.36 之后的 Newow 页面与独立参考研究显示改动。

- 改善主图标签靠近 K 线的碰撞布局，保留原始动作与交易记录。
- 修复副图计算区段匹配、绘图高度与工具栏挤压；黄色量柱按满足条件显示，跨策略一致。
- 精简自动加载、收益曲线说明、日期轴、统计卡片和等待状态布局。
- 收益标签统一为近3月、近1年、近3年、今年、理论值、全部，按维护历史与上市起点截取。
- 增加独立回看理论值与页面年化显示，原始参考交易价格不变；理论值非可执行收益。
- 增加独立双策略融合参考和 CDV2 综合解释、显式来源的跨周期价格；保留未开放、缺失与计算段隔离。

验证：功能及工程定向回归 572 passed，两个工程断言为 v1.10.36 已有失败；前端 726 passed / 1 skipped，生产构建通过；新增模块 Ruff、Newow canonical 校验和独立代码复核通过。本地真实 JM 普通累计 183.66 百分点、理论累计 371.60 百分点，窗口切换与原始记录保持已浏览器验收。

已知边界：普通曲线仍是已完成页面参考交易简单累计，尚未复刻持仓浮动权益曲线；非账户或因果可执行收益。正式 reader 默认 legacy；persisted reader 尚不提供理论值，未在本版本启用。P9持久化面板既有不可用、部分历史/预热与自然 Runtime 验收边界保持。全仓 OpenSpec 尚有未修改 reference-trading spec 的既有失败；secret scan 唯一既有命中为合成 Reader.token 测试标识。两个工程断言为截图库存和旧 AGENTS 固定措辞，未改动相关源文件。

发布不切换正式 Runtime，不改变数据、通知范围、策略激活或 auto_order=false。

## 2026-09-26 正式 Runtime 切换

owner 明确“开始切换”后执行。新根 `/Users/zhangzhao/Library/Application Support/GuiyiQuant/runtime-v1.10.37` 为独立 Git、detached at exact tag commit、clean；旧 v1.10.36 根保留。冻结 uv/pnpm 安装和 Web build 通过。render-only 与两次 market promotion preflight 均 passed/non_trading_interval；base、market、alert、weekly 四组 installer 均 loaded=true。

`local-services-status.sh` overall=passed，API/Web HTTP200，API/Web/Live/Alert 运行根与 loaded_commit 均为 v1.10.37/07cdb4b7。after-market/late-provider 为正常 schedule-only idle，weekly已装载；reference worker仍关闭。原 Scope、audience和配置路径保留，没有补发、历史重跑、来源下载、migration或Canonical改写。

只读 `/api/runtime/health` 顶层 ok；非交易时段60品种 CLOSED/subscribed0，尚无新completed Bar，coverage unverified；新根after_market pending、weekly missed/through未知。Alert processing ok，但历史notification失败仍degraded。切换前旧根after_market missed、weekly 23 finding和告警历史保留，不能用新根空状态认定修复。

正式浏览器JM主图、MACD、六窗口、年化32.2%和普通累计183.66/74笔可见。正式reference API ready，理论值74笔累计371.5988631491555399359207894，hindsight=true/executable=false；原始记录可见。但本次浏览器点击理论值仍保留普通曲线，未将该交互计为通过，待修正。P9持久化面板仍为既有503。截图与服务读回见 outputs/newow-release-v1.10.37-20260926。

恢复：旧根exact v1.10.36 clean且保留；两版本ops脚本和after_market状态合同未变，无schema migration。专门的schema-v5 interruption recovery proof不适用于旧schema3无interruption现场，其尝试返回ValueError，不能称该proof通过；正常nontrading promotion preflight通过。若需回退，应从旧根render/preflight后运行原installer四组并重新读取root/commit/health；不复制新旧运行状态。

状态：RELEASED，Runtime promotion与现场服务回读完成；自然RUNTIME_READY未验收。下一步先修正正式收益窗口/理论值交互，再以9/28新completed observation、盘后和weekly实际结果完成自然验收。
