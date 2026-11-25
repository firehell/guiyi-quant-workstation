# RQAlpha P1 离线撮合试验

使用 Apple Silicon 上的 CPython 3.13.3 和 RQAlpha 6.3.0。环境与应用 API 分开，锁文件仅引用公开 PyPI。运行器仅接受一个冻结 SHFE 物理合约及明确给定的日盘 Session、完整 1m、每日费率、结算和涨跌停。该入口用于 P1 可行性验证，P3 的行情服务、发布及账户精度合同仍待验证。

从仓库根目录创建环境。随后在临时目录和 macOS 禁网沙盒中运行定向测试及冻结真实样本。

```sh
repo_dir="$PWD"
service_dir="$repo_dir/services/newow-rqalpha"
evidence_root="$repo_dir/output/guiyi-v2-p1a-rqalpha"
fu_sample_dir='/Volumes/扩展盘/guiyi-quant-workstation/output/newow-fu15-validation-20261107'
rqalpha_legacy_dir="${HOME}/.rqalpha"
proof_sandbox='(version 1) (allow default) (deny network*)
  (deny file-read* (subpath (param "GUIYI_LEGACY_RQALPHA")))
  (deny file-write* (subpath (param "GUIYI_P0_SAMPLE")))'
uv sync --locked --project "$service_dir" --cache-dir /private/tmp/guiyi-v2-p1a-uv-cache \
  --default-index https://pypi.org/simple \
  --python /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
mkdir -p "$evidence_root"
evidence_dir=$(mktemp -d "$evidence_root/verification.XXXXXX")
scratch_dir=$(mktemp -d /private/tmp/guiyi-p1a-offline.XXXXXX)
cd "$scratch_dir"
printf '%s\n' "$evidence_dir"
/usr/bin/sandbox-exec -D GUIYI_LEGACY_RQALPHA="$rqalpha_legacy_dir" \
  -D GUIYI_P0_SAMPLE="$fu_sample_dir" -p "$proof_sandbox" \
  /usr/bin/env -i "$service_dir/.venv/bin/python" -B \
  -m pytest -v -p no:cacheprovider "$service_dir/tests"
/usr/bin/sandbox-exec -D GUIYI_LEGACY_RQALPHA="$rqalpha_legacy_dir" \
  -D GUIYI_P0_SAMPLE="$fu_sample_dir" -p "$proof_sandbox" \
  /usr/bin/env -i PYTHONPATH="$repo_dir/services/quant-api:$repo_dir/packages/quant-core" \
  "$service_dir/.venv/bin/python" -B "$service_dir/fu_sample.py" \
  "$fu_sample_dir" "$evidence_dir/fu2603-first-pair.json"
```

- 5m 收线 `09:05:00` 在历史模型中于 `09:05:02` 可用。最早候选为 `09:06:00` 分钟开盘，原生 `NEXT_BAR_OPEN` 在 `09:06:00` 标签回调创建委托，在 `09:07:00` 标签回调撮合。委托冻结价取决策时已知的 `09:05:00` 收价。证据保存信号、建模成交时点、原生委托及成交回调时点。首候选无资格即结束，缺失的原始分钟或参数阻断运行。
- 每次提交一手，使用 RQAlpha 原生委托、撮合、费率、持仓和结算，滑点为零。证据保留原生平今字段，开仓的业务平今手数记录为零。带仓到期末保留持仓与结算估值。显式换月边界有仓时标记 `ROLLOVER_INTERRUPTED`，新段的 `HOLD` 没有开仓委托。
- FU2603 只以 09:35 前 35 根 1m 重算 7 根 5m 策略输入。日盘 225 根 1m 供引擎执行及估值。样本以 SHA-256 核验，只从既有冻结原件读取。委托按核验的物理合约运行，许可日期范围来自归档的主力归属窗口。
- FU2603 手算为一手买入 2485、卖出 2480、开仓费 1.2425、平今费 0、最终权益 9948.7575。记录原生浮点及其精确二进制值。原生开仓费的最短十进制表示为 `1.2425000000000002`，严格对比写出证据后返回 1。P1 未批准舍入规则。

## P3 FU2603 真实数据试验

P3 用同一 RQAlpha 6.3.0 环境计算 `FU2603 × trend × 5m × 2026-01-05`。
手工入口读取有界的只读 MDS，冻结同合约完整 5m 前缀和当日 1m，并由 P2 与原生已确认持仓共同决定委托。
默认口径为初始资金 10,000 元、一手多头、零滑点、历史信号可用延迟 2 秒、同 Session 首候选有效。
费用及权益按 CNY 8 位半偶舍入对账，原生浮点文本及十六进制随结果保留。

