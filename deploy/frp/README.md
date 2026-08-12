# FRPC 隧道配置（Mac mini → 腾讯云）

Mac mini 的 launchd 受监督服务就绪后，通过 FRPC 将本地只读 Web/API 端口映射到腾讯云 FRPS。
完整运维顺序见 [`deploy/README.md`](../README.md)。

## 端口映射

| 名称 | Mac mini local | 腾讯云 remote |
|------|----------------|---------------|
| guiyi-web | `127.0.0.1:5173` | `18080` |
| guiyi-api | `127.0.0.1:8000` | `18000` |

腾讯云 Nginx 反代 `18080` / `18000`，见 [`deploy/nginx/guiyi-quant.conf`](../nginx/guiyi-quant.conf)。

## 安装与启动（Mac mini）

```bash
brew install frpc
cp deploy/frp/frpc.toml.example /usr/local/etc/frp/frpc.toml
# 编辑 frpc.toml，填入真实 serverAddr；auth.token 仅写本机配置且不得提交

brew services start frpc
brew services info frpc
```

前台诊断（查看 start proxy success）：

```bash
brew services stop frpc
frpc -c /usr/local/etc/frp/frpc.toml
```

## 常见错配

```toml
localPort = 5174    # 错：应为 5173
localPort = 3000    # 错
remotePort = 18000  # 错：web 应为 18080
localIP = "0.0.0.0" # 不推荐，用 127.0.0.1 即可
```

## 验收

Mac mini：

```bash
./scripts/ops/network/local-tunnel-healthcheck.sh
curl -i http://127.0.0.1:5173/
curl -i http://127.0.0.1:8000/api/health
```

如受监督服务未加载，先只读确认具体缺失目标：

```bash
./scripts/ops/macos/local-services-status.sh
```

随后按 `TESTING.md` 对单个目标服务取得范围明确的一次性重载意图；不得用聚合恢复命令同时执行
数据库迁移、Web build 与多服务切换。

腾讯云 ECS：

```bash
./scripts/ops/network/tunnel-healthcheck.sh
```
