# 独立 SimNow 关闭态准备

Owner 交办在 develop 开发并生成独立关闭态配置，无 Broker 预检；基线 `109d09a883`。
旧账户状态保留 UNKNOWN，不继承余额、持仓、订单或发送记录。不发布、不切换、不安装服务、
不读取凭据、不连接柜台、不交易；原 Market/Alert/Reference/API/Web 保持 v1.16.31/gen37。

## 实现与合同

schema 3 沿用 schema 2 字段，仅接受 observe/disabled。独立状态锚点要求0700、无路径别名，
状态根不存在或为空；配置0600、单链接。schema 1/2不变，schema 2缺四库仍拒绝。
schema 3不能启动、检查Keychain、render/install或取得账户运行锁。

`--preflight-preparation`重载配置，以指定SDK解释器执行现有无Broker `--observe-only --check`，
并在返回后复验配置和空状态根。超时、SDK不兼容、配置或账户文件出现均拒绝。
输出`simnow_preparation_preflight_v1`：准备合格与实际账户/运行/执行资格明确分开。
合同见[SimNow执行](../SIMNOW_EXECUTION.md#独立关闭态准备schema-3)。

## 实际准备与读回

主工作区新建 `output/simnow-independent-20261028`，使用独占创建，未覆盖既有目录/文件。
仅从既有关闭候选复用账号指纹、SDK解释器、API依赖路径；不读取Keychain或其他凭据。
配置为 `continuous.disabled.private.json`，schema3/observe/false，代码根为当前develop；
state anchor为新目录，状态根为其`output/simnow-controlled`。anchor/output/state均0700，配置与结果0600。
目录中仅配置和`preflight.json`两个文件，状态根为空；没有账户四库、初始资金或空仓结论。

真实命令：

```sh
services/quant-api/.venv/bin/python -B scripts/ops/macos/simnow-service.py \
  --config /Volumes/扩展盘/guiyi-quant-workstation/output/simnow-independent-20261028/continuous.disabled.private.json \
  --preflight-preparation
```

返回0，真实指定SDK检查通过。结果：`preparation_valid=true`、旧`UNKNOWN`、新`UNINITIALIZED`；
`account_reconciled`、`balance_verified`、`positions_verified`、`runtime_ready`、`execution_permitted`、
`broker_io`、`credentials_loaded`均false。准备结果不冒充账户已核验。

旧候选/SimNow plist/service-bindings/旧monitor及四库存在性与SHA前后相同。
再次只读预检前后，新目录全部文件及全局账户锁/host.lock存在性与SHA不变；未创建四库或运行锁。
六个正式进程仍为原PID42519/42525/42531/42538/42545/42707，均继续使用release-v1.16.31；无重启/切换。

## 验证与交付

- 使用锁定解释器与 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core`。
- TESTING持续trade组合：supervisor/host/execution/credentials/HTDY/monitor及对应API/输入测试，**587 passed**。
- 独立Review：supervisor组138 passed，最终准备态19 passed，无未解决Confirmed Issue。
- 四个修改模块Mypy通过；定向Ruff、`git diff --check`通过；secret scan 0。
- 真实SDK预检及只读重复预检通过，保护文件未变，状态根空。

代码/测试/Review和关闭态准备完成，允许集成develop；本轮直接在develop提交推送。
不创建tag/Release，不修改正式配置、绑定、监控来源或旧失败记录。
后续另做账户只读对账，根据新鲜真实快照初始化账本；启动、结算确认及交易另行推进。
