# PK 周线逐品种验收（2026-09-24）

- 固定截点：`2026-09-18T07:00:00.000001Z`。D1 修复前 PK Catalog revision `2b75be99...`；来源请求仅 PK2611 的 2026-08-10 至 08-14 五个交易日，来源判定 D1 stale、旧 W1 成交额正确，无自动重试。
- D1 精确包 SHA-256 `7d5f19584313ad7ff892dfb3481b2297609a09504d37ca7990a9a27948974cbe`：仅 PK2611 2026-08 月 D1 分区、2026-08-10 turnover 一值更新；W1 零写。提交和完整回读通过。
- W1 首包在提交前 MDS cutoff 检查处停止；只读检查确认 Catalog 40/40 旧指针且 revision 不变。40 个候选文件为不可变同字节内容。查明原因是校验使用全局截点而非合约目标周终点；修正后只读候选叠加回读四合约分别返回 42、40、38、33 根目标 Bar，保留唯一 PK2611/2025-12-19 合法质量中断。
- 新 W1 精确包 SHA-256 `b11cef3e45f628ba89fe6b961d50b481a45d010ef951cd03d92b934e4ccf4517`：40 个 W1 月分区（36 新、4 旧），149 根缺周插入、4 根有 D1 来源回执支持的旧成交额冲突修复。dry-run、独立 Review、提交前后 MDS 质量回读、提交后 40/40 候选指针通过。最终 PK Catalog revision `a7452292a9460c84201eae7549520e885c9f12477fb570cdfc1fc079c08561c4`。最新物理盘点只有 1 根合法质量中断，没有缺周或值冲突。
- Candidate readiness：趋势、震荡、主升浪主视图、图表、参考交易均 READY；主力控盘、涨跌动能、照妖镜 READY。MACD 为 WARMING，震荡比较器因样本不足为 UNAVAILABLE，其余比较器 NOT_APPLICABLE；这些状态没有通过造价或降低阈值清除。
- 正式候选 Scope v15：`develop@01375ae8bb448487ba7eadca1373a5c5c548dedf`，53/60，剩余 PF/PL/PR/PX/SF/SH/SM。后端定向 277 passed；Web 测试 677 passed、1 skipped；Web build、OpenSpec strict、ruff、`git diff --check` 和独立 Review 通过。只读正式 API smoke：3 策略 × 图表/参考/MACD/比较器共 12 个 HTTP 200，PF 周线仍 409。
- 隔离真实浏览器在同一 commit、同一截点完成 PK 三策略首次导航，三者主图、状态与参考交易均加载；主升浪截图 `output/playwright/pk-weekly-v15-main-rise-20260924.png`。页面顶部非实时独立报价与“当前主力不可判定”属于独立元数据状态，不冒充图表/参考 READY。Console 仅见隔离预览按合同拒绝 `/reference-trading/streams` 的 403。预览进程已关闭。
- Release 和 Runtime promotion 尚未执行。现行受监督 Runtime 与本开发候选身份分开。
