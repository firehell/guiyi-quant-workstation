# 归一量化 Mac mini 本地运维手册

> 角色：DevOps / 本地运维部署专家
> 版本：v1.0　生成时间：2026-07-09
> 适用阶段：V1（Mac mini 主机，低运维 / 可恢复 / 可回滚）
> 配套文档：`ROLE_SPEC.md`、`TASK_MATRIX.md`、`STATE_MACHINE_TICKET.md`、`COLLAB_PROTOCOL.md`、`SECURITY_HANDBOOK.md`、`TEST_EXPERT_HANDBOOK.md`、`UX_VISUAL_SPEC.md`

## 0. 本手册定位与红线

本手册只负责 **Mac mini 上的本地长期运行、备份、恢复、回滚**，不设计任何云部署。

V1 三原则（强制）：

1. **Mac mini 优先**——所有常驻进程、调度、监听、预警运行在 Mac mini 本地。
2. **低运维**——能用系统自带能力（launchd / newsyslog）就不自建复杂编排；一个主运行进程 + 一个交互观测会话即可。
3. **可恢复、可回滚**——任何部署都可 `git checkout` 回旧 tag，任何数据异常都可还原备份，且**绝不删除历史行情数据**。

必须人工确认的操作（详见 §17 + §16）：

- Mac mini 首次 `git clone`（一次性）
- 任何会改变生产代码的 `git pull` / `git checkout`（即部署）
- 创建 / 加载 / 卸载 launchd 守护、启用开机自启
- 编辑或创建 `.env`（含 RQData token、企业微信 webhook）
- 数据回滚 / 覆盖 / 删除
- 首次把企业微信 webhook 从 dry-run 切到真实发送
- 任何生产配置变更

AI（WorkBuddy / CodeBuddy / Codex CLI）**不得**自行执行以上任一操作；属于 `SECURITY_HANDBOOK.md` 六条强制禁令的延伸。

---

## 1. Mac mini 目录规划

建议固定一个根目录，全站路径都基于它。下文以 `$GQ_ROOT` 代表 Mac mini 上的根目录，默认：

```text
/Users/<macmini-user>/guiyi-quant
```

规划如下（一级清晰、不嵌套过深）：

```text
$GQ_ROOT/
├── repo/                 # git 仓库（业务代码）            [git tracked]
│   ├── scripts/          # codex_plan.sh / codex_dev.sh / run_tests.sh / collect_result.sh
│   └── ...               # 业务代码，不在此直接常驻运行改动
├── venv/                 # Python 虚拟环境（隔离依赖）      [local, gitignored]
├── run/                  # 运行时产物
│   ├── guiyi.pid         # 主运行进程 pid
│   ├── guiyi.sock        # 可选本地 socket（状态查询）
│   └── last_bar.ts       # 最近一次处理到的 bar 时间戳（断点续传用）
├── data/                 # 数据目录（受保护，见 §8/§9）
│   ├── parquet/          # JM v2 raw / standard parquet
│   ├── db/               # PostgreSQL / DuckDB 本地库文件
│   └── archive/          # 盘后归档落盘
├── logs/                 # 日志目录（见 §6/§7）
│   ├── app.log
│   ├── listener.log
│   ├── scheduler.log
│   └── error.log
├── backups/              # 备份（见 §8/§9）
│   ├── data-YYYYMMDD/
│   └── config-YYYYMMDD/
└── .env                  # 密钥（RQData token / 企业微信 webhook）【绝不进 git / 文档 / 日志】
```

约定：

- `repo/` 与 `data/`、`logs/`、`backups/` 物理分离，便于单独备份 `data/` 而不碰代码。
- 所有绝对路径在 `run/` 下用相对 `$GQ_ROOT` 的方式引用，避免硬编码 home。
- `.env` 在 `.gitignore` 中，且本手册禁止任何脚本 `cat .env` 后写日志或回传。

---

## 2. GitHub → Mac mini 本地版本管理方案

核心原则：**GitHub 是源，Mac mini 是消费端；Mac mini 永不 push，AI 永不 push。**

流程：

```text
开发机（Codex/CodeBuddy 改代码）
   → 你 review → 你 git push 到 GitHub
   → Mac mini 侧你手动 git fetch + 按 tag 部署（见 §3）
```

Mac mini 上的 git 配置：

