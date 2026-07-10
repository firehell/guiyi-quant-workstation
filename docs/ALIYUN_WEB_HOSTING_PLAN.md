# 公网 Web 托管与安全 Gate

更新时间：2026-07-10

## 1. 定位

公网托管只提供个人研究工作站的受控浏览器入口，不改变产品边界：不做 SaaS、多用户、自动交易、实盘委托或远程 shell。

当前公网拓扑为腾讯云 Nginx + FRPS，经受控隧道访问 Mac mini 上的受监督服务。仓库同时保留 systemd 模板作为未来 Linux 同机运行候选，但它不是本轮已部署事实。

## 2. 架构

```text
Browser HTTPS :443 + Basic Auth
-> Tencent Nginx
   -> FRPS 127.0.0.1:18080 -> Mac mini static dist :5173
   -> FRPS 127.0.0.1:18000 -> Mac mini FastAPI :8000

Mac mini launchd
-> API / static Web / backtest worker / signal worker

Docker localhost only
-> PostgreSQL 127.0.0.1:5432
-> Redis auth 127.0.0.1:6379
```

公网长期路径不运行 Vite dev server、`uvicorn --reload` 或 oneshot 子进程组。

## 3. 安全 Gate

真实服务器验收前必须全部满足：

- Nginx 80 仅重定向到 HTTPS。
- TLS 1.2/1.3 与有效证书。
- Basic Auth 文件位于 `/etc/nginx`，密码不入库。
- 云安全组不开放 5432/6379/8000/5173/18000/18080；FRPS 端口按隧道设计限制来源。
- Mac mini `.env` 不入库；若使用候选 systemd 部署，环境文件必须位于 `/etc/guiyi-quant/guiyi-quant.env` 且权限 0600。
- DB、Redis 密码为独立随机值，模板内无 `replace-with-*`。
- 日志不输出 URL 凭据、webhook、token、cookie、RQData license。
- 未认证 Web/API/health 请求均返回 401；认证后才返回 200。

缺少任一项即禁止公网验收。

## 4. 仓库资产

- `deploy/nginx/guiyi-quant.conf`
- `deploy/nginx/README.md`
- `deploy/frp/frpc.toml.example`
- `deploy/launchd/*.plist.template`
- `deploy/systemd/guiyi-quant-api.service`
- `deploy/systemd/guiyi-quant-worker-backtests.service`
- `deploy/systemd/guiyi-quant-worker-signals.service`
- `deploy/systemd/guiyi-quant.target`
- `deploy/systemd/guiyi-quant.env.example`
- `scripts/local-services-status.sh`
- `scripts/server-recover.sh`
- `scripts/public-healthcheck.sh`

## 5. 验收命令

```bash
sudo nginx -t
sudo systemctl status nginx
sudo ss -lntp
```

未认证：

```bash
PUBLIC_BASE_URL=https://workstation.example.com ./scripts/public-healthcheck.sh
```

认证：

```bash
BASIC_AUTH_USER=<user> BASIC_AUTH_PASS=<pass> \
PUBLIC_BASE_URL=https://workstation.example.com ./scripts/public-healthcheck.sh
```

重启恢复：

```bash
sudo ./scripts/server-recover.sh --confirm-production-restart
```

## 6. 当前状态

- 仓库配置和 shell 语法已完成。
- HTTP URL 会被公网检查脚本拒绝。
- 当前没有真实域名、证书和云安全组验收上下文，因此远程 HTTPS、401、端口封闭尚未实际验证。
- Mac mini LaunchAgent 因外置盘隐私权限被系统拒绝读取项目 `.env`，失败 job 已卸载；解决权限前不能宣称重启恢复通过。
- 不能把“模板已生成”写成“公网部署已完成”。
