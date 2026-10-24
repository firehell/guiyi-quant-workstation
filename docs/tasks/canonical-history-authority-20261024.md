# 正式历史唯一口径：v1.15.18 最小补丁

Owner 已交办盘后 Canonical 作为唯一正式历史口径。此补丁基于 exact v1.15.17，只回移正式入口及审计隔离修复，不带入 develop 其他未发布的输入、公式或 launcher 变化。

Newow/Subing 固定原有已保存历史 reader，保留原生完整来源证明和质量拒绝。通用记录面板仅作首次事件审计；Subing 正式图只画 Canonical callouts/指标，实时标记仅在审计模式显示。HTDY 本版不新增历史模型，仅保留既有 Canonical 指标并将实际事件标记改为显式审计。旧记录不删、不回写、不重放通知。

旧 2,565 条对应 Canonical 已齐全，240 路 H1 独立历史经新 lease 验收。新 611 条属于未完成的 10/26 交易日，本补丁不将其标为完整。正式部署、旧故障进程处置及运行读回另行执行，不由离线测试推导完成。

验证与发布的实际结果由主任务在通过后追加。

## 精确候选实际验证

扩展后端 819 passed / 81 skipped；完整 Web 1168 passed / 3 skipped；正式sourceproof/API定向24项及审计面板4项独立复验通过。Subing读取前后用同一revision/seq验证完整Canonical前缀；mid-read暖机前缀修订拒绝旧结果。原融合cache三项fixture补充精确historical模式断言后全套通过，未放宽代际检查。

OpenSpec strict、secret scan、diff、离线uv lock通过。独立Review无剩余Confirmed Issue，允许发布main/tag。候选与v16对比db/live/input/formula/launcher指纹相等，仅reference合同变化。实际发布与维护续接/readback由主任务在Git外证据和develop STATUS中追加，当前不提前声明上线或自然采集验收。
