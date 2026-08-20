# Alert PushPlus Transport 实施计划

日期：2026-08-20

## 任务 1：通知领域边界

- 以测试先行定义 `owner`、`htdy_observers`、delivery 与 provider acceptance。
- HTDY 映射为一次 Topic delivery，SuBing 映射为一次 owner delivery。
- 保留现有 Alert Event-first、无 retry/replay/backfill 语义。

## 任务 2：PushPlus adapter 与安全配置

- 锁定官方 Python SDK。
- 实现严格 Git 外配置读取、权限/owner/symlink/替换检查。
- 实现 owner 无 Topic、HTDY exact Topic、`wechat/txt` 请求与安全错误边界。
- shortCode 只作为 provider acceptance，公开时脱敏。

## 任务 3：composition、CLI、health 与运维

- Runtime composition 只装配 PushPlus transport。
- canary 改为显式 audience；删除 recipients/preflight CLI。
- health 只做结构检查、禁止网络和发送。
- launchd/installer/status 只保留同一个 private config path。

## 任务 4：删除旧实现并同步文档

- 删除 Clawbot/OpenClaw Node seam、recipient directory/pairing、manifest 与未完成 WxPusher 代码。
- 删除旧测试，补齐 dispatcher/config/adapter/composition/CLI/health/ops 测试。
- 同步 AGENTS、STATUS、PROJECT_SOURCE、DECISIONS、ARCHITECTURE、DEVELOPMENT、TESTING 与 deploy 文档。

## 任务 5：验证与集成

- 运行 Alert focused、全 engineering、Ruff、Mypy、shell/plist、secret scan 与 diff check。
- 普通代码完成后提交、合入并 push `develop`。
- 不写真实 token/Topic，不发送通知，不切换 Runtime，不执行 release/tag 或生产 DB mutation。

## 独立外部 Gates

1. 创建专用消息 token 与 Topic。
2. 人工核对 Topic 当前成员在 `1..4` 人内；可以先启用当前成员，后续加入第 4 人。
3. 写入 Git 外 `0700/0600` private config。
4. 分别执行 owner 与 Topic 单次真实 canary。
5. 精确持续授权、release/tag、Runtime promotion/switch/readback 与自然 HTDY 验收。
