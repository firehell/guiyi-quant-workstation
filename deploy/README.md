# 运维拓扑与只读检查

仓库唯一 active 运维链为：Mac launchd 受监督 Runtime → FRPC 本地隧道 → 腾讯云 FRPS → Nginx
HTTPS/Basic Auth 公网入口。腾讯云不运行第二套 API/Web 应用副本。

## 三段只读检查

按链路从内向外执行；以下脚本只读取状态，不启动、停止、重载服务，也不运行 migration 或数据任务：

```bash
# Mac：四个 launchd label、同一 Runtime 根、Git 身份与本地 HTTP/Runtime health
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

- [`deploy/launchd/`](launchd/)：Mac API/Web/Live/after-market 与日志轮转模板；安装器模式见
  `TESTING.md`。
- [`deploy/frp/`](frp/)：FRPC/FRPS 隧道配置与分段验收。
- [`deploy/nginx/`](nginx/)：腾讯云 HTTPS/Basic Auth 反代模板。

`--render-only` 可用于本地无副作用验证。任何 launchd 加载/重载、Runtime switch、腾讯云配置应用或
Nginx reload 都是独立受控外部操作，必须在执行前取得与目标相符的一次性明确意图。