- 仅配置 `origin` 指向 GitHub（只读消费，不配写权限 key 当然也可以，但务必只 fetch/pull）。
- 建议 Mac mini 用 **SSH deploy key（只读）** 或 HTTPS + 只读 token，避免 Mac mini 持有可写凭证。
- AI 在 Mac mini 上只允许 `git fetch` / `git status` / `git diff` / `git log` / `git checkout <tag>`，**禁止 `git push`**（GitHub 操作边界见 `SECURITY_HANDBOOK.md`）。

每日同步方式：

- 不自动 pull。你决定何时把新 release 拉到 Mac mini。
- `git fetch --tags` 拉取最新 tag，再用 §3 的 checkout 流程升级。

---

## 3. 分支、tag、release、本地生产 checkout 方案

分支模型（轻量）：

```text
main      稳定主分支（受保护，只能经 PR 合入）
develop   集成分支（开发机日常）
tag       vX.Y.Z 发布标记（生产 checkout 的对象）
```

- **V1 生产运行以 tag 为准，不在移动分支上常驻**。不要 `git checkout main` 后长期跑——main 一旦变动，生产就漂移。
- 推荐生产 checkout 方式（detached + 记录）：

```bash
cd $GQ_ROOT/repo
git fetch --tags
git checkout v1.3.0          # 明确版本，detached HEAD 可接受
git log -1 --oneline         # 记录当前运行 commit，写入 run/DEPLOYED_COMMIT
```

- 维护一个 `$GQ_ROOT/repo/run/DEPLOYED_COMMIT`（或 `$GQ_ROOT/run/DEPLOYED_COMMIT`）记录当前生产 commit，便于回滚时对照。
- release 由你在 GitHub 手动打 tag 并写 release notes；Mac mini 侧只消费。

---

## 4. tmux / daemon / launchd 使用建议

V1 低运维推荐组合：**launchd 负责常驻与崩溃自启；tmux 负责人工观测与排障**，二者不冲突、不叠加多层调度器。

| 工具 | 用途 | V1 建议 |
|---|---|---|
| **launchd** | 开机自启 + 进程崩溃自动拉起（`KeepAlive`） | 主运行进程用它，稳定常驻 |
| **tmux** | 交互式观测 / 手动重启 / 看实时日志 | 排障、看 listener 实时输出用，不作为长期自启手段 |
| **daemon（自写）** | 不推荐 | V1 过度运维，避免引入 |

launchd plist 要点（仅示例，不硬编码路径/密钥）：

```xml
<!-- ~/Library/LaunchAgents/com.guiyi.quant.plist -->
<key>Label</key>        <string>com.guiyi.quant</string>
<key>ProgramArguments</key>
  <array>
    <string>/Users/<user>/guiyi-quant/venv/bin/python</string>
    <string>/Users/<user>/guiyi-quant/repo/scripts/run_loop.sh</string>
  </array>
<key>WorkingDirectory</key> <string>/Users/<user>/guiyi-quant/repo</string>
<key>RunAtLoad</key>    <true/>
<key>KeepAlive</key>    <true/>      <!-- 崩溃/退出自动拉起 -->
<key>ThrottleInterval</key> <integer>30</integer>  <!-- 频繁崩溃时限流，防雪崩 -->
<key>StandardOutPath</key> <string>/Users/<user>/guiyi-quant/logs/app.log</string>
<key>StandardErrorPath</key> <string>/Users/<user>/guiyi-quant/logs/error.log</string>
<key>StartCalendarInterval</key> <!-- 可选：定时任务，见 §5 -->
```

- 加载：`launchctl load ~/Library/LaunchAgents/com.guiyi.quant.plist`（**需你人工确认**）。
- 卸载：`launchctl unload ...`（**需你人工确认**）。
- 不用 `launchctl start` 长期顶替 `KeepAlive`，保持单一自启入口。

---

## 5. 实时监听服务常驻方案

主运行进程 `run_loop`（由 `scripts/run_loop.sh` 启动的 Python 主循环）负责：

1. 按周期从 RQData 拉取 1m 最新 bar（RQData 主源，1m 基础）。
2. 触发策略信号评估（仅确认收盘后触发，见 `TEST_EXPERT_HANDBOOK.md` §3）。
3. 对通过 Stage 9 Gate 的 eligible 事件，按 dry-run 默认生成企业微信 payload；真实发送需独立授权开关。
4. 持久化 `run/last_bar.ts`，作为断点续传锚点。

常驻方式：

