# 运维拓扑与只读检查

仓库唯一 active 运维链为：Mac launchd 受监督 Runtime → FRPC 本地隧道 → 腾讯云 FRPS → Nginx
HTTPS/Basic Auth 公网入口。腾讯云不运行第二套 API/Web 应用副本。

## 三段只读检查

按链路从内向外执行；以下脚本只读取状态，不启动、停止、重载服务，也不运行 migration 或数据任务：

```bash
# Mac：API/Web/Live/after-market/Alert 五个 label（按 activation marker 判定 required）、同一 Runtime 根、
# 已加载进程 commit 身份与本地 HTTP/Runtime health
./scripts/ops/macos/local-services-status.sh

# Mac：本地端口与 FRPC
./scripts/ops/network/local-tunnel-healthcheck.sh

# 腾讯云：FRPS 端口与隧道 upstream
./scripts/ops/network/tunnel-healthcheck.sh

# 公网：HTTPS、Basic Auth、Web/API/WebSocket 与关闭端口
PUBLIC_BASE_URL=https://<your_domain> ./scripts/ops/network/public-healthcheck.sh
```

未认证公网检查预期 HTTP 401；提供 Basic Auth 后，页面/API 预期 200，
`/api/v1/market/ws` WebSocket Upgrade 预期 101。

## 配置与变更 Gate

- [`deploy/launchd/`](launchd/)：Mac API/Web/Live/after-market/Alert 与日志轮转模板；安装器模式见
  `TESTING.md`。
- API 与 Alert 模板只共享一个 Git 外 `GUIYI_ALERT_NOTIFICATION_CONFIG_PATH`；PushPlus token 与 Topic code
  不进入 plist、仓库或状态输出。
- [`deploy/frp/`](frp/)：FRPC/FRPS 隧道配置与分段验收。
- [`deploy/nginx/`](nginx/)：腾讯云 HTTPS/Basic Auth 反代模板。

安装器会把渲染时 checkout SHA 写入每个 plist 的 `GUIYI_RUNTIME_COMMIT`；只读状态脚本同时核对已加载
`GUIYI_PROJECT_ROOT`、该 commit 与当前 supervised checkout，避免把移动后的工作树 HEAD 当成已运行版本。

`--render-only` 可用于本地无副作用验证。任何 launchd 加载/重载、Runtime switch、腾讯云配置应用或
Nginx reload 都是独立受控外部操作，必须在执行前取得与目标相符的一次性明确意图。

### Market Runtime promotion preflight

`install-local-services.sh --confirm-market-runtime` 只会执行一次
`run-local-service.sh market-runtime-preflight`。该 preflight 是只读检查，发生在外部 activation marker 准备、
runtime script 写入、已安装 LaunchAgent plist 替换以及任何 `launchctl` mutation 之前；仓库内 plist render
不属于这些外部 activation mutation。若 preflight 阻断，安装器非零退出，且不触碰 marker、runtime directory、
installed plist 或 `launchctl`。

preflight 只读取 operational universe、权威 Calendar/Session phase、既有 immutable Live subscription snapshot 与
公开 after-market status。允许的通过原因只有：完整且 identity 有效 snapshot 的 `snapshot_ready`；所有品种真正
最早权威 Session start 前的 `before_first_session`；同日 after-market 已 passed、且 products 与 operational
顺序完全一致的 `after_market_complete`；以及无 current trading day、无 active Session 的
`non_trading_interval`。它不会把“下一段 session 尚未开始”误作 `before_first_session`。

跨 checkout 时，preflight 从当前 supervised、已加载 after-market launchd root 读取 status，并与 installed
plist 声明的 root 交叉校验，不能把 candidate checkout 当作 status authority。仅 first-install 可使用 candidate
root，且必须同时满足 launchd domain 可读、after-market label 明确 not-found、没有 installed plist。任何
domain/permission/label 命令错误，或 root 缺失、畸形、不一致，均以
`MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE` 阻断；runtime env 不能覆盖这个受控 status path。

已开始后的缺失 snapshot、无效/部分 snapshot、未知或分歧的 phase/session authority，以及 running、corrupt、
unreadable 或 chronology 不可能的 after-market state 一律阻断；公开 block reason 仅为
`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED`、`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_INVALID`、
`MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。没有 override、repair、synthetic snapshot、retry、replay 或
fallback；通过预检本身不构成 Runtime promotion、release、Runtime ready 或 production verification。
