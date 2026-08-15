# FRPC 隧道配置（Mac mini → 腾讯云）

Mac mini 的 launchd 受监督服务就绪后，通过 FRPC 将本地 Web/API 端口映射到腾讯云 FRPS。
完整运维顺序见 [`deploy/README.md`](../README.md)。

## 端口映射

| 名称 | Mac mini local | 腾讯云 remote |
|------|----------------|---------------|
| guiyi-web | `127.0.0.1:5173` | `18080` |
| guiyi-api | `127.0.0.1:8000` | `18000` |

腾讯云 Nginx 反代 `18080` / `18000`，见 [`deploy/nginx/guiyi-quant.conf`](../nginx/guiyi-quant.conf)。
FRPS 必须使用 [`frps.toml.example`](frps.toml.example) 中的
`proxyBindAddr = "127.0.0.1"`，使这两个代理端口只供同机 Nginx 访问。
FRPS 控制端口 `7000` 仍可被远端 FRPC 访问，因此服务端与客户端必须使用内容相同的本机
token 文件认证；模板依赖 FRP `v0.64.0+` 的 `auth.tokenSource`，秘密文件缺失时配置加载失败。
云安全组还应把 `7000` 的来源限制为受控地址，但不能用来源限制替代 FRPS 自身认证。

## 安装与启动（Mac mini）

```bash
brew install frpc
cp deploy/frp/frpc.toml.example /usr/local/etc/frp/frpc.toml
# 编辑 frpc.toml，填入真实 serverAddr
# 通过本机秘密管理创建 /usr/local/etc/frp/client_token，并设置权限 600；勿写入仓库

test -s /usr/local/etc/frp/client_token
frpc verify -c /usr/local/etc/frp/frpc.toml

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

服务端也必须先通过本机秘密管理创建非空的 `/etc/frp/server_token`（权限 `600`），再校验并
启动 FRPS：

```bash
test -s /etc/frp/server_token
frps verify -c /etc/frp/frps.toml
```

两个 token 文件的内容必须相同，但不得把值写入命令、配置、文档、日志或 Git。受监督服务直接
读取固定文件；文件缺失时不能退化为共享默认 token。

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

公网验收还必须确认 `18000` / `18080` 为 closed；Basic Auth 只保护 Nginx
入口，不能补救 FRPS 代理端口直接暴露。
