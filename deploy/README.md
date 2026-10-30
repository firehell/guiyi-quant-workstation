# 运维拓扑与只读检查

本页描述安装顺序、现场校验和恢复条件；是否执行由 `AGENTS.md` 的交办任务范围决定。
文中“执行意图”指已交办目标与当前精确对象一致，不要求每个 phase 再向 owner 请示。

仓库唯一 active 运维链为：Mac launchd 受监督 Runtime → FRPC 本地隧道 → 腾讯云 FRPS → Nginx
HTTPS/Basic Auth 公网入口。腾讯云不运行第二套 API/Web 应用副本。

API 入口固定一个 Uvicorn 应用进程（显式 `--workers 1`，不受 `WEB_CONCURRENCY` 覆盖）。
Newow 的 snapshot token、重型门禁与在途去重都由该进程持有；同一入口的多 worker、多 API 副本
不属于当前支持拓扑，不能依靠连接粘滞或增加重试弥补。单进程仍通过既有同步路由线程池处理并发请求。
进程重启后旧 token 失效，返回既有分类 409，由客户端按既有规则清除关联状态并最多重建一次。
缓存和逐事实校验、取消、重型预算保持不变。启动参数检查不代替真实多连接 HTTP、浏览器和负载响应验收。
更改部署契约须进入新补丁候选；不得挪动旧 tag 或临时修改 Runtime checkout。切换后仍须核对实际进程与请求链路。

## 三段只读检查

按链路从内向外执行；以下脚本只读取状态，不启动、停止、重载服务，也不运行 migration 或数据任务：

```bash
# Mac：按每个服务绑定核对实际 root/tag/commit/generation 与监督进程、
# 已加载进程 commit 身份与本地 HTTP/Runtime health
./scripts/ops/macos/local-services-status.sh

# Mac：本地端口与 FRPC
./scripts/ops/network/local-tunnel-healthcheck.sh

# 腾讯云：FRPS 端口与隧道 upstream
./scripts/ops/network/tunnel-healthcheck.sh

# 公网：HTTPS、Basic Auth、Web/API/WebSocket 与关闭端口
PUBLIC_BASE_URL=https://<your_domain> ./scripts/ops/network/public-healthcheck.sh
```

