# v1.10.31 精确候选发布 Review（2026-09-24）

- 候选：`ff012744e4ed1781b7ae56d5b6c153957d29de92`，从 `v1.10.30@120c5c9490b9909bb64b2e55a5fb5893e57a04c0` 建立，合入 `develop@10e6805665ede2cff18c3ebd40808dad11471529`，PR [#394](https://github.com/firehell/guiyi-quant-workstation/pull/394) 保持草稿。
- 范围：新增 PF、PK、PL、PR、PX、RS、SF、SH、SM、SR 的正式 W1；共 60/60。周线 v2 固定 19 品种。1h 和完整跨周期解释仍未开放。固定截点 `2026-09-18T07:00:00.000001Z`。
- 真实只读策略矩阵：W1 v1 组 41 品种 123/123 READY；W1 v2 组 19 品种 56 READY、RS 震荡 1 WARMING。共 180/180 有确定状态；两份报告 `audited/complete`，预算未耗尽，provider 请求和写入均为 0。D1 180 项为 150 READY、30 UNKNOWN，报告 `incomplete`；UNKNOWN 是 OI、PF、PK、PL、PR、PX、RS、SF、SH、SM 各三策略，根因 `SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED`，底层事实为 `NonpositiveCloseFact`。OI 在现役 v1.10.30 同样复现。
- 精确候选真实浏览器首载：W1 180 个唯一品种×策略主图状态均与策略审计一致；179 个参考摘要自动可见。RS 震荡首载主图 WARMING，参考段显示“尚未请求”，点击“读取参考交易”后参考摘要正确显示 WARMING 与历史覆盖。原全量脚本强制 180 个摘要自动可见，因此 179/180、Playwright 退出 1；定向 RS 交互复核 1 passed。D1 180 个唯一组合页面检查 1 passed，150 READY、30 unavailable，与策略审计逐项一致；30 项无虚构参考摘要。
- 候选验证：最终定向后端 269 passed；Web 单元 684 passed、1 skipped，build 成功；OpenSpec 10/10；定向 Ruff、mypy 通过。此前完整后端套件 4960 passed、92 skipped、1 个旧审计脚本期望失败，修正后该 2 项定向复测通过。全库 mypy 301 个既有错误与 v1.10.30 基线一致。独立规范与标准 Review 对产品代码无 confirmed issue。
- 只读部署预检：`market-runtime-preflight` 返回 `passed/snapshot_ready/60/60`；`install-local-services.sh --render-only` 成功。发布前必须重新核验 exact tag 与现役状态。
- **发布判定：阻塞。** D1 30 项当前无法评估，且页面把已知质量合同拒绝泛化为服务不可用；质量语义如何扩展需 owner 选择。PR 保持草稿；未执行 main merge、tag、GitHub Release、Runtime promotion。现役仍为 v1.10.30、正式 W1 50/60。自然运行验收另行待证。

原始 JSON/JSONL 文件与本 README 同目录，均为只读核对结果。文件 SHA-256：

本轮实际页面命令（临时审计 spec 执行后已从候选工作树移除，原始结果保留）：

```bash
MATRIX_FREQUENCY=1w EXPECTED_SHA=ff012744e4ed1781b7ae56d5b6c153957d29de92 PLAYWRIGHT_SKIP_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 pnpm exec playwright test -c playwright.config.mjs e2e/release-v1-10-31-matrix.tmp.spec.mjs --workers=1
MATRIX_FREQUENCY=1d EXPECTED_SHA=ff012744e4ed1781b7ae56d5b6c153957d29de92 PLAYWRIGHT_SKIP_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 pnpm exec playwright test -c playwright.config.mjs e2e/release-v1-10-31-matrix.tmp.spec.mjs --workers=1
PLAYWRIGHT_SKIP_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174 pnpm exec playwright test -c playwright.config.mjs e2e/release-v1-10-31-rs.tmp.spec.mjs --workers=1
./scripts/ops/macos/run-local-service.sh market-runtime-preflight
./scripts/ops/macos/install-local-services.sh --render-only
./scripts/ops/macos/local-services-status.sh
```

结果依次为：W1 严格自动摘要断言 1 failed（其余 179 项通过）；D1 1 passed / 180 行；RS 手动读取 1 passed；preflight `passed/snapshot_ready`；render-only 成功；现役 status `overall=passed` 且仍为 v1.10.30。上述命令没有执行 provider 下载或正式写入。

| 文件 | SHA-256 |
| --- | --- |
| `guiyi-v1.10.31-d1.json` | `7176a42b30ac2f98709cf4fff2b9f2f386080e1369ce7403b1255b2632973c96` |
| `guiyi-v1.10.31-w1-v1.json` | `54cdd18f9d3215eccd4c2782f7696afc2b5f9245afff0651308e31c5d42ede1e` |
| `guiyi-v1.10.31-w1-v2.json` | `310a3aca663f713974ff9836b12bd85ad2f42b46a14a354f0f38c4bd986edf55` |
| `guiyi-v1.10.31-page-1w.jsonl` | `1d1ef9e0b63465728eefe464f10649e274d92f833216181fb03c2396ed2cc4ed` |
| `guiyi-v1.10.31-page-1d.jsonl` | `bde97b6c34300a109f7b0f13e272558ffb70ea4d94bff64683b408140b153070` |
| `guiyi-v1.10.31-rs-browser-debug.json` | `0dc97af897529280508ad59e6afeb18d6459bee08b0c736a27adb1ac857f8e48` |
