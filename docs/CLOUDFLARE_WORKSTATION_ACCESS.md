# Cloudflare Workstation Access

本文记录归一量化工作站通过 Cloudflare Tunnel + Access 暴露到浏览器的本地配置口径。

## 目标

- Mac mini 常驻运行本地服务。
- 公司端只通过浏览器访问 `https://workstation.yanyi.com`。
- 不开放路由器端口，不暴露 SSH、terminal、code-server 或任意 shell。
- Cloudflare Access 必须先启用，并且只允许个人邮箱访问。

## 本地服务

从仓库根目录启动：

```bash
cd /Volumes/扩展盘/guiyi-quant-workstation
./scripts/dev-up.sh
```

本地端口：

```text
前端：http://127.0.0.1:5173
API：http://127.0.0.1:8000
健康检查：http://127.0.0.1:8000/healthz
```

验收命令：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:5173/healthz
```

预期 JSON：

```json
{"status":"ok","service":"local-workstation"}
```

## Cloudflare Tunnel 配置

先登录并创建 tunnel：

```bash
cloudflared tunnel login
cloudflared tunnel create guiyi-workstation
cloudflared tunnel list
```

创建 `~/.cloudflared/config.yml`：

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /Users/zhangzhao/.cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: workstation.yanyi.com
    path: /api/*
    service: http://127.0.0.1:8000
  - hostname: workstation.yanyi.com
    path: /ws/*
    service: http://127.0.0.1:8000
  - hostname: workstation.yanyi.com
    path: /healthz
    service: http://127.0.0.1:8000
  - hostname: workstation.yanyi.com
    service: http://127.0.0.1:5173
  - service: http_status:404
```

绑定 DNS：

```bash
cloudflared tunnel route dns guiyi-workstation workstation.yanyi.com
```

第一次测试：

```bash
cloudflared tunnel run guiyi-workstation
```

确认 `https://workstation.yanyi.com` 先进入 Cloudflare Access 登录页，再进入本地工作站。

## Access 策略

在 Cloudflare Zero Trust 创建 self-hosted application：

```text
Application name: Guiyi Workstation
Public hostname: workstation.yanyi.com
Path: 留空
```

访问策略：

```text
Policy name: Allow myself only
Action: Allow
Include: Emails
Value: <YOUR_EMAIL>
Session duration: 8h 或 24h
```

不要使用：

```text
Everyone
Any valid email
整个域名邮箱
```

## 常驻服务

手动 tunnel 测试通过后再安装 macOS 服务：

```bash
cloudflared service install
```

如果需要开机后不登录用户也启动：

```bash
sudo cloudflared service install
```

## 安全检查

- Web/API 只监听 `127.0.0.1`。
- 路由器没有开放端口。
- Cloudflare Access 已启用。
- Access 只允许个人邮箱。
- 没有暴露 SSH、terminal、code-server 或任意 shell。
- `~/.cloudflared/config.yml` 和 tunnel credentials 不提交进 Git。
- 不在日志中打印 Cloudflare token、OpenAI key、GitHub token 或其他凭据。
