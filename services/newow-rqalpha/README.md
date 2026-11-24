# RQAlpha P1 离线撮合试验

使用 Apple Silicon 上的 CPython 3.13.3 和 RQAlpha 6.3.0。环境与应用 API 分开，锁文件仅引用公开 PyPI。运行器仅接受一个冻结 SHFE 物理合约及明确给定的日盘 Session、完整 1m、每日费率、结算和涨跌停。该入口用于 P1 可行性验证，P3 的行情服务、发布及账户精度合同仍待验证。

从仓库根目录创建环境。随后在临时目录和 macOS 禁网沙盒中运行定向测试及冻结真实样本。

```sh
repo_dir="$PWD"
service_dir="$repo_dir/services/newow-rqalpha"
evidence_dir="$repo_dir/output/guiyi-v2-p1a-rqalpha"
uv sync --locked --project "$service_dir" --cache-dir /private/tmp/guiyi-v2-p1a-uv-cache \
  --default-index https://pypi.org/simple \
  --python /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
mkdir -p "$evidence_dir"
scratch_dir=$(mktemp -d /private/tmp/guiyi-p1a-offline.XXXXXX)
cd "$scratch_dir"
/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' \
  /usr/bin/env -i HOME="$scratch_dir" TMPDIR="$scratch_dir" PATH=/usr/bin:/bin \
  PYTHONDONTWRITEBYTECODE=1 "$service_dir/.venv/bin/python" \
  -m pytest -v -o cache_dir="$scratch_dir/pytest-cache" "$service_dir/tests"
/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' \
  /usr/bin/env -i HOME="$scratch_dir" TMPDIR="$scratch_dir" PATH=/usr/bin:/bin \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$repo_dir/services/quant-api:$repo_dir/packages/quant-core" \
  "$service_dir/.venv/bin/python" "$service_dir/fu_sample.py" \
  '/Volumes/扩展盘/guiyi-quant-workstation/output/newow-fu15-validation-20261107' \
  "$evidence_dir/fu2603-first-pair.json"
```

- 5m 收线 `09:05:00` 在历史模型中于 `09:05:02` 可用。最早候选为 `09:06:00` 分钟开盘，原生 `NEXT_BAR_OPEN` 在 `09:06:00` 标签回调创建委托，在 `09:07:00` 标签回调撮合。委托冻结价取决策时已知的 `09:05:00` 收价。证据保存信号、建模成交时点、原生委托及成交回调时点。首候选无资格即结束，缺失的原始分钟或参数阻断运行。
- 每次提交一手，使用 RQAlpha 原生委托、撮合、费率、持仓和结算，滑点为零。证据保留原生平今字段，开仓的业务平今手数记录为零。带仓到期末保留持仓与结算估值。显式换月边界有仓时标记 `ROLLOVER_INTERRUPTED`，新段的 `HOLD` 没有开仓委托。
- FU2603 只以 09:35 前 35 根 1m 重算 7 根 5m 策略输入。日盘 225 根 1m 供引擎执行及估值。样本以 SHA-256 核验，只从既有冻结原件读取。委托按核验的物理合约运行，许可日期范围来自归档的主力归属窗口。
- FU2603 手算为一手买入 2485、卖出 2480、开仓费 1.2425、平今费 0、最终权益 9948.7575。记录原生浮点及其精确二进制值。原生开仓费的最短十进制表示为 `1.2425000000000002`，严格对比写出证据后返回 1。P1 未批准舍入规则。
