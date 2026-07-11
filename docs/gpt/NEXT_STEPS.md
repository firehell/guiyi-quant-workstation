# NEXT_STEPS.md

更新时间：2026-07-10

## 总原则

- 数据可信度、可追溯和可复算优先于收益和功能扩展。
- 当前不做自动交易、实盘账户、SaaS、多用户或大型重构。
- live、scheduler、数据写入、schema 和公网部署必须分阶段 Gate。

## 当前已完成

1. Stage 13-G：`report_id=14` lineage 与 trust audit passed。
2. JM `20260710_v2` 六周期：1m direct，五周期 local aggregation，全部 primary passed。
3. Stage 8.6：全品种 1d 与 JM 最新主连六周期分开审计。
4. Alembic `20260710_0020`：数据库 current=head，workbench 复合索引存在。
5. 安全配置：DB/Redis localhost、Redis auth、凭据环境变量、HTTPS Nginx 模板。
6. 运行模板：腾讯云 Nginx + FRP，Mac mini launchd 监督 static/API/workers；外接卷权限未通过，systemd 仅为 Linux 候选模板。
7. Web V1-B 视觉与信息架构重构：11 路由、1440/1280/1024 响应式和 Console 验收通过。

## 下一阶段建议

### P0：真实服务器安全 smoke

- 替换 Nginx 域名、证书和绝对路径占位符。
- 云安全组拒绝 5432/6379/8000/5173。
- 未认证访问必须 401，认证后 Web/API/WS 成功。
- `systemctl restart guiyi-quant.target` 后 API 和两个 worker 自动恢复。
- 该步骤需要真实服务器权限；本仓库配置通过不等于远程验收通过。

### P1：8 个全品种 pending 独立修复

- `bb/rs/wh/wr/zc`：只读审计 abnormal price，不能直接升级 quality。
- `L2609F/PP2609F/V2609F`：核对 manifest/parquet/DB，确认后做受控登记。
- 修复后重跑 `stage8_6_1d_first`，不得影响 JM 六周期通过结论。

### P1：样本外验证设计

- 冻结 `report_id=14` 策略版本、参数、数据版本和 execution policy。
- 明确样本内、样本外和 walk-forward 区间。
- 不调参改善当前负收益，不把审计 passed 包装为策略准入。

### P1：macOS 长期运行选择

- 方案 A：人工授予 LaunchAgent 后台访问外接卷权限。
- 方案 B：把长期运行副本放到本机磁盘，数据资产通过受控路径挂载。
- 未完成选择前，不宣称本机开机自启通过。

## 明确后置

- live ingest / aggregation scheduler。
- 企业微信批量重试 scheduler。
- after-market archive 自动运行。
- `research_only` schema/API 语义拆分。
- Web trust audit 专项展示与约 651 kB 公共 chunk 性能拆包。

以上后置项均应另开新 Codex 会话并使用 Plan 模式。

## 下一轮 GPT 上传文件

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `docs/ARCHITECTURE.md`
- `docs/ALIYUN_WEB_HOSTING_PLAN.md`
- `data/reports/stage8_6_active_gate_summary.md`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