隧道检查入口依赖同目录的 `http-probe.sh`；单独分发到 ECS 时须同时复制两个文件，见
[FRP 验收与分发说明](frp/README.md#验收)。

未认证公网检查预期 HTTP 401；提供 Basic Auth 后，页面/API 预期 200，
`/api/v1/market/ws` WebSocket Upgrade 预期 101。

## 发布工作树存储

发布与正式运行源码统一使用扩展盘的linked worktree，默认路径为
`/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/release-vX.Y.Z`，按版本命名。
最新发布树兼作正式服务源码根，不另建Application Support中的runtime克隆；安全配置、共享launcher和日志保持Git外既有位置。
外接卷launchd访问须通过宿主权限与真实启动/读回验证，安装器沿用`GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1`选项并核对所有required服务。

保留所有仍被 service-bindings、磁盘 plist 或现场进程引用的发布树；解除全部引用并完成现场读回后才清理。 SimNow还须检查installed/loaded的`--config`私有配置、稳定monitor身份锚中的API环境/SDK/账户根及许可路径；未知结构、不可读、链接或读前后漂移阻止清理。限定路径下的未决SimNow切换/恢复意图同样保留依赖；只有完整计划及正式终态证明闭合的记录才能作为历史，不能仅凭COMPLETE字样放行。只读 `python -m app.runtime_retention cleanup-plan /exact/root...` 汇总 binding/plist/loaded/进程引用；未知结果阻止清理，删除前重新扫描。未引用旧树不作为常驻回滚树。
SimNow v7普通完成记录的发布路径来自冻结的`snapshot.preimage.release`，须与原plan同字段及candidate的release身份逐值相等，tag/commit须与candidate及其code身份相等；candidate本身不要求存在root字段，若存在则须相等。原意图/plan/hash及完整闭合条件不变，不修改历史记录来解除引用。
创建新树、构建、render/preflight、切换和健康读回完成后，逐树核对精确路径、版本、dirty/untracked、已集成状态、配置/loaded服务与进程引用；有用户修改或引用时停止该树清理。
保留必要运行JSON与日志证据，不保留整棵旧源码；不删除tag/Release历史，不触碰develop/main、普通任务树、行情、DB、Scope或安全配置。
应用管理的worktree使用Codex archive工具，普通Git worktree使用non-force的`git worktree remove`；独立旧clone只有在精确清单与引用复核通过后才能清理。

修复默认向前发布补丁，不移动旧tag；需要恢复时可从Git重建精确旧版本。后续修复复用最新发布树的修复分支，发布新版本后改为对应版本名称；正式服务始终绑定已验证commit，不能把dirty源码冒充原版本。
安装器的原子失败恢复、preflight、身份校验继续保留；结果不明先停止相关mutation并只读核对，不能因清理而盲目重试。

## 按服务连续交接

新增稳定目录 `~/Library/Application Support/GuiyiQuant/service-bindings.json` 是启用新拓扑后的唯一身份入口。
每项固定 exact annotated tag、commit、发布根、代次、启用状态、合同内容指纹及实际 launchd label。
共享 `run-local-service.sh` 只做稳定分派，业务 launcher 保留在各自发布树。普通发布不覆盖共享分派器。
API/Web 配套影响；未知依赖按全服务受影响。v1 对共享合同只接受内容指纹相等，不能证明兼容时阻止混合版本。
所有已启用服务都参加兼容检查，即使它们全部在本次受影响集合中，也不默许顺序制造未知混合版本。

安装器的四个新入口在 legacy render/mutation 之前分派（计划文件需当前用户独占 0600）：

```bash
./scripts/ops/macos/install-local-services.sh --plan-topology --candidate-root /absolute/release-tree --tag vX.Y.Z --commit EXACT_SHA
./scripts/ops/macos/install-local-services.sh --apply-topology-plan --plan /absolute/topology-plan.json
./scripts/ops/macos/install-local-services.sh --plan-release --candidate-root /absolute/release-tree --tag vX.Y.Z --commit EXACT_SHA
./scripts/ops/macos/install-local-services.sh --apply-release-plan --plan /absolute/service-plan.json
```

前两项用于一次性迁移：权威 Session 证明全部 operational 品种 BREAK/CLOSED、末根 completed 覆盖及确认宽限结束，
冻结旧 plist/loaded 身份与发送互斥锁后停止旧拓扑，执行 0051、证明空 journal、显式初始化 0-0，启动消费者再启动 Feed。
旧进程若不具备可证明的发送收尾合同，返回 `BOOTSTRAP_LEGACY_*_DRAIN_UNSUPPORTED`，不能强杀、伪造空闲或补发。
迁移 journal 结果未知时保留 preimage 并禁止复用；只能先精确只读核对，不能把失败当安全重试。
首次迁移兼容旧独立日志轮转：按固定脚本字节、plist、loaded参数/cwd与空闲状态冻结旧未版本化身份；不借用API根伪造旧tag。迁移后使用正式服务绑定与发布树内脚本。
历史Alert失败诊断继续保留；无锁预检不声称发送空闲，只有完整旧符号锁与Newow发送锁持有、Canonical通知路径排除及现场身份验证后才允许收尾。

后两项只交接受影响的服务。候选使用临时 label，最多 120 秒纯读取/计算预热。
旧版停止领取，最多 10 秒收尾并释放 OS 独占锁；超时取消，旧版恢复领取。
候选取得新代次后，从原提交进度续接。现场核对 plist、loaded PID/env、心跳、实际 ready、冻结输入边界与消费进度；
API/Web 还读回 HTTP。定时服务仅在维护锁与无运行 PID 证明成立后重新注册日历，不 kickstart 业务任务。候选 label 晋升后继续由 KeepAlive 监督，直到下次被精确退休。
采集器本身的交接仍限于权威休息段、实际 pending=0 与 source cursor=tail。
API 始终一个进程，短暂重启会失效旧 snapshot token。UI/API 发布不会切换未受影响的 Feed/Live/Alert/Reference。

交接后的未知结果写入 `deployment-outcome.json` 并请求候选协作停止领取，不恢复旧发送权，不重试 provider。
全部正式副作用受 OS 锁与新代次二次核对约束；TTL、健康标签或候选预热不授予发送权。
新绑定存在后，旧一根安装器的 mutation 模式拒绝执行；只读状态按各服务根检查，不能用 API 根代表全部 Runtime。

工程测试、发布、现场交接及自然连续性验收分别记录。专用 Redis/PostgreSQL 测试不发送真实推送；
自然信号未发生时保留待验收，不能宣布 `RUNTIME_READY`。

## 配置与变更 Gate

- [`deploy/launchd/`](launchd/)：Mac API/Web/Live/after-market/Alert、默认未安装的 weekly audit/reference worker 与日志轮转模板；验证命令见
  `TESTING.md`。
- API、Alert 与 Reference worker 模板只共享一个 Git 外 `GUIYI_ALERT_NOTIFICATION_CONFIG_PATH`；PushPlus token 与 Topic code
  不进入 plist、仓库或状态输出。

Newow 动作通知由 Reference worker 生命周期内的独立 Delivery 线程消费已提交 forward 动作，
默认关闭；四策略×1w/1d/60m 的启用边界、Scope、Topic fingerprint 与 one-shot claim 保存在
0050 新建通知表。启用后只发送新的 BUILD/REDUCE/CLEAR，失败和未知不补发，不改旧 Alert Scope。
停止发送使用通知 policy disabled，不删除 claim；provider accepted 不证明 Topic 成员实际收到。
合同见 [Newow 动作通知](../openspec/specs/newow-action-notifications/spec.md)。
- [`deploy/frp/`](frp/)：FRPC/FRPS 隧道配置与分段验收。
- [`deploy/nginx/`](nginx/)：腾讯云 HTTPS/Basic Auth 反代模板。

安装器会把渲染时 checkout SHA 写入每个 plist 的 `GUIYI_RUNTIME_COMMIT`；只读状态脚本同时核对已加载
`GUIYI_PROJECT_ROOT`、该 commit 与当前 supervised checkout，避免把移动后的工作树 HEAD 当成已运行版本。

`--render-only` 可用于本地无副作用验证。任何 launchd 加载/重载、Runtime switch、腾讯云配置应用或
Nginx reload 都是真实外部操作，须属于交办目标并核对环境、服务范围与现场身份；无需逐项再次请示。
Reference worker 默认只在 `--render-only` 中渲染。`--confirm-reference-worker` 仅加载该 label，
要求已安装 API 的 root/commit 与候选完全一致、共享 launcher 字节一致，并创建权限为 0600 的
exact `.run/reference-worker-enabled` marker；失败时恢复 marker、原 plist 与原加载状态。
`local-services-status.sh` 对已启用的 worker 核对 marker、loaded root/commit 和运行状态，
对无 marker 的残留 plist 报错。安装模式不创建/激活 forward 流、不执行 0048 migration，
也不代表 Runtime 已切换或模型已接受；这些仍按 P9 精确批次分别验证。
交办目标覆盖发布、切换及必要恢复时可连续完成，分别核验对应 Gate；跨会话恢复与有界重试按 `AGENTS.md`，
不增加逐命令审批，不放宽 exact identity、preflight、兼容性或安装器失败恢复合同。

### Weekly operational full-history audit

`com.guiyi.quant-weekly-audit.plist.template` 从每周六 09:00 开始至 23:00 每小时提供一次有限触发机会，
用于覆盖休眠/唤醒或短时不可运行；应用层以本周六 09:00 为身份，整周最多建立一次真实审计尝试。
后续触发只返回 `already_attempted`，不会覆盖 `passed/findings/failed/skipped_busy`，因此不是失败 retry。
任务仍是 `operational_full_history` 只读审计，不含 `RunAtLoad/KeepAlive`，也没有 provider/data write 或通知能力。
`--render-only` 会渲染该模板，但不安装或启用它。

每周 label 只能在获得该次安装的明确外部操作意图后，从目标 exact Runtime checkout 执行：

```bash
./scripts/ops/macos/install-local-services.sh --confirm-weekly-audit
```

安装器在任何外部 mutation 前要求已安装 API plist 是非 symlink 普通文件，其
`GUIYI_PROJECT_ROOT` 与当前 checkout 完全相同，`GUIYI_RUNTIME_COMMIT` 与当前 40 位 Git SHA 完全相同。
此模式原子写入独立的 `.run/weekly-audit-enabled` marker，并只替换/加载
`com.guiyi.quant-weekly-audit`：不 bootout/kickstart 其他 label，不写 Market/Alert marker，
不替换共享 launcher/log rotator。weekly plist 直接指向该 exact checkout 中的
`scripts/ops/macos/run-local-service.sh weekly-audit-scheduled`，避免使用其他 checkout 的启动器。

`local-services-status.sh` 只从既有 Runtime health 打印有界的盘后 stage/attempt/symbol/成功操作数，
及独立 weekly status/through/findings。未安装显示 `disabled`，本周时点前显示 `not_run`，已过时点且没有本周尝试显示
`missed`；诊断不会自动运行审计、修复数据或通知。weekly label 不是现有 operational health 的 required service；安装成功也不证明
首次自然审计已通过、release 或 Runtime promotion。

### Market Runtime promotion preflight

#### Interrupted-run closeout before promotion

先使用已审查的新 CLI 对现役 root/commit 和原状态字节 SHA-256 执行一次只读核验：

```bash
guiyi data close-interrupted-after-market --runtime-root /absolute/current-runtime \
  --runtime-commit EXACT_40_HEX_COMMIT --expected-status-sha256 EXACT_64_HEX_SHA256
```

只有交办目标包含该收尾、且现场身份与精确计划一致时才追加 `--apply`。该操作只将原运行记录为 interrupted，
不证明更新完成，不修复行情、不安装调度。blocked/结果不确定立即停止，不删 JSON、不重跑；明确写入不确定时
须重新只读核实。旧 Runtime reader 不认识 schema v4/v5 会降级；新候选 reader 可以读取，但 promotion 的
phase/Live snapshot Gate 完全保留。安全收尾、发布、五服务同步和周审计安装仍是各自受控操作。
现役 v1.10.5 writer 下次自然运行会写回 schema v2，不能承接 v5 中断摘要；reader 降级不阻止覆盖。
收尾 apply 前须核对下一次旧任务窗口，确认届时使用任务目标内的新 writer，或任务范围确实包含暂停旧盘后调度；
保留收尾读回证据。不得仅凭收尾结果推导暂停调度或切换 Runtime。
旧 Runtime 在五服务解除引用前不得清理。

#### Compatible recovery proof and failed-install boundary

部署前的恢复候选必须是已经发布的 exact annotated tag、该 tag 的 peeled 40 位 commit，以及位于独立绝对
路径、detached 且内容不变的目标 root；候选代码必须能读取 schema-v5 盘后终态并保留规范化
`last_interruption`。v1.10.5 与 v1.10.6 不支持这个状态合同，schema v5 写入后不得将它们列为 rollback
或恢复候选。

候选代码可先对现役 Runtime 做一次只读兼容性证明：

```bash
guiyi data compatible-recovery-proof \
  --candidate-root /absolute/candidate-root \
  --candidate-commit EXACT_CANDIDATE_40_HEX_COMMIT \
  --runtime-root /absolute/current-runtime \
  --runtime-commit EXACT_RUNTIME_40_HEX_COMMIT \
  --expected-status-sha256 EXACT_64_HEX_STATUS_SHA256 \
  --expected-operational-products-sha256 EXACT_64_HEX_PRODUCTS_SHA256
```

该命令复用 `RuntimeDataBinding`，重新核对现役五服务、root/commit、精确 status 字节、operational
集合及 DB/Redis/Canonical/RQData 配置身份，只输出候选 commit/tree、hash/count、规范化中断摘要与配置
类别，不输出配置值。它没有 provider、DB/Canonical 写入、网络、通知、launchctl mutation、marker/plist
mutation 或安装能力；结果中的 `recovery_ready` 固定为 `false`，直到发布 Gate 另行证明 exact tag/peeled
commit 和 immutable recovery root，并确认恢复属于交办目标。

Market 安装固定先加载 idle 的 `com.guiyi.quant-after-market`，再加载并 kickstart
`com.guiyi.quant-live`；新 writer 的 root/commit 与 status ownership 因而先于新 Live 建立。新 root 不继承旧
root 的 `.run`，安装器不复制或改写旧 schema-v5 terminal status；旧 status 仍留在旧 root，作为 D 的不可变
审计事实。新 writer 首次自然运行才在新 root 建立自己的 status。

health 的跨版本历史证据另存 `.run/after-market-history.json`。Market 安装在只读 preflight 通过后
从精确旧 authority 保留有界终态摘要和原 commit/hash，不创建新 `after-market-status.json`，也不改
promotion predicate。历史成功在 API 中标为 `retained_success`，历史失败为 `retained_failure`；
当前失败、last_failure、卡住和不可读状态始终优先。相同源的重复保留幂等，冲突失败关闭。
Market 安装器由 Python wrapper 以不创建文件的方式独占旧 writer 既有 OS guard，继承同一 fd
并校验 inode/uid/锁排他性，从 preflight、证据保留一直持有到服务安装或失败恢复结束。
guard 忙、缺失或不安全时停止；genuine first-install 没有旧 writer 才不需要该锁。
旧树退休前仍封存原状态字节；历史证据不是新版本自然验收。首次补回已归档的历史证据使用
`python -m app.market_data.after_market_history --target-root EXACT_ROOT --source-status EXACT_FILE
--source-commit EXACT_COMMIT --expected-source-sha256 EXACT_SHA`，默认只读；精确校验后才加 `--apply`。

安装器在 candidate mutation 前只为 shared launcher、log rotator、after-market/Live installed plist 和两者
loaded/absent 状态保存有界精确前像，不复制或修改 status。此后从 shared launcher/rotator 的 copy/chmod、
activation marker 准备到 plist/load 的整个 mutation 区间都使用同一个失败恢复出口。部分失败时先按已尝试
label 的逆序 bootout candidate，再恢复文件并按原状态仅重载先前 loaded 的服务。安装器通过 Python
`runtime_status_authority` 取得所有 launchd loaded/absent 结论，shell 不解析 launchctl 输出；仅 exit 113 加
exact requested label/user 缺席可成为 absent，其他结果一律 unknown/fail-closed。除逐字节和 loaded/absent
状态外，每个恢复为 loaded 的服务还必须由 Python authority 精确核对进程 root、commit、arguments、working
directory 与 environment，全部通过后才恢复 activation marker 前像，并明确输出
`partial market install is blocked`。该恢复不会重试安装，也不会加载原本 stopped 的旧 writer；下一次安装仍需
新的 promotion preflight 与交办目标内匹配的安装操作。任一 candidate label 仍 loaded、bootout/print 不是当前请求
label 的 exact not-found、恢复或读回结果不明时，marker 保留且状态为 unknown/blocked，不能声称 stopped 或
recovered，也不切换到 v1.10.5/v1.10.6。

两个 market label 已成功启用且 marker 已提交后，前像或 marker backup 的删除只是 post-commit cleanup。
cleanup 不确定时不回滚已经提交的 Runtime，安装器以成功退出并显式输出
`cleanup=unknown retry_safe=false`，同时警告 `do not retry`；调用方必须把它解释为“安装已发生、清理状态未知”，
不能按普通安装失败自动重试。

#### Read-only promotion predicate

`install-local-services.sh --confirm-market-runtime` 只会执行一次
`run-local-service.sh market-runtime-preflight`。该 preflight 是只读检查，发生在外部 activation marker 准备、
runtime script 写入、已安装 LaunchAgent plist 替换以及任何 `launchctl` mutation 之前；仓库内 plist render
不属于这些外部 activation mutation。若 preflight 阻断，安装器非零退出，且不触碰 marker、runtime directory、
installed plist，也不执行 `launchctl` mutation；为解析 supervised authority 而进行的只读 `launchctl print`
可能已发生。

针对 stopped-terminal 的受控安装调用必须由外部受审 receipt 提供 SHA，而不是从现场 status 临时自算：

```bash
GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256=EXACT_REVIEWED_64_HEX_SHA256 \
  ./scripts/ops/macos/install-local-services.sh --confirm-market-runtime
```

该变量缺失或与现场字节不符时 stopped 分支失败关闭；genuine first-install 不需要也不消费 status。

preflight 只读取 operational universe、权威 Calendar/Session phase、既有 immutable Live subscription snapshot 与
公开 after-market status。允许的通过原因只有：完整且 identity 有效 snapshot 的 `snapshot_ready`；所有品种真正
最早权威 Session start 前的 `before_first_session`；同日 after-market 已 passed、且 products 与 operational
顺序完全一致的 `after_market_complete`；以及无 current trading day、无 active Session 的
`non_trading_interval`。它不会把“下一段 session 尚未开始”误作 `before_first_session`。

跨 checkout 时，preflight 只调用 Python status authority，不在 shell 重复解析 terminal JSON。正常 loaded
分支从当前 supervised after-market launchd root 读取 status，并与 installed plist 声明交叉校验。D 后的
stopped 分支只接受 exact schema-v5 interrupted terminal、保留且未变的 installed plist/root/commit/config、
launchd domain 可读且 after-market label 明确 not-found、另外四服务身份精确，以及 Live/Alert 双 heartbeat
新鲜且 recovery guard 已启用；调用方还必须在 source runtime env 之外提供受审 terminal bytes 的 exact
SHA-256，缺失或不匹配均阻断。读取前后重检任一 status/plist/root/process/config/heartbeat 漂移或 writer
重现均阻断。仅 genuine first-install 可使用 candidate root，并同时要求 label 明确 not-found、没有 installed
plist 且 candidate status 不存在；该模式不会读取残留或预置 `.run` status。任何 domain/permission/label 命令
错误，或 root 缺失、畸形、不一致，均以 `MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE` 阻断；runtime env
不能覆盖 Python 选定的 status path、account HOME 或 caller 提供的 expected terminal SHA。

stopped-terminal 只解决 status ownership；不会把 promotion 判为通过。`snapshot_ready`、
`before_first_session`、`after_market_complete` 与 `non_trading_interval` 四个独立 predicate 原样保留。

已开始后的缺失 snapshot、无效/部分 snapshot、未知或分歧的 phase/session authority，以及 running、corrupt、
unreadable 或 chronology 不可能的 after-market state 一律阻断；公开 block reason 仅为
`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED`、`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_INVALID`、
`MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。没有 override、repair、synthetic snapshot、retry、replay 或
fallback；通过预检本身不构成 Runtime promotion、release、Runtime ready 或 production verification。


### 节假日供应商晚到恢复

Market 盘后仍在本地 18:05 自然运行，`RQDATA_NOT_READY` 或
`NEXT_TRADING_SESSION_NOT_READY` 最多等待一小时重试一次。盘后 daily 写入前必须
检查全部精确目标的源响应，冻结已验证批次再写入；类别级 ready 不能代替逐目标完整性。
缺 endpoint 的预检不发布任何历史分区；质量异常、部分提交、未知提交结果不能纳入自动恢复。

两次均因上述安全的晚到原因失败时，独立记录失败交易日和 operational 范围，
在失败日加两个自然日（即使是假日）19:05 由 `com.guiyi.quant-late-provider-recovery`
只检查一次。米筐没有已确认的公开机器公告接口时记录 announcement=unavailable，
不声称不存在公告，按 owner 决策继续默认检查。恢复状态与原自然 after-market 状态分开。

检查前原子落盘 claimed；崩溃、源仍不齐、维护锁冲突、写入或读回失败均消费该次机会，
不自动补跑。19:05 前不运行；延迟超过一小时或错过当日记 expired。源齐全后，同一范围
通过有界 metadata 同步、daily-recovery 精确计划/CAS、全部源完整性和物理读回，
才记录恢复 passed。只清理原交易日 Live，原自然失败不改成成功，不补发通知。

下一交易日与短周边界仅由 RQData Calendar/Session 证明：例如 2026-09-30
下一交易日是 2026-10-08，10-10 调休工作日不是交易日；不得用工作日算术替代。
新服务随已交办的 Market Runtime 安装，schedule-only idle 不算服务失败。
升级时须显式保留未消费的延后恢复状态，不能以新的空状态丢弃未完成检查。

### 持续记录的跨版本恢复状态

Market正常日切准备与Newow历史刷新分别使用既有稳定运行目录
`~/Library/Application Support/GuiyiQuant/market-day-metadata-preparation.json`和
`~/Library/Application Support/GuiyiQuant/newow-historical-refresh-state.json`，不放在release `.run`中。
对应独立锁、0600文件、原子提交及fsync保持；切换版本、退休worktree不得删除或重新初始化。
`inflight/blocked`仍须读回，不因新版本重新消费provider或重建资产；不兼容状态版本须显式迁移或阻断。
本次首次启用没有旧运行状态需迁移，initial历史receipt继续保留在任务证据目录。

Reference 历史刷新只在前台健康轮授予本地许可后领取一个工作单元，且 operational 60 品种
均由既有 MarketPhaseResolver 确认为 BREAK/CLOSED、下一 Session 距今超过 140 秒时才开始。
交易中、临近开盘或权威未知时保留 pending 意图并延后，线程等待不表示历史资产已完成。
单次许可最多一个已提交批次，保存现有恢复状态后在既有批次边界让出；完整输入读取仍保持
Canonical 维护锁。普通扫描不会反复取消长输入读取，真实 completed 观察与收尾会协作请求退出。
本地许可和两秒等待不授权接管源锁，超时仍按真实 SOURCE_BUSY 阻断。
只有服务明确证明在任何写入之前中断，才可恢复 pending；写入后的裸取消及未知状态保存
保持阻断与原始意图，不凭已有旧 resume token 盲重试。

首次拓扑切换的旧launchd KeepAlive可能在正常SIGTERM后复活；收尾必须确认原PID退出，在完整发送锁持有期间重新验证复活定义并卸载，不能把label出现新PID视为原PID仍在发送。真实print-disabled同时支持enabled/disabled及旧布尔格式，未知值阻断。

仅当旧拓扑已经局部停用、schema仍0050且没有新registry/观察基线/owner/安装preimage时，`python -m app.runtime_bootstrap recover-readback --output <absolute-plan>`冻结有限恢复计划；`recover-legacy --plan <absolute-plan>`重新校验后恢复原loaded Web启用状态和原空闲日历服务，不kickstart。原未知journal按原字节保留，失败恢复attempt禁止盲重试；恢复终态通过后另生成新的拓扑计划。该入口不处理已经迁移、安装或候选发送过的未知结果。

### 休市窗口整组发布

当待发布共享合同改变、不能与旧消费者并行时，使用 `install-local-services.sh --plan-cohort --candidate-root <absolute-release-root> --tag <annotated-tag> --commit <peeled-commit>` 冻结整组计划，再用 `--apply-cohort-plan --plan <absolute-plan>` 单次执行。
仅支持现有十服务、六常驻全部启用的向前版本；数据库合同默认不变，仅已预装的0052→0053新增接收表可按
`reference_inbox_preinstalled_additive_0053_v1`提供精确Git差异、单链head及新鲜只读schema/约束/触发器证明；
另允许已预装的0053→0054不可变Inbox恢复结果表，按`reference_inbox_recovery_preinstalled_additive_0054_v1`核对原表、原guard不变以及新增表完整约束/触发器；
证明写入计划并在停服前和CAS前重验，其他schema变化不放行；保留原定时服务启用状态，不启用缺省任务。
所有 operational 品种须由权威 Calendar/Session 证明休市、无 grace、距离下一 Session 超过660秒；未知仍阻断。
计划有效15分钟，预热后和CAS前重新验证；停机预算600秒。预热只读Canonical，不伪造Live订阅、消费信号或发送通知。
日历先暂停，Feed先排空，全部旧所有者退出后持维护/所有者锁，一次CAS提交全部新绑定；消费者先于Feed启动，最后仅注册原日历。
CAS前失败仅在旧绑定明确未变时恢复原定义；CAS开始后未知结果禁止自动回滚或重试，需只读核对。私有attempt、原件和旧失败记录保留。
整组计划冻结已真实停驻owner的原drain；排空时沿用精确request，失败恢复不得取消或重启该旧owner。
原owner仍存活时保持原PID停驻；若已退出则保持定义缺席并保留`restore_unknown`，等待前向恢复读回，不能将保留drain视为旧读端可安全重启的证明。
闭市空闲证明必须与自然completed Bar、Event及送达分开；工程切换成功不声明整体Runtime Ready。

交接保存稳定历史刷新控制文件时，精确稳定目录路径复用该控制读取器既有64,000,000字节上限；原fd、防链接、owner、nlink、权限和读前后身份校验不变，普通配置与其他路径不放宽。

整组预热对已有恢复journal使用限定8MiB读取（仅稳定目录直接子项的generation/deployment/scheduled-update三类），原配置文件上限、防链接及读前后身份校验不变。
仅cohort显式午休预热可对BREAK使用Canonical：逐次fresh Session证明、无current Session、下次开市大于660秒，完整Scope计算前后须通过原生Feed静默证明；证明失败拒绝且不回退实时窗口。普通Alert读取不启用此选项。

仅cohort闭市Canonical预热可将苏冰D1/W1 quality-v2的明确WARMING_UP逐路记录，不能计入calculated或声明信号就绪；原生预热默认strict，未知/质量/映射失败仍阻断。预热证据在任何停机前持久化。

完整Alert scope的只读预热上限600秒，其他子服务120秒；均在停机预算开始之前。该上限不延长15分钟plan有效期，预热后计划过期仍取消，不能带过期计划停服。
新的预热失败状态保留固定service/condition及白名单公开码，区分子进程超时、无效输出和候选拒绝；不保存异常原文。
Newow与SuBing forward共用MDS发布边界：Session完成不等于Canonical已发布，18:05前仅当日未发布尾部可等待；
旧欠期、物理源、owner及质量异常仍阻断，W1仍使用完整自然周。普通页面窗口及真实前像/seed预热不变。

卸载每项仅请求一次；在既定停机预算内等待真实label缺席与旧PID退出。CAS前恢复须先等待本控制器已请求的teardown完成（独立有界恢复等待），再取消drain，按原loaded前像恢复，不把异步仍loaded误当恢复成功。

若CAS前进入`restore_unknown`，先恢复并只读核对原态；`install-local-services.sh --resolve-cohort-restored --plan <original-plan>`仅审计历史计划身份，不执行过期计划。它要求exact旧registry/SHA、原plist及loaded前像、fresh owner/实际PID/OS锁、空闲日历、Scope/config哈希与本attempt不同目标label缺席，写唯一私有恢复receipt并fsync后才更新global指针。原attempt/state.json逐字保留；postCAS unknown、新registry或任何漂移均不能使用此入口。之后切换必须全新plan/attempt，全局工作树引用另按retention核查。


### 已完成CAS后的同版本启动恢复

版本CAS已被独立证明完成、但后续启动验收失败时，保留原cohort的 `outcome_unknown` attempt，使用独立 `postcas_forward_recovery_v1` 计划和receipt恢复当前已安装generation。该入口不安装、不CAS、不改配置、不回退版本或接收语义，只取消当前generation的精确drain并按消费者、Feed、原定时服务顺序恢复。混合安装、未知writer、身份/配置漂移或不能证明已完成CAS时拒绝。

旧cohort的完整保护快照仍按原old根逐字校验；当前运行根的完整保护快照独立冻结进新audit并逐阶段固定，共同真实路径、私有配置、DB/Scope及已启用marker均须保持权威，不按basename抹平两个根的历史状态。

恢复控制器从独立精确tag/commit的干净正式发布树执行，计划冻结控制器身份并逐阶段复验；控制器版本与运行服务版本分别记录，不能将控制器新发布冒充消费者已升级。

当精确当前Live在固定drain下由launchd反复exit1重启、不能稳定停驻时，计划可显式冻结 `live_restart_intent`。只允许部署/维护锁内核对同一label、binding、安装/launcher、drain与实际进程身份后，先持久记录单次effect再发一次原生bootout；确认整个label absent、所有已观察PID退出、owner锁空闲，重验原件/数据库前缀及pending/UNKNOWN后，才可启动原Live和其他消费者。禁止kill、重复bootout、把active冒充parked，或根据未公开日志猜测内部异常。任何退出、锁或提交事实不明即停止相关恢复。

同版本恢复使用正常服务启动的权威Session/rank1/注册交易日校验，可处于TRADING、BREAK或CLOSED；不复用版本promotion的休市660秒条件，也不放宽原cohort条件。新计划仍有15分钟TTL、600秒总预算，部署/维护/owner锁及各阶段独立读回；只恢复原启用集合。

`confirmed_intake_halt` 仅接纳两层原生失败记录：A为Live卸载前缀，B为已确认A后启动消费者、在intake失败并停驻的前缀。新计划同时绑定A/B的public/private plan、state和effect身份；重新证明全部当前消费者精确parked、owner锁可取、Feed与日历absent、pending capture及UNKNOWN为0、完整源/DB/routes和所有当前尾部已ACK追齐。旧接收摘要不可逆时不得用摘要不等推断漂移或直接忽略，须以完整当前前缀校验替代；新快照固定静态context并逐阶段复验。只接受此两层链，不循环接纳新的未知attempt，不执行bootout，成功receipt解析A/B且保留原字节。任一额外effect、第三未决、漂移或未ACK当前尾部均拒绝。

`confirmed_feed_halt`只接纳该A/B之后的精确C：C必须为`confirmed_intake_halt`，仅有同generation的consumers、合法schema2 intake及精确label的Feed bootstrapped三个effect，在verified失败且没有成功receipt。完整冻结A/B/C公共与私有plan、state、effects和保护前像；其他或第四层unknown继续拒绝。
首次用`plan --close-feed-only --predecessor-recovery-plan <C>`冻结`stop_after=feed_close`，该终点进入plan hash。当前Feed须精确loaded且parked，冻结binding/plist/launcher/drain、所有已观察PID/后代及完整source原件/identity索引和completed DB/routes前缀。apply持部署、维护及owner锁，先耐久记录意图，仅调用一次原生bootout；等待label absent、全部观察PID退出、owner锁free及两次前缀不变，期间新增观察PID必须先入effect再验证退出。结果不明保留unknown，不重复卸载、不接纳该unknown为新前驱。
关闭成功只生成`feed_close_readback_v1`及`feed_closed`终态，不启动任何消费者、不修改全恢复成功指针，也不把A/B/C解析为已恢复。后续正常恢复须显式`plan --predecessor-recovery-plan <C> --feed-close-plan <关闭计划>`，冻结关闭计划公共/私有plan、state和receipt字节，并重新现场证明关闭与输入前缀；这些字节在每个后续阶段继续校验。只有正常恢复最终成功才由新receipt关联闭合A/B/C，原件保持不变。缺失heartbeat或单独parked状态不代替此次进程退出关闭证明。

若该close-only D仅有已记录的Feed卸载请求，随后在`feed_stop_intent`以`RuntimeIdentityError/SERVICE_IDENTITY_INVALID`停为unknown且无成功receipt，可显式运行`confirm-feed-close --plan <D>`。这是原件历史审计及新鲜只读确认，不执行过期计划、不调用launch mutation、不生成新恢复attempt。它要求精确C/B/A及D公共/私有plan、state、effect不变，当前Feed label absent、全部观察PID退出、锁free、其他消费者仍精确parked、完整双输入前缀与D意图一致且无其他unknown。仅写一次`feed-close-confirmation.json`关联D原字节和独立控制器身份；D原state及unknown保留。后续E只通过显式D引用读取该确认并逐阶段pin其字节，D不能作为额外递归前驱，任意其他unknown继续阻断。
卸载等待中的PID采样只核对精确root/commit/tag/generation、arguments及合法header PID，不把过渡state冒充ready；最终关闭仍须独立证明label缺席及PID全集退出。新代码不能倒推旧D未留存的具体launchd过渡状态。

接收快照schema2记录采样初始current_tail与结束final_tail。两个新鲜独占接收轮只有在前缀/合同不回退且ACK和DB共同前进，或两轮每分区均ack=current_tail=final_tail时才证明存活；空闲不由Session CLOSED或调用者标志推导。合法零进展且仍有积压只在原预算内等待，完整性或时序错误立即失败。

30秒活性样本过期不等于前缀损坏。等待循环逐次验证全部快照（包括同一owner cycle）的静态context、原件/routes、ACK及数据库前缀非回退；只有这条连续链通过后才能滚动活性采样窗口。过期样本本身不授予活性，仍需两轮不同且新鲜的owner cycle，并在最终身份校验后重新检查样本新鲜度。原120/240秒局部预算、600秒总预算及计划期限不延长。
新的verified失败在原生attempt中仅补充固定子步骤与合法带时区采样时间；接收异常仅保留精确类型的固定公开码，不记录异常原文或回溯。新诊断不能用于倒推旧attempt未记录的失败原因，也不增加对未决恢复前缀的接纳范围。

接收存活由独立typed证明确定：原冻结SourceProof完整不变、active v2边界与原升级意图匹配、所有已ACK原件及冻结routes在数据库中逐条完整，其他分区不回退；有积压时须两次新鲜有界receiving cycle显示ACK与数据库前缀共同前进。计算等待及BLOCKED分别展示并继续逐流fence，不借此清除失败或重试；接收错误、原件/routes/身份异常、接收提交未知、恢复前未归属pending capture、失权或超时拒绝。旧尾部全部追齐是后续独立验收，不冒充启动完成条件。

若恢复attempt在单次Live卸载后进入unknown，而独立原生读回已确认label缺席、全部观察PID退出、owner锁空闲及其余消费者仍停驻，可用显式 `--predecessor-recovery-plan` 冻结仅此已确认前缀的continuation。新计划绑定原cohort及前驱operator/private plan、state、effect字节hash，前驱effects必须仅为Live卸载意图，target必须同一当前generation；从consumers开始，路径不得调用bootout。其他未决attempt仍阻断。成功的新receipt通过精确关联事实闭环此唯一前驱，两个原unknown文件都不改，不能以通用allow-unknown、清记录或重跑旧计划代替。

恢复成功写新receipt并更新全局恢复结果指针，不能把原attempt改为成功。结果未知时停止相关mutation并独立读回，不盲重试。恢复前缺失的自然原件显式记录，禁止用provider历史补成Live事实；不回放Alert或补发旧通知。

### Reference receiving v2 交接

先升级0053新增两表，发布兼容版时接收协议仍为旧版；`ReceivingProtocol.request` 只在schema可读后登记
稳定的升级意图，不改Redis。原生独占所有权交接后的实际启动冻结现有各日游标/尾部，再原子启用v2。
候选warmup只读，不写升级状态或生产intake_error。不得同时启动两个接收者。
已声明 `reference_backlog_handover_v1` 的精确候选允许保留Reference未确认后缀：计划冻结v2意图、0053与启用流身份、全分区及游标前像；全部旧所有者与Feed停驻后逐条校验原件及identity索引，冻结完整hash、数量、容量与边界，并在停服前和CAS前独立重验。其他消费者仍须追尾，pending capture须为0；未知、冲突、缺原件、容量或原期限不满足仍取消。控制器不推进游标、不激活协议，由新实际所有者独占启动。
首个v2持久接收后禁止回退到旧“计算完成才ACK”的语义；只能用兼容版本或前向修复。
0053原件非空时downgrade拒绝，禁止删除原件以完成回滚。
接收异常持久保留并停止intake；已提交的各流原件仍可计算，health分别呈现二者。

首次激活但未有自然Bar的Reference流，预热只能在完整原始flat seed、receipt、manifest及散列链验证后记为initialized，
不能记为calculated；已计算但缺前像继续拒绝。v2每轮有界接收可发布receiving_cycle，原计算ready/blocked不改。
原生交接仅在独立只读复核protocol/schema/owner/游标及所有当前冻结head后，分别接受durable_receiving、
backlog或waiting_history运行模式；普通PENDING必须无错误，历史等待与worker阻断逐项全等。
身份漂移、BLOCKED/UNKNOWN、接收异常及未证明fusion依赖仍拒绝，所有旧身份与时限Gate不变。
DB队列空不能证明Redis追尾，运行切换及自然业务验收仍分别记录。

### 消费者恢复失败后的停驻确认

`python -m app.runtime_cohort_recovery reconcile-stopped --plan <failed-plan>` 仅接纳同一安装generation、
完成consumers后在intake超时且从未启动Feed的失败边界。部署/维护及真实owner锁内重证当前parked、Feed与日历缺席、
观察PID退出、安装/配置前像及完整原件/routes/ACK前缀；使用当前drain，不恢复旧控制文件。追加唯一
`stopped-confirmation.json`，保留所有原unknown/state字节，不改全局成功指针。相同事实重复确认幂等，额外effect、
未关联unknown或漂移拒绝。历史关联按有限扁平文件哈希集合验证，不递归增加特殊前驱模式。

随后使用 `plan --source-plan <original-cohort> --stopped-confirmation <confirmation> --output <new-plan>`
冻结新15分钟计划，预算仍600秒；`apply-plan`一次恢复当前generation的消费者、接收、Feed、综合校验及原定时服务。
成功receipt关联闭合该事故，旧失败不改写。收尾确认本身不代表服务恢复，也不允许重跑旧attempt。
正常cohort与同版本恢复共用完成接收报告及双fresh前缀验证；v14的`cycle`与`receiving_cycle`均可作为完成报告，
不同stage不互相冒充两个轮次；计算pending/blocked独立于接收活性，UNKNOWN及完整性问题仍拒绝。

### 已闭合发布依赖封存与退役

整组切换成功、旧进程退出且已完成现场读回后，使用同一现役版本运行：

```bash
python -m app.runtime_retention closeout-plan /exact/old-release-root ... > /private/retirement-plan.json
python -m app.runtime_retention seal-closed --plan /private/retirement-plan.json
python -m app.runtime_retention cleanup-plan /exact/old-release-root ...
```

closeout-plan固定本次真实退役roots、共同Git库及历史身份、原plan/state/receipt字节和必要.run证据；
seal-closed在部署锁内重采样并原子保存于既有Runtime私有目录release-retirements，不改旧unknown，不复制源码或凭据。
历史Git身份不再要求旧checkout存在，当前active binding/installed/process仍默认严格校验真实根；未闭合或没有有效seal的
历史引用继续阻止清理。封存后的全局指针及binding可以随下一次合法部署变化，旧不可变证据仍须原字节匹配。
历史对象不允许写回active registry。正常新cohort在首effect前保留私有plan，旧attempt仅使用当时原件、不回填。

清理只按最后重新读回一致的精确cleanup-plan逐个non-force移除；必要证据、tag/Release、共享配置、行情和DB不删除。
删除后从唯一现役树核对历史审计、未决恢复检查及下一部署前置条件；自然行情、盘后业务及数据质量仍单独验收。
