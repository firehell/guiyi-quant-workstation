# 2026-10-16 全量可发布代码汇总

用户交办汇总可发布代码、发布并切换。发布范围为已验收 develop 91655d9ec、现有 v1.15.10 版本准备088ff048d及已发布 main v1.15.9；合并候选44af6ed35。
相对 v1.15.9 为556个文件，不能把相对develop的3文件当作全部发布范围。

历史未合并分支含旧Scope、候选研究和维护记录，不自动合入；未跟踪output及其他worktree保留。
既有八批专项验证及真实浏览器证据见 watch-eight-batches.md；真实参考收益来源503保留未完成项。

## 本轮验证

- NODE_OPTIONS=--max-old-space-size=512 pnpm -C apps/quant-web test：1133 passed，3 skipped。
- 发布Runtime/绑定/交接/定时/质量重暖/通知handoff/provider/研究API/能力合同定向pytest：185 passed。
- NODE_OPTIONS=--max-old-space-size=768 pnpm -C apps/quant-web build：类型、build、topology通过。
- openspec validate --specs --strict --no-interactive：11 passed。
- python3 scripts/engineering/secret_scan.py --json：零发现；git diff --check通过。
- 新独立caller定向pytest：76 passed；独立Review修正项复核通过。

## 切换边界

现役10服务为v1.15.7 / gen19 / schema0051。候选不能与旧Feed混用合同；需全10服务闭市冷切换及0052兼容验证。
本轮只读60品种Session与当日自然18:05盘后Gate通过；Reference实测720启用：508 READY、212 DATA_CONFLICT、pending0，完整就绪Gate失败；禁止drain及切换。
未停止、drain或修改现役服务，未执行migration。
独立Review发现旧caller用v7算法生成候选合同，已在新独立caller以候选自身进程算法隔离修正；旧绑定仍按v7校验。
