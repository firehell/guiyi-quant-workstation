# SimNow结算证明与恢复诊断

执行依据：owner已批准的“SimNow账户恢复与自动交易闭环处理方案”。基线为现役v1.16.44
`7b1723e6b5df53091cdb3cd7e1b438b95717208f`，独立任务分支`codex/simnow-recovery-settlement`。
开盘正式十服务/独立SimNow、原账户四库与预算/block均不变。

## 事实与实现

- 本轮既有失败记录证明双轮账户查询及结算/确认请求完整返回，但未保存确认日期；
  不能断言今晚失败就是日期比较。离线复现连续入口在ConfirmDate为周五、TradingDay为周一时拒绝成功确认。
- 共用`SettlementConfirmation`取代连续与有界两套结算判定，人工入口沿用NativePortfolio路径。
  证明绑定当前账户/交易日/连接，查询保守shortcut保留；显式确认的成功回报不以日期相等判定。
  未知结果至多一次，源身份版本化，不更改策略/风险/旧账本或新鲜度门禁。
- Supervisor精确标记恢复阶段，失败只留白名单原因及结算日期/请求摘要，不输出秘密或异常正文。
  最后自审补充“确认失败不得沿用前一查询request ID”的失败回归后修复。

## 验证记录

- 初始4条回归均失败：两条夜盘日期、两条阶段/脱敏诊断；与预期缺陷一致。
- TESTING.md中的六文件合并定向运行：144 passed in 39.76s，零Broker/原账户写入。
- 之后只修改结算诊断清旧字段及对应测试；11 passed in 0.07s，不重复六文件全量。
- 3个生产模块mypy通过，结算诊断补修后单模块复验通过；受影响Python Ruff、秘密扫描0及diff通过。
  初轮独立执行安全Review确认两处P1，均已在同一补丁补修：未知结算结果跨连接重试，以及有界入口
  在缓存已确认后更换登录身份仍可创建Adapter。前者2条回归先失败后通过，传输分类及新反例18项通过；
  后者执行/只读各1条回归先失败，修复后在状态写入/只读成功返回及最终Session前零查询重验身份。
- 补修受影响定向运行36 passed，另外两条漂移用例仅调整为既有precheck抛固定错误的验收方式后2 passed；
  固定SDK无网络结构/协议34项通过。未重跑六文件。未知错误不泄密；结算响应信息presence仅增诊断，
  空RspInfo是否允许表示成功仍为既有协议待验证风险，不据假设改变Gateway生产处理。
- 同一独立审查者已对`6307af54d39c68d061de672e264809da5a56a3ca`增量复核，两P1关闭；
  独立仅跑4项反例通过（0.27s），无剩余Confirmed Issue，允许集成develop及release candidate。
  PR554已实际合入develop `beeeed3f77365027d1498ed554c105668272a2ff`。
- v1.16.45仅增加版本与交付状态，生产实现逐blob等已审候选；版本一致性1项、离线uv lock、
  Core/API sdist+wheel、Web type/build/topology通过。初次无隔离打包因测试venv缺hatchling停止，
  随后使用标准离线隔离缓存成功，未安装到现役venv或修改依赖。Web保留既有大chunk提示，不改无关UI。

## 部署边界

当前交易日20261102已持久化CONTINUOUS_RECOVERY_REQUIRED；保持原block和attempt=1，
不新增同日恢复例外。代码验证后正常集成/发布，只有既有工具证明合法休市窗口及目标日/预算可用时
才切独立SimNow，不切正式十服务。无合法条件停在已验证候选；不反复启动，不新增调度或通知。
自然接管、逐品种输入、策略开平、费用对账、跨日/断线/换月分别待验。

## 实际发布与最终只读读回

PR555合main `b3e1f231eb1d0ecf9f850ce73fdc66de1da4bd3d`，完整Git树等受测1da3f901；
annotated v1.16.45及GitHub Release于2026-10-30 22:06:40 CST正式完成，非draft且目标main。
22:09原run0900f127仍RECOVERY_BLOCKED/pending=true/opening=false，原account/dispatch文件SHA
与执行前相同，20261102 attempt1及原block保持。未停启/重连、结算确认或报撤单。
一次正式切换只读check返回BLOCKED/RESULT_UNKNOWN；当时独立诊断返回WINDOW_UNPROVEN。
该诊断的初始化问题及更正读回见下一节；没有许可、plan或claim，未尝试切换。
状态为RELEASED / CODE_COMPLETE_EXTERNAL_GATE_PENDING：运行仍44，正式十服务仍41；
合法窗口/目标日权威事实及预算、新鲜接管、输入、自然交易和跨日换月仍须分别验收。

## 窗口定位与下一可用目标日（只读）

owner交办先处理剩余第一步：定位窗口拒绝，并核实合法休市窗口、目标交易日和连接预算。
2026-10-30 22:49–22:52 CST，通过既有安全配置加载程序后启动全新解释器，只读权威数据库及
原signals.sqlite；没有修改服务、账户、连接计数或阻断，没有Broker请求、RQData下载、DB写入或新后台任务。

- 独立诊断原先导入应用后才加载配置，连接池缓存旧配置，其OperationalError被权威入口统一包装为
  ORDINARY_TAKEOVER_WINDOW_UNPROVEN。正式宿主已有配置加载后重执行初始化；本次按该顺序诊断后读取正常，
  不把此前错误推断为生产Calendar/Session缺失。正式check在市场开放时仍可能把该固定窗口拒绝显示为RESULT_UNKNOWN；
  本轮只定位，不为诊断显示新增生产补丁。
- 22:52:50实际读取60品种：45 TRADING、15 CLOSED、UNKNOWN为0。夜盘结束分别为当日23:00、
  次日01:00及02:30；全部下一Session为11/2 09:00。因此当前不满足全部休市/无当前Session，切换应阻断。
- 20261102及20261103的权威Calendar/Session均覆盖60/60。前者首Session为10/30 21:00、
  末Session至11/2 15:00；后者首Session为11/2 21:00、末Session至11/3 15:00。不需要为窗口定位补下载。
- 原耐久记录仍为20261102 attempt1及CONTINUOUS_RECOVERY_REQUIRED；跨自然日不消除该交易日阻断。
  20261103尚无attempt或block记录，按现有每交易日最多3次预算当前使用0/3；未预留或授予连接许可。
- 结合下一实际Session必须属于目标日、全60休市及距下一Session严格大于660秒合同，下一候选部署区间为
  **11/2 15:00收盘确认后、严格早于20:49 CST**；对应20261103首Session连接窗口为
  **11/2 20:58–21:02 CST**。上述为现有权威时段推导，必须在执行时重新校验，不能提前当作许可。

第一步调查完成。下一步只在合法条件实时通过后生成原生新鲜计划/claim，将已发布v1.16.45切至独立SimNow；
正式十服务、原账户四库、writer/双锁、预算、耐久阻断及原风险/输入门禁保持。接管、60品种输入和自然交易仍待验。
