# VeighNa P1-B macOS 离线验证

本目录锁定 Apple Silicon 上的 CPython 3.13.3、VeighNa 4.4.0 和 PortfolioStrategy 1.3.0。CTP 使用官方为 Mac 推荐的 6.7.7.2 GitHub 发布源码，锁定提交 `fa199f70dac9e242c20e925c17e2241b877e694f` 及归档 SHA256 `de298bfd8c917d99fb84bf4177909cf98b791d701c056683d239546fc8f9eb6b`。[官方发布](https://github.com/vnpy/vnpy_ctp/releases/tag/6.7.7.2) · [上游问题 #91](https://github.com/vnpy/vnpy_ctp/issues/91)

同版本的 PyPI 源包缺少框架符号链接，签名资源及 `Info.plist` 与 Git 归档存在字节差异。在目标 Mac 上，两份 Git 归档框架均可原样加载，返回 `v6.7.7_MacOS_20240716 15:00:00`。对同版本 PyPI 框架做相同加载时，dyld 返回签名无效。Git 归档中的原始签名与系统安全设置均保留。系统的独立 `codesign --verify --strict` 信任链检查返回 `CSSMERR_TP_NOT_TRUSTED`，本次实际加载由目标 Mac 上的 dyld 验证。

按 [gateway_smoke.py](gateway_smoke.py) 开头的命令，从锁定归档用 Apple Clang／Meson 构建，然后在新的私有目录和系统禁网沙箱中执行 smoke 或 pytest。验收包含两个 ARM64 扩展导入、未连接的 CTP 网关初始化，以及六类事件经具体 Python 回调进入 VeighNa EventEngine 后的顺序、字段和身份。回调输入是固定测试数据。MD 权限与订阅、TD 连接与对账、原生回报传输及 P5 恢复需独立验收。

## P5 共享账户离线宿主

`TradingHost` 消费 P2 completed 输入。`VeighNaOfflineGateway` 复用 headless `MainEngine`、`EventEngine`、持仓转换器、PortfolioStrategy 模板和 CTP 回调。部署、账户仲裁、领取及审计记录由隔离 PostgreSQL 保存。账户、持仓和成交来自读回与回报。fixture 报撤单只记录请求。所有真实连接和真实报撤单入口均关闭，`auto_order=false`。

装配顺序为创建私有目录和网关，启动宿主并绑定账户/交易日/连接代次，对账后用 `activate` 校验范围、为物理合约登记风险参数，再送入 P2 预热和前向事实。`receive_observation` 接收带源代次的 completed journal 原件，`receive_publication` 接收 P2 的日周首次发布证据。调用方提供 Market 已证明的下一端点与时间。调用 `advance` 在超过截止时刻后封闭同端点批次并分派已落盘意图。同一截止时点仍处理已有输入的冲突。回报沿单一 EventEngine 队列进入 PG，可随时处理。期末已发布的 D1/W1 仍可产出观察决策，闭市或过期的动作无报单资格。

启动和回报变化后，须提供同身份、同代次、同水位的资金、持仓、订单及当日成交四段完成证据。读回绑定本次查询身份，决策按各段事实已知时点读取。已知原生委托身份可在重启时进行精确对账。缺关联证据的未知提交不重发、预留不释放。持仓退出只进入 DRAINING，释放名额须有更新的空仓及无未决义务读回。旧约可用有界 `ManagementPermit` 离线演练撤余单和按可平量减仓。共享范围默认使用 P2 的正式 60/16 验证器，70/20 仅隔离容量用例。

只读 API 可将独立的 `build_newow_trading_router` 绑定到 `TradingStore.projection` 或 `read_projection`。独立应用挂载 `GET /api/v1/newow/trading/{status,account,positions,decisions,orders,fills}`，默认服务入口不挂载。记录按固定查询上限翻页，资金和持仓显示最后一次读回与状态。

### 隔离验证

沿用 P1-B 的解释器、CTP 归档和签名。已存在的 P1-B 环境可在独立 venv 复用锁定产物，只补 P5 源码和新增依赖。使用一次性 PostgreSQL 16 的空库 `guiyi_p5_test`，只绑定本机动态非 5432 端口，无正式卷或凭据。以下由仓库根启动，传入本次独立解释器路径和 PG 端口，禁止继承 PG 环境变量。原生测试沙箱仅允许访问该测试 PG。

```sh
p5_root="$PWD"
p5_python="$p5_root/services/newow-vnpy/.venv/bin/python"
p5_port=49607 # 替换为本次隔离 PG 的实际本机端口
p5_run="$(mktemp -d /private/tmp/guiyi-p5.XXXXXXXX)"
mkdir -m 700 "$p5_run/.vntrader"
p5_existing_vntrader="$HOME/.vntrader"
(
    cd "$p5_run" && /usr/bin/env -i PATH=/usr/bin:/bin PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
        GUIYI_VNPY_PROBE_DIR="$p5_run" \
        GUIYI_P5_ISOLATED_DATABASE="host=127.0.0.1 port=$p5_port dbname=guiyi_p5_test user=postgres" \
        PYTHONPATH="$p5_root/services/newow-vnpy:$p5_root/services/quant-api:$p5_root/packages/quant-core" \
        /usr/bin/sandbox-exec -D "P5_PG=localhost:$p5_port" -D "P5_TRADER=$p5_existing_vntrader" \
        -p '(version 1) (allow default) (deny network*) (allow network-outbound (remote ip (param "P5_PG")))
            (deny file-read* file-write* (subpath (param "P5_TRADER")))' \
        "$p5_python" -s -B -m pytest -q -p no:cacheprovider "$p5_root/services/newow-vnpy/tests"
)
```

P6 保留证书信任链、独立行情读取、SimNow 权限与无结算写入的只读通道、原生四段查询完整性及实际提交关联的验收。实际报撤单、自然成交及本机容量以 P6 对应证据为准。

## 模拟交易中心 · SimNow 账户观察

`simulation_observer.py` 以一个独立进程绑定一个明确授权的 SimNow 账户。它复用锁定版原生 TD 登录与查询，
将成功资金、持仓、委托和成交读回写入专用 PostgreSQL schema。它跳过默认结算确认，不连接 MD，报撤单入口拒绝调用。
Web API 通过只读事务查询数据库，连接柜台由宿主负责。

仅在获得相应环境和账户的连接授权后，使用私有账户目录与权限 0600 的 JSON。配置字段为
`alias`、`environment`（`simnow`）、`front`（受限前置）、`user`、`password`、`app_id`、`auth_code`，以及
可选的 `deployment`（策略 ID、公式版本、参数 Profile、风险政策与物理合约）。账户不共用工作目录。
数据库由操作员显式应用 [simulation_schema.sql](simulation_schema.sql)。写进程使用
`GUIYI_SIMULATION_WRITER_DSN`，API 使用 `GUIYI_SIMULATION_READER_DSN`。两者按相应 schema 使用独立角色权限。

从仓库根执行，环境变量由本机秘密管理注入，目录路径使用实际绝对路径：

```sh
PYTHONPATH="$PWD/services/quant-api" services/newow-vnpy/.venv/bin/python \
    services/newow-vnpy/simulation_observer.py --observe \
    --account-config /absolute/private/account.json --workdir /absolute/private/account-runtime
```

[验收与后续阶段](../../openspec/changes/add-simulation-center/tasks.md)。
