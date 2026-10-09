# 苏冰六周期静默记录与 EMA21 同向研究

目标：operational 品种在5m/15m/30m/60m/1d/1w按原MACD CROSS+EMA21公式产生独立原始Event，保持通知关闭。触发时额外原子保存六周期同向研究快照，供比较全部信号与PASS信号。1m不加入。

合同：保留稳定Rule身份；各周期拥有公式身份。研究policy subing_ema21_alignment_v1只检查close与EMA21，不参与原信号Gate。每周期使用同一物理合约固定EMA初始化的已完成输入；target bar_end<=signal bar_end，snapshot只表达首次检测时可见事实。buy要求六周期LONG，sell要求六周期SHORT，等于均线为FLAT且FAIL；任何无法证明输入为UNKNOWN且总结果UNKNOWN。记录原始Event关联、首次observed_at、as_of、各周期时间/合约/close/ema21/direction/reason。研究快照不可重算覆盖，历史Event没有快照时返回null。

实现顺序：
- [x] 扩六周期Registry/Evaluator与各频独立cursor，保留数学内核；日周复用canonical_updated。
- [x] MarketReadService加入同合约跨频as-of读取，日周Canonical前缀与完整coverage。
- [x] 新研究快照表/Alembic，原Event及研究结果一个事务；API提供结构与PASS/FAIL/UNKNOWN读取筛选。
- [x] Web开放六周期事件及同向筛选/详情，现有四周期reference范围保持，新增5m/W1不伪造reference。
- [x] 定向/模块回归、迁移离线检查、Web typecheck/build、OpenSpec、diff/secret、独立Review。
- [x] develop集成与交付记录；生产迁移/Scope/Release/Runtime按实际交付范围单独记实，不以代码冒充生效。

关键验收：跨频相同cutoff不相互跳过；相等/缺尾/中间缺口/换月/未完成日周/未来输入；重复与重启不改研究快照；原Event在FAIL/UNKNOWN仍存在；六周期零通知；旧记录null；筛选不截断分页；触发原始价格与EMA版本可审计。

本记录为实施与验证入口，真实命令结果和现场状态在完成时补充。未授权扩大数据历史范围、补发通知、交易或自动晋升研究候选。

## 当前实现与证据

六周期Registry、各频独立Evaluator状态、同物理合约as-of EMA21快照、Event与研究结果原子提交、history分页前筛选及Web入口/筛选/详情均已实现。Live先写齐同端点到期派生周期再发布消息；日周通过真实Calendar/Session/Canonical/MDS测试证明不读未来尾部。保留四周期历史reference能力，5m/1w不伪造reference。

- Web：npm test 795项，794通过、1跳过；npm run build/typecheck/topology通过。
- 浏览器：PLAYWRIGHT_PORT=5198 npx playwright test -c playwright.config.mjs e2e/subing-multiperiod.spec.mjs，1通过，实际Chrome＋明确fixture，只证明交互不证明自然信号效果。
- 后端：定向357通过；扩大alert/subing回归发现两条既有CLI断言在原develop同样失败，均断言CLI没有reference，而基线已经存在reference；未修改无关CLI实现。对应tests/test_alert_cli.py::test_parser_exposes_only_active_runtime_domains_and_commands及tests/test_subing_retirement.py::test_cli_has_no_research_domain。
- Ruff、git diff --check、OpenSpec 10规范通过；后端与Web独立Review通过。
- 0049迁移源码预检单元测试通过；真实PostgreSQL隔离测试因宿主自动审批连续两次超时未执行，不能声明迁移通过。本任务临时测试容器已删除，生产DB未变更。

仍待真实PostgreSQL迁移验证、正式发布/迁移/Scope读回与Runtime切换。当前生产仍是原版本与既有15m Scope，不以候选代码冒充上线。自然信号的PASS比例及后续表现尚未积累；不能据此判断筛选改善收益。六周期完整物理历史重放的生产耗时尚待观察；缺少W1预热或其他输入时明确UNKNOWN，不弱化事实校验。

最终后端命令：PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core /Volumes/扩展盘/guiyi-quant-workstation/services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short services/quant-api/tests/test_alert*.py services/quant-api/tests/test_subing*.py services/quant-api/tests/alembic/test_subing_multiperiod_migration.py services/quant-api/tests/test_market_read_service.py services/quant-api/tests/data_foundation/test_live_market.py -k 'not test_parser_exposes_only_active_runtime_domains_and_commands and not test_cli_has_no_research_domain'。
结果544 passed、3 skipped（隔离PostgreSQL）、2 deselected（已在原develop复现的CLI基线失败）。新增分页测试证明PASS筛选在分页前执行且更改status不能复用旧cursor；非法Decimal返回typed验证失败。原始Event与快照的成功、重复不覆盖及插入失败回滚均通过。

## 续接完成状态

owner明确允许推送、develop集成和隔离迁移验证后，候选288236dca已推送至origin/codex/subing-multiperiod并快进集成、推送origin/develop。工作区保留既有用户outputs，无关修改未触碰。

真实PostgreSQL迁移测试现已通过：临时独立容器127.0.0.1:55439，数据库guiyi_subing_isolated_migration_test，原隔离名称/OID guard保持启用；测试5 passed，涵盖启用Scope扩六周期、disabled/empty保持不变、畸形Scope预检拒绝、HTDY及既有Event保留、研究表写入与禁止破坏性downgrade。初始独立库OID与生产库碰巧相同，被guard拦住且迁移未运行，随后仅在临时容器另建测试库解决，未修改安全检查。

代码、模块测试、Web构建/浏览器、独立Review、真实隔离PostgreSQL迁移验证及develop集成已完成。生产数据库迁移、正式发布、Scope读回、Runtime切换和自然信号验收尚未执行；新功能尚未在生产生效。下一步为正式发布与运行验收。