- 由 launchd `KeepAlive` 托管（§4）。
- 主循环内部应有：固定 sleep 间隔、异常捕获不退出（只记日志 + 系统告警）、退出码非零以便 launchd 拉起。
- 不依赖 tmux 保活；tmux 仅用于你临时观察。

定时任务（盘后归档、每日巡检）：

- 用 launchd `StartCalendarInterval`（如每日 15:30 盘后归档、每日 23:50 巡检），或系统 `launchd` 周期间隔。
- 不在代码里自建 cron 守护，避免与 launchd 双重调度。

---

## 6. 日志目录规划

见 §1 的 `logs/`。分类写入，便于轮转与排障：

```text
logs/
├── app.log        # run_loop 主循环常规日志
├── listener.log   # RQData 拉取 / 实时监听专项
├── scheduler.log  # 定时任务（归档 / 巡检）
└── error.log      # 异常 / 堆栈（launchd StandardErrorPath 也指向它）
```

补充：

- 企业微信发送结果记到 `signal_notifications` 表（见 `STAGE9_WECHAT_DELIVERY.md`），不把 webhook / token 写日志。
- 日志中任何出现的密钥、webhook、账户字段必须按 `SECURITY_HANDBOOK.md` §11 脱敏；一旦泄露视为 P0。

---

## 7. 日志轮转策略

优先用 macOS 自带 `newsyslog`（系统级、零额外依赖）：

- 在 `/etc/newsyslog.d/guiyi.conf` 增加条目（需 sudo，你手动操作）：

```text
# logfile                              mode owner group size count flags
/Users/<user>/guiyi-quant/logs/app.log        644 <user> staff 5M   14    GZ
/Users/<user>/guiyi-quant/logs/listener.log   644 <user> staff 5M   14    GZ
/Users/<user>/guiyi-quant/logs/scheduler.log  644 <user> staff 2M   14    GZ
/Users/<user>/guiyi-quant/logs/error.log      644 <user> staff 5M   14    GZ
```

- `5M` = 单文件到 5MB 轮转；`14` = 保留 14 份；`GZ` = 压缩。
- 也可用 Python `TimedRotatingFileHandler`（按天），二选一，不要两套同时跑。
- **硬约束**：日志不得无限增长；磁盘低于阈值（如 <10%）必须触发清理告警（见 §15）。

---

## 8. 数据备份策略

保护对象：`data/`（parquet / db / archive）——**历史行情数据永不删除**（安全红线）。

方案：

- 每日一次增量快照：`rsync -a --delete $GQ_ROOT/data/ $GQ_ROOT/backups/data-$(date +%Y%m%d)/`
  - 注意：`--delete` 只作用于备份目录内部，不碰源 `data/`；源数据只增不删。
- 保留窗口：最近 14 天日备 + 每月 1 号月备（保留 3 个月），可按磁盘调整。
- 备份不离开 Mac mini 本地磁盘（V1 不设计云备份，避免过度运维）；如需外部盘，单独挂 `backups/` 到外置盘，**不自动上传任何云**。
- 备份前无需停服（parquet / DuckDB 读多写少；如 PostgreSQL 建议低峰期或 `pg_dump` 一致性快照）。
- 备份动作本身记 `scheduler.log`，不记录数据内容。

---

## 9. 配置备份策略

保护对象：launchd plist、`scripts/`、`.env`（密钥）。

- plist + scripts：随 git 仓库版本走，MAC mini 上 `git` 即配置备份；改 plist 前先确认在仓库有对应版本。
- `.env`：**本地备份一份到 `backups/config-YYYYMMDD/.env`，但不进 git、不上云、不进任何文档/日志**。恢复时由你手动从本地备份拷回。
- 配置备份清单（每日巡检核对）：

```text
backups/config-YYYYMMDD/
├── com.guiyi.quant.plist
├── run_loop.sh
├── .env                      # 仅本地，绝不外传
└── MANIFEST.txt              # 记录备份时间 + DEPLOYED_COMMIT
```

---

## 10. 断网处理策略

监听进程对网络中断必须**优雅降级，不崩溃、不丢状态**：

- RQData 拉取失败 → 捕获异常，记 `listener.log` + 触发企业微信系统告警（若 webhook 此时可达；不可达则仅本地 error.log）。
- 暂停实时拉取，保持 `run/last_bar.ts` 不变；进入退避重试（指数退避，如 30s / 60s / 120s，上限 10 分钟）。
- 网络恢复后，从 `last_bar.ts` 之后续传，**不重复发送已确认事件**（依赖 Stage 9 幂等键 `enterprise_wechat:signal_event:{id}`）。
- 不删除、不重置已落盘数据；不切换数据源（RQData 是唯一主源）。

