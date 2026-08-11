# Nginx 反向代理安装说明

适用于腾讯云轻量服务器：Nginx 只在 HTTPS 443 提供受认证入口，反代 FRP 隧道端口；80 端口只做 HTTPS 跳转。

## 架构

```text
Browser
  -> Tencent Nginx :443 (TLS + Basic Auth)
  -> 127.0.0.1:18080 / 18000 (FRPS 隧道入口)
  -> Mac mini FRPC
  -> 127.0.0.1:5173 (supervised static dist) / 8000 (FastAPI)
```

| 公网路径 | Nginx upstream（ECS 本机） | Mac mini 本地 |
|---|---|---|
| `/api/*`、`/ws/*`、`/healthz` | `127.0.0.1:18000` | `127.0.0.1:8000` |
| `/*`（含 `/market`） | `127.0.0.1:18080` | `127.0.0.1:5173` supervised static dist |

## 安装步骤（Ubuntu ECS）

先把配置中的 `workstation.example.com` 和证书路径替换为真实值。证书私钥与 htpasswd 严禁提交仓库。

```bash
sudo cp deploy/nginx/guiyi-quant.conf /etc/nginx/sites-available/guiyi-quant.conf
sudo ln -sf /etc/nginx/sites-available/guiyi-quant.conf /etc/nginx/sites-enabled/guiyi-quant.conf
sudo htpasswd -c /etc/nginx/.htpasswd-guiyi <your_user>
sudo certbot certonly --nginx -d <your_domain>
sudo nginx -t
sudo systemctl reload nginx
```

云安全组只开放 80/443。5432、6379、8000、5173、18000、18080 均不得直接对公网开放；FRPS 控制端口按隧道设计限制来源。

## 502 / Empty Reply 排障

顺序：Mac mini 受监督服务 -> FRPC -> ECS 隧道端口 -> Nginx。

```bash
# Mac mini
./scripts/ops/macos/local-services-status.sh
./scripts/ops/network/local-tunnel-healthcheck.sh
# 服务重载按 TESTING.md 分目标执行，不使用聚合恢复脚本

# Tencent ECS
./scripts/ops/network/tunnel-healthcheck.sh
sudo tail -30 /var/log/nginx/error.log
```

FRPC 配置模板：[`deploy/frp/frpc.toml.example`](../frp/frpc.toml.example)

## 公网安全验收

未认证请求必须返回 401，认证后才允许 200：

```bash
PUBLIC_BASE_URL=https://<your_domain> ./scripts/ops/network/public-healthcheck.sh
BASIC_AUTH_USER=<user> BASIC_AUTH_PASS=<pass> \
PUBLIC_BASE_URL=https://<your_domain> ./scripts/ops/network/public-healthcheck.sh
```

未完成有效 TLS、401/200 验证和公网端口核验前，禁止把公网入口标记为已验收。
