# 运维拓扑与只读检查

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
# Mac：API/Web/Live/after-market/Alert 五个 label（按 activation marker 判定 required）、同一 Runtime 根、
# 已加载进程 commit 身份与本地 HTTP/Runtime health
./scripts/ops/macos/local-services-status.sh

# Mac：本地端口与 FRPC
./scripts/ops/network/local-tunnel-healthcheck.sh

# 腾讯云：FRPS 端口与隧道 upstream
./scripts/ops/network/tunnel-healthcheck.sh

# 公网：HTTPS、Basic Auth、Web/API/WebSocket 与关闭端口
PUBLIC_BASE_URL=https://<your_domain> ./scripts/ops/network/public-healthcheck.sh
```

未认证公网检查预期 HTTP 401；提供 Basic Auth 后，页面/API 预期 200，
`/api/v1/market/ws` WebSocket Upgrade 预期 101。

## 配置与变更 Gate

- [`deploy/launchd/`](launchd/)：Mac API/Web/Live/after-market/Alert、默认未安装的 weekly audit 与日志轮转模板；验证命令见
  `TESTING.md`。
- API 与 Alert 模板只共享一个 Git 外 `GUIYI_ALERT_NOTIFICATION_CONFIG_PATH`；PushPlus token 与 Topic code
  不进入 plist、仓库或状态输出。
- [`deploy/frp/`](frp/)：FRPC/FRPS 隧道配置与分段验收。
- [`deploy/nginx/`](nginx/)：腾讯云 HTTPS/Basic Auth 反代模板。

安装器会把渲染时 checkout SHA 写入每个 plist 的 `GUIYI_RUNTIME_COMMIT`；只读状态脚本同时核对已加载
`GUIYI_PROJECT_ROOT`、该 commit 与当前 supervised checkout，避免把移动后的工作树 HEAD 当成已运行版本。

`--render-only` 可用于本地无副作用验证。任何 launchd 加载/重载、Runtime switch、腾讯云配置应用或
Nginx reload 都是独立受控外部操作，必须在执行前取得与目标相符的一次性明确意图。

### Weekly operational full-history audit

`com.guiyi.quant-weekly-audit.plist.template` 固定每周六 09:00（launchd `Weekday=6`）运行一次
`operational_full_history` 只读审计，不含 `RunAtLoad/KeepAlive`，也没有 retry、provider/data write 或通知能力。
`--render-only` 会渲染该模板，但不安装或启用它。

每周 label 只能在获得该次安装的明确外部操作意图后，从目标 exact Runtime checkout 执行：

```bash
./scripts/ops/macos/install-local-services.sh --confirm-weekly-audit
```

安装器在任何外部 mutation 前要求已安装 API plist 是非 symlink 普通文件，其
`GUIYI_PROJECT_ROOT` 与当前 checkout 完全相同，`GUIYI_RUNTIME_COMMIT` 与当前 40 位 Git SHA 完全相同。
此模式只替换/加载 `com.guiyi.quant-weekly-audit`：不 bootout/kickstart 其他 label，不写 Market/Alert marker，
不替换共享 launcher/log rotator。weekly plist 直接指向该 exact checkout 中的
`scripts/ops/macos/run-local-service.sh weekly-audit`，避免使用其他 checkout 的启动器。

`local-services-status.sh` 只从既有 Runtime health 打印有界的盘后 stage/attempt/symbol/成功操作数，
及独立 weekly status/through/findings。weekly label 不是现有 operational health 的 required service；安装成功也不证明
首次自然审计已通过、release 或 Runtime promotion。

### Market Runtime promotion preflight

#### Interrupted-run closeout before promotion

先使用已审查的新 CLI 对现役 root/commit 和原状态字节 SHA-256 执行一次只读核验：

```bash
guiyi data close-interrupted-after-market --runtime-root /absolute/current-runtime \
  --runtime-commit EXACT_40_HEX_COMMIT --expected-status-sha256 EXACT_64_HEX_SHA256
```

只有获得针对相同身份的一次实际收尾执行意图后才追加 `--apply`。该操作只将原运行记录为 interrupted，
不证明更新完成，不修复行情、不安装调度。blocked/结果不确定立即停止，不删 JSON、不重跑；明确写入不确定时
须重新只读核实。旧 Runtime reader 不认识 schema v4/v5 会降级；新候选 reader 可以读取，但 promotion 的
phase/Live snapshot Gate 完全保留。安全收尾、发布、五服务同步和周审计安装仍是各自受控操作。
现役 v1.10.5 writer 下次自然运行会写回 schema v2，不能承接 v5 中断摘要；reader 降级不阻止覆盖。
收尾 apply 前须核对下一次旧任务窗口，明确届时使用已批准的新 writer，或另行取得暂停旧盘后调度的
执行意图；保留收尾读回证据。不得据此自动暂停调度或切换 Runtime。
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
commit 和 immutable recovery root，并取得一次匹配的恢复执行意图。

安装部分失败后的恢复不是安装器自动 rollback。只有针对已发布 compatible root、明确服务集合和该次失败现场
单独批准的一次尝试，才可使用该 root 中已正式 Review 的安装器；仍须运行同一 promotion preflight。
activation marker 恢复不能证明已加载服务、plist 或 status 已事务回滚；任何失败尝试仍有 label loaded 或现场
结果不明时保持 blocked，不自动重试，也不切换到 v1.10.5/v1.10.6。

#### Read-only promotion predicate

`install-local-services.sh --confirm-market-runtime` 只会执行一次
`run-local-service.sh market-runtime-preflight`。该 preflight 是只读检查，发生在外部 activation marker 准备、
runtime script 写入、已安装 LaunchAgent plist 替换以及任何 `launchctl` mutation 之前；仓库内 plist render
不属于这些外部 activation mutation。若 preflight 阻断，安装器非零退出，且不触碰 marker、runtime directory、
installed plist，也不执行 `launchctl` mutation；为解析 supervised authority 而进行的只读 `launchctl print`
可能已发生。

preflight 只读取 operational universe、权威 Calendar/Session phase、既有 immutable Live subscription snapshot 与
公开 after-market status。允许的通过原因只有：完整且 identity 有效 snapshot 的 `snapshot_ready`；所有品种真正
最早权威 Session start 前的 `before_first_session`；同日 after-market 已 passed、且 products 与 operational
顺序完全一致的 `after_market_complete`；以及无 current trading day、无 active Session 的
`non_trading_interval`。它不会把“下一段 session 尚未开始”误作 `before_first_session`。

跨 checkout 时，preflight 从当前 supervised、已加载 after-market launchd root 读取 status，并与 installed
plist 声明的 root 交叉校验，不能把 candidate checkout 当作 status authority。仅 first-install 可使用 candidate
root，且必须同时满足 launchd domain 可读、after-market label 明确 not-found、没有 installed plist。任何
domain/permission/label 命令错误，或 root 缺失、畸形、不一致，均以
`MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE` 阻断；runtime env 不能覆盖这个受控 status path。

已开始后的缺失 snapshot、无效/部分 snapshot、未知或分歧的 phase/session authority，以及 running、corrupt、
unreadable 或 chronology 不可能的 after-market state 一律阻断；公开 block reason 仅为
`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED`、`MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_INVALID`、
`MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE`。没有 override、repair、synthetic snapshot、retry、replay 或
fallback；通过预检本身不构成 Runtime promotion、release、Runtime ready 或 production verification。