---

## 11. 重启恢复策略

两类重启：

1. **进程崩溃（launchd 拉起）**：`KeepAlive` 自动重启（ThrottleInterval 限流防雪崩）。重启后从 `run/last_bar.ts` 续传。
2. **Mac mini 整机重启**：launchd `RunAtLoad` 在登录后自动加载服务；无需人工干预即可恢复常驻。

恢复核对（自动 + 可见）：

- 服务起来后，先校验 `data/` 完整、DB 可连、`last_bar.ts` 存在。
- 首轮只做"追平历史 bar"，不立即批量发历史告警；确认追上当前时间后再恢复实时。
- 若重启发生在交易时段，恢复后只处理"未确认"的新 bar，已发的靠幂等键去重。

---

## 12. RQData 失效处理策略

RQData 是主源，失效时：

- 检测：连续 N 次（如 3 次）拉取失败 / 返回异常 → 判定 RQData 失效。
- 动作：
  - 记 `listener.log` 错误 + 企业微信系统告警（异常类型=RQData 失效，建议操作=检查账号/网络/配额）。
  - 保持现有 `data/` 不变，**不删除、不回退到旧数据、不切换其他源**。
  - 退避重试（见 §10）；恢复后从 `last_bar.ts` 续传。
- 不达标不发送：RQData 失效期间不生成基于缺失数据的信号，避免误触发。
- 账号/配额类问题由你人工处理（涉及 RQData 密钥，AI 不碰）。

---

## 13. 企业微信 webhook 失败处理策略

对齐 `STAGE9_WECHAT_DELIVERY.md` 与 `TEST_EXPERT_HANDBOOK.md` §4：

- 发送失败（HTTP 非 2xx / 超时）→ **重试 ≤3 次**，指数退避（如 5s / 15s / 45s）。
- 每次发送带幂等键 `enterprise_wechat:signal_event:{id}`，重试不重复落通知记录。
- 3 次仍失败 → 记 `signal_notifications` 状态为 `failed`，触发企业微信系统告警（异常类型=webhook 发送失败），**停止对该事件继续重试，不无限循环**。
- webhook 本身不可达（断网）时：仅本地 `error.log` + 待恢复后由下一轮补发（仍受幂等键约束）。
- 真实发送开关默认 off（dry-run）：首次开启真实发送**必须你人工确认**（安全红线）。

---

## 14. 运行状态检查命令

提供 `scripts/gq_status.sh`（由 CodeBuddy 后续实现，此处定契约）：输出以下字段，便于你或巡检脚本快速判断：

```text
$ gq_status
service   : running (pid 12345, uptime 3d 4h)
launchd   : loaded (com.guiyi.quant)
last_bar  : 2026-07-09 15:00:00 (fresh / STALE!)
rqdata    : ok / FAIL (last success 2m ago)
wechat    : dry-run / live (last send 12m ago, ok)
disk      : 62% used (backups 14d)
backup    : data-20260709 ok, config-20260709 ok
deploy    : v1.3.0 @ <commit>
```

简化人工核查命令（无需脚本）：

```bash
launchctl list | grep guiyi          # 看服务是否 loaded/运行
tmux ls                               # 看你开的观测会话
tail -n 50 $GQ_ROOT/logs/error.log   # 看异常
cat $GQ_ROOT/run/last_bar.ts         # 看续传锚点
git -C $GQ_ROOT/repo log -1 --oneline# 看当前部署 commit
```

状态判定语义（与 `UX_VISUAL_SPEC.md` 颜色规范一致）：正常绿 / 警告橙（如 last_bar 略旧）/ 错误红（服务 down、RQData FAIL、disk 高）。

---

## 15. 每日巡检清单

由 launchd 每日固定时刻触发 `scripts/gq_daily_check.sh`，或你手动跑 `gq_status` + 以下勾选：

