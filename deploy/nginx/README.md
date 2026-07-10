# Nginx 反向代理安装说明

适用于腾讯云 / 阿里云轻量服务器：Nginx 监听 80，反代本机 `./scripts/dev-up.sh` 启动的服务。

## 路径映射

| 公网路径 | 上游 |
|----------|------|
| `/api/*` | `http://127.0.0.1:8000` |
| `/ws/*` | `http://127.0.0.1:8000` |
| `/healthz` | `http://127.0.0.1:8000` |
| `/*`（含 `/market`） | `http://127.0.0.1:5173` |

## 安装步骤（Ubuntu）

```bash
# 1. 复制站点配置
sudo cp deploy/nginx/guiyi-quant.conf /etc/nginx/sites-available/guiyi-quant.conf
sudo ln -sf /etc/nginx/sites-available/guiyi-quant.conf /etc/nginx/sites-enabled/guiyi-quant.conf

# 2. 创建 Basic Auth（勿提交密码）
sudo htpasswd -c /etc/nginx/.htpasswd-guiyi <your_user>

# 3. 若默认站点冲突，可禁用
# sudo rm /etc/nginx/sites-enabled/default

# 4. 校验并重载
sudo nginx -t
sudo systemctl reload nginx
```

## 502 排障

502 表示 Nginx 正常，但上游 5173/8000 未响应。在仓库根目录执行：

```bash
ss -lntp | egrep ':5173|:8000'
./scripts/dev-status.sh
curl -sf http://127.0.0.1:8000/healthz
curl -sf -o /dev/null -w "web=%{http_code}\n" http://127.0.0.1:5173/
sudo tail -30 /var/log/nginx/error.log
```

恢复服务：

```bash
./scripts/server-recover.sh
```

公网验收：

```bash
BASIC_AUTH_USER=<user> BASIC_AUTH_PASS=<pass> ./scripts/public-healthcheck.sh
```