先按 [TESTING](../../TESTING.md#guiyi-v2-p3-隔离历史回测) 准备专用本地 PostgreSQL。
显式设置 `GUIYI_NEWOW_BACKTEST_WRITE_DSN` 指向隔离写入者，`GUIYI_NEWOW_BACKTEST_READ_DSN`
指向隔离只读角色。以下从任务 checkout 根目录运行；`facts_dir` 指向既有 FU 归档，
`input_dir` 是 Canonical 之外的既有私有目录。

```sh
PYTHONPATH=services/quant-api:packages/quant-core \
  services/quant-api/.venv/bin/python -B -m app.services.newow_backtest_job \
  --facts-dir "$facts_dir" --input-dir "$input_dir" --trial
```

`--trial` 写入 `trend_5m_rqalpha_trial_v1`。默认正式系列 `trend_5m_rqalpha_v1`
要求此前交易日完整物理合约证据、当时有效的 Catalog 排名和独立的 RQData rule=2 证据。
首日正式样本返回 `RANK1_AS_KNOWN_UNPROVEN`。隔离 API 可查询正式尝试状态和独立试验结果。
只有显式手工运行入口启动回测；查询、刷新、翻页直接读取已发布 run。

`GET /api/v1/newow/backtests/latest` 按 `product=fu`、`strategy=trend`、`frequency=5m`、
`research_profile_id` 查询。P4 将返回的 `run_id` 固定用于后续 `/{run_id}/trades` 和
`/{run_id}/equity` 请求。权益点为初始及逐日结算，逐笔中的 `modeled_fill_at` 和
`native_fill_event_at` 使用上海时间并各自保留。

## P4 隔离工作台与盘后回测

使用 P3 结果库，并仅在隔离库应用 `20261124_0056`。原 run、逐笔、权益及成功版本读接口保持原合同。API 进程只需 `GUIYI_NEWOW_BACKTEST_READ_DSN`。在 develop Web 启动时设置 `VITE_NEWOW_BACKTEST_PREVIEW=1`，由牛哇主图的「回测记录」进入，旧「参考记录」仍可独立打开。

盘后参考隔离模式须显式设置 `GUIYI_NEWOW_REFERENCE_MODE=after_market_isolated`。
隔离盘后入口另设 `GUIYI_NEWOW_EOD_ISOLATED_CONFIG`，且实际 Catalog DSN 和 Canonical 根目录必须与隔离配置一致。生产者、API、盘后维护使用同一个显式的测试 Redis，地址须为 127.0.0.1 的非 6379 端口。状态及锁分开放在 `.run/newow-isolated`。Web 以 `VITE_NEWOW_EOD_ISOLATED=1` 构建，API 仅接显式给定的隔离只读连接。维持 `auto_order=false`。已成功落盘的 Canonical 凭证先保存在该隔离状态目录的 `newow-publications`，维护锁释放后正常入口自动消费；下列命令可启动独立的补领进程。

```sh
PYTHONPATH=services/quant-api:packages/quant-core   services/quant-api/.venv/bin/python -B -m app.services.newow_backtest_eod   --status "$isolated_status_file" --config "$isolated_config" --watch
```

配置为 JSON 数组。每项必填 `product`、`since`、`facts` 和 `facts_sha256`。执行事实使用 P3 已有的 instrument、daily、parameters 结构，显式给出目标物理合约在回测窗口内的逐日事实。换月后须登记新物理合约的事实文件及摘要；缺失时系列保留旧结果。可选 `trial: true` 开设试验系列，可选 `rule2` 和 `rule2_sha256` 记录独立凭证，文件路径用绝对路径。研究消费者读取名为 `guiyi_newow_market_test` 的隔离本地 PostgreSQL（非 5432 端口），连接变量为 `GUIYI_NEWOW_EOD_MARKET_DSN`。另设 `GUIYI_NEWOW_EOD_CANONICAL_ROOT`、`GUIYI_NEWOW_EOD_INPUT_DIR`、`GUIYI_NEWOW_BACKTEST_WRITE_DSN`。可用 `GUIYI_NEWOW_EOD_ENGINE` 指向离线引擎解释器。

重复凭证、同一输入、旧日期或已被替代的同日凭证会复用已有结果或跳过。写事务失败保留最后成功 run。明确失败后可用 `--receipt <sha256> --retry-series fu trend 5m` 重试正式组合；试验系列另加 `--retry-trial`。有新的未结维护或失败状态时等待 Canonical 再次确认。提交结果未知由 P3 独立读回处理。相同研究输入全量重算仍使用同一逻辑 run。接口翻页固定 run 并独立读取成交和权益。

P4 沿用同 Session、严格后继分钟开盘的一手执行模型。日线和完整周线发布参考动作与输入切片，当前跨 Session 订单政策缺失，逐笔成交与权益为空。主力切换后新段重新预热与核验，旧段标明换月中断并按原 run 保留。当前 Catalog 横截面和回顾性 rule=2 匹配无法证明开盘时就可用的原始事实，因此正式资格仍留在 `RANK1_AS_KNOWN_UNPROVEN`。季节、手续费和历史数据修订按各 run 保存的输入及版本复核。