- [ ] 服务进程存活（pid 存在，uptime 合理）
- [ ] launchd 状态 loaded
- [ ] `last_bar` 新鲜度（交易时段内 ≤ 间隔阈值；非交易时段允许旧）
- [ ] RQData 最近成功拉取时间（≤ 阈值）
- [ ] 企业微信最近发送状态（dry-run/live + 成败）
- [ ] 日志体积（无单文件异常膨胀，轮转生效）
- [ ] 磁盘剩余（≥ 10%，否则告警 + 清理旧备份）
- [ ] 当日数据备份存在且完整
- [ ] 当日配置备份存在
- [ ] 错误日志无 P0（密钥泄露 / 自动交易 / 越权）
- [ ] `DEPLOYED_COMMIT` 与正在运行的 commit 一致

任一 ✗ → 按 §13/§12/§10 对应策略处理；P0 类（密钥/越权/自动交易）立即按 `SECURITY_HANDBOOK.md` 一票否决升级。

---

## 16. 部署前检查清单

部署 = 在 Mac mini 上把生产代码切到新 tag（需你人工确认）。执行 `git checkout` 前核对：

- [ ] 新 tag 在 GitHub 已存在且 release notes 完整
- [ ] 开发侧已通过测试，`collect_result.sh` 结果包结论为通过（见 `TEST_EXPERT_HANDBOOK.md`）
- [ ] `$GQ_ROOT/repo` 工作区干净（`git status` 无未提交改动）
- ] `.env` 未被本部署改动（密钥不变更；若需变更，单独走 §17 人工确认）
- [ ] 已做数据备份（`backups/data-YYYYMMDD` 最新）
- [ ] 已做配置备份（plist / scripts）
- [ ] launchd 服务当前状态已知（部署时会短暂 unload/load）
- [ ] 已知回滚目标（`git tag` 上一个稳定版本）
- [ ] 部署动作由你本人执行 `git checkout` + `launchctl unload/load`（AI 不代执行）
- [ ] 部署后计划跑 `gq_status` 验证

任一 ✗ → 暂停部署。

---

## 17. 回滚方案

回滚 = 把生产代码恢复到上一稳定 tag（需你人工确认，AI 不代执行）。

步骤：

```bash
cd $GQ_ROOT/repo
launchctl unload ~/Library/LaunchAgents/com.guiyi.quant.plist   # 停服务（你确认）
git checkout v1.2.0            # 上一稳定 tag
git log -1 --oneline > $GQ_ROOT/run/DEPLOYED_COMMIT             # 更新记录
# 如数据异常需还原（极少）：rsync 从 backups/data-<回滚日> 恢复（你确认，不删历史）
launchctl load ~/Library/LaunchAgents/com.guiyi.quant.plist     # 重启服务（你确认）
$ gq_status                     # 验证：service running, last_bar fresh, rqdata ok
```

约束：

- 回滚**只动代码 checkout + 重启**，默认不动 `data/`（历史行情永不删）。
- 仅当确认某次写入污染了数据才从备份还原数据，且还原前先另存当前 `data/` 为 `data-pre-rollback-YYYYMMDD/`，绝不 `rm -rf`。
- 回滚后跑每日巡检（§15）确认无 P0。
- 回滚动作本身记录到 `scheduler.log`（不含数据内容）。

---

## 附录 A：与既有手册的对应关系

| 本手册章节 | 关联约束来源 |
|---|---|
| §0 红线 / 人工确认 | `SECURITY_HANDBOOK.md` 六条强制禁令 + 一票否决 |
| §2 / §3 git 边界 | `COLLAB_PROTOCOL.md` §11–12（Codex 不 push）、`SECURITY_HANDBOOK.md` §7 |
| §5 监听 / 断点续传 | `TEST_EXPERT_HANDBOOK.md` §5（长稳）、§3（确认收盘触发） |
| §10–13 失败处理 | `STAGE9_WECHAT_DELIVERY.md`（幂等键 / dry-run）、`TEST_EXPERT_HANDBOOK.md` §4/§5 |
| §13 真实发送开关 | `SECURITY_HANDBOOK.md` §10（企业微信机器人规则） |
| §14 状态语义 | `UX_VISUAL_SPEC.md` 状态色规范 |
| §16 部署前检查 | `SECURITY_HANDBOOK.md` 交付前检查清单 |

## 附录 B：V1 明确不做（避免过度运维）

- 不上 Kubernetes / Docker Swarm / 云托管。
- 不引入自建监控平台（用 `gq_status` + 企业微信系统告警即可）。
- 不自动拉取 GitHub（不自动部署）。
- 不自动清理 `data/` 历史。
- 不把备份上传任何云。
- 不跑多个互相竞争的进程管理器（launchd 单一自启入口）。
