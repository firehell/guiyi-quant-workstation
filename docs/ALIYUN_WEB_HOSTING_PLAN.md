# 阿里云 Web 托管方案

生成时间：2026-07-07

## 1. 定位

阿里云 Web 托管是归一量化当前远程访问主线，用于让浏览器访问本地研究工作站产出的 Web 能力。

本方案只解决访问、运行和健康检查问题，不改变产品边界：

- 仍是个人本地量化研究工作站。
- 不做公开 SaaS。
- 不做多用户权限系统。
- 不接实盘自动下单。
- 不把企业微信提醒当成交易指令。

Cloudflare Tunnel / Access 已降级为历史备选方案，见 `docs/CLOUDFLARE_WORKSTATION_ACCESS.md`。

## 2. 第一版范围

第一版只做最小可验收托管：

- Web 前端可通过阿里云入口访问。
- FastAPI REST API 可通过受控反向代理访问。
- WebSocket 路径可用于 backtest / signal 进度。
- `/healthz`、`/api/health` 可被外部探测。
- 本地 Mac / 工作站仍是数据下载、回测、信号和复盘主运行环境。

第一版不做：

- 不开放 SSH、terminal、code-server 或任意 shell。
- 不提交阿里云账号、AccessKey、证书私钥、token、cookie。
- 不把 RQData license、企业微信 webhook 或数据库密码写入仓库。
- 不把 PostgreSQL 直接暴露到公网。
- 不改数据主链路或策略逻辑。

## 3. 服务边界

本地服务口径保持：

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000
API docs: http://127.0.0.1:8000/docs
Health: http://127.0.0.1:8000/healthz
```

反向代理路径建议：

```text
/api/*      -> FastAPI
/ws/*       -> FastAPI WebSocket
/healthz    -> FastAPI
/*          -> Vue Web
```

验收前必须确认：

- `curl http://127.0.0.1:8000/healthz` 返回 JSON。
- `curl http://127.0.0.1:8000/api/health` 返回 JSON。
- Web 页面可打开 `/market`。
- WebSocket 连接路径不被代理截断。

## 4. 安全要求

- 所有密钥只通过本机环境变量、系统钥匙串或阿里云控制台配置。
- 仓库不保存阿里云 AccessKey、证书私钥、数据库密码、RQData license、企业微信 webhook。
- 日志不能打印 `QYWX_WEBHOOK_URL`、RQData 凭据、阿里云凭据或 cookie。
- 外部访问只暴露 Web / API / WebSocket / health check，不暴露数据库、Redis、文件系统或 shell。
- 企业微信仍只允许观察提醒，不表达“必须买入 / 必须卖出”。

## 5. 验收标准

- 本地 `./scripts/dev-up.sh` 可启动 Web / API / worker。
- 外部入口访问 Web 成功，Market 页面可加载。
- `/api/health` 与 `/healthz` 外部访问成功。
- WebSocket smoke 可观察 backtest 或 signal 通道连接。
- 关闭本地服务后 health check 能明确失败，不长时间假装 healthy。
- 不新增任何凭据文件或敏感日志。

## 6. 后续任务

建议另开独立阶段：

```text
ALIYUN-WEB-1A-HOSTING-DESIGN
ALIYUN-WEB-1B-LOCAL-PROXY-SMOKE
ALIYUN-WEB-1C-REMOTE-HEALTH-SMOKE
```

每个阶段都应先 Plan，明确是否涉及域名、证书、反向代理、端口和运行守护。
