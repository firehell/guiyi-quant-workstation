# WORKSTATION-PUBLIC-SECURITY-SMOKE 验收摘要

**任务 ID**: WORKSTATION-PUBLIC-SECURITY-SMOKE  
**执行时间**: 2026-07-12  
**总体结论**: **FAIL**（公网 HTTPS Gate 未通过；多项检查阻塞或待人工补全）

---

## 执行环境限制

| 项 | 计划要求 | 实际 |
|----|----------|------|
| Smoke 执行机 | 外网第三方机器 | Mac mini（仓库所在机） |
| ECS 基线 | SSH 运行 tunnel-healthcheck / nginx -t | SSH 公钥被拒绝 |
| 认证 smoke | 用户提供 BASIC_AUTH_* | 环境变量未设置 |
| 重启恢复 | 分项人工授权 | 未授权，全部跳过 |

---

## 分阶段结果

| 阶段 | 结果 | 说明 |
|------|------|------|
| 0 Mac 基线 | **PASS** | 5173/8000 LISTEN，frpc 运行，launchd 五服务 loaded |
| 0 ECS 基线 | **PARTIAL** | 仅公网探测；隧道端口 18080/18000 未暴露 |
| 1 TLS / HTTP→HTTPS | **FAIL** | 443 Connection refused；HTTP 80 返回 401 无跳转 |
| 2 未认证 401 (正式脚本) | **FAIL** | `public-healthcheck.sh` 在 http_redirect 失败退出 |
| 2 未认证 401 (HTTP 补充) | **PARTIAL PASS** | 各路径 HTTP 401；敏感端口 CLOSED |
| 3 认证 200/WS 101 | **BLOCKED** | 缺凭据 + HTTPS 不可用 |
| 4 安全组 / 7000 | **FAIL** | 7000 公网 OPEN；缺控制台截图 |
| 5 重启恢复 | **SKIPPED** | 待单独授权 |
| 6 证据归档 | **DONE** | 见本目录 |

---

## 已通过项

- Mac mini 本地服务与 FRPC 隧道上游正常
- 未认证时 Web/API/health/WS 经 Nginx 返回 **401**（HTTP 层）
- 公网端口 **5432 / 6379 / 8000 / 5173 / 18080 / 18000** 均为 **CLOSED**

---

## 未通过 / 阻塞项

1. **HTTPS 443 不可达** — 无法完成 TLS 验收与 `public-healthcheck.sh` 正式流程  
2. **HTTP 未强制跳转 HTTPS** — `:80` 直接 401，非 301/308  
3. **FRPS 控制端口 7000 公网 OPEN** — 违反「限制来源」Gate  
4. **认证后 200/WS 101** — 未测（无凭据）  
5. **ECS 本机 / 安全组截图** — 未测（无 SSH / 控制台）  
6. **重启恢复 5a~5d** — 未执行（无授权）

---

## 证据文件

| 文件 | 内容 |
|------|------|
| [baseline_mac.txt](baseline_mac.txt) | Mac local-services + local-tunnel healthcheck |
| [baseline_ecs.txt](baseline_ecs.txt) | 公网探测替代 ECS SSH |
| [port_scan.txt](port_scan.txt) | 公网端口扫描 |
| [tls_check.txt](tls_check.txt) | openssl + HTTP 头 |
| [smoke_anon.txt](smoke_anon.txt) | 正式 public-healthcheck（失败） |
| [smoke_anon_http_supplement.txt](smoke_anon_http_supplement.txt) | HTTP 层补充 401 探测 |
| [smoke_auth.txt](smoke_auth.txt) | 认证 smoke 阻塞说明 |
| [security_group_notes.txt](security_group_notes.txt) | 7000/443 结论与待补截图 |
| [restart_skipped.txt](restart_skipped.txt) | 重启项跳过记录 |

---

## 修复优先级（需人工授权后执行）

### P0 — 开通 HTTPS

1. 腾讯云安全组入站放行 **TCP 443**  
2. ECS 确认 Nginx `listen 443 ssl` 与 Let's Encrypt 证书有效：`sudo nginx -t && sudo systemctl status nginx`  
3. 配置有效 **域名** DNS 指向 ECS（`workstation.yanyi.com` 当前 NXDOMAIN）  
4. Nginx `:80` 仅做 `return 301 https://$host$request_uri`

### P0 — 收紧 FRPS 7000

1. 安全组移除 7000 对 `0.0.0.0/0` 的入站（若存在）  
2. 仅允许 Mac mini 出口 IP 或 VPN 内网访问 7000

### P1 — 复测

```bash
# 外网机器（推荐）
PUBLIC_BASE_URL=https://<domain> ./scripts/public-healthcheck.sh

BASIC_AUTH_USER='<user>' BASIC_AUTH_PASS='<pass>' \
PUBLIC_BASE_URL=https://<domain> ./scripts/public-healthcheck.sh
```

### P2 — 重启恢复（分项授权）

见 [restart_skipped.txt](restart_skipped.txt)

---

## 状态声明

- **不得**将 `docs/ALIYUN_WEB_HOSTING_PLAN.md` §6 标为已验收  
- **不得**声明 `LONG_RUNNING_READY`（仍依赖 T7 长稳 + 完整公网 smoke）  
- 本 smoke **未修改**策略、回测、交易逻辑或 `.env`  
- **未打印** Basic Auth 密码或 FRP token

---

## 下一步

1. 修复 P0（443 + 7000 + 域名）后，从外网机器重跑 Gate 1~3  
2. 提供 BASIC_AUTH 环境变量或自行执行认证 smoke  
3. 补安全组截图与 ECS `ss` 输出  
4. 逐项授权后执行 Gate 5 重启恢复 smoke
