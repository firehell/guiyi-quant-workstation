# 第一步：当前运行阻断核查（2026-10-24）

Owner仅交办Reference ready=false、采集状态、消费积压和维护锁核查/排障。本轮未推进AL/RB维护、历史资产构建、盘后补齐或通知。

## 结论

当前没有发现进程/维护锁/消费者积压阻断。十服务exact v1.15.18/gen23，六PID保持不变；Reference在scan与cycle间正常循环。40秒40次采样中3次ready=true，blocked_count全部0，刷新与通知后台存活。单次scan ready=false不代表服务故障。Feed原生poll同样先mark_not_ready再mark_ready，单帧不能替代业务检查。

两轮独立Runtime/Reference health、Redis journal/heartbeat、PG锁读回，所有保留日志consumer均在tail，数量/游标未变，pending Capture0；PG维护锁0、文件维护锁空闲。Feed available=true、input_failure=null、pending0，Live/Alert heartbeat新鲜。闭市60品种、订阅0符合当前Session，不要求产生新行情。

## 保留的业务异常

- Live 34 ok、15 not_due、11 lagging；11品种仍为既有611原件缺口，不能由消费追尾推断原始数据完整。
- Reference 672 READY、48 OBSERVATION_LAGGING；11品种44路源缺口，另L4持久health为旧OBSERVATION_LAGGING，computed/observed已追平当前endpoint。正式v18 forward_source_context和source transaction guards不以该health标签拒收下一正常输入，不能为了显示绿色手改health。
- 全局degraded保留：旧盘后UPDATE_FAILED、旧通知transport失败及评估覆盖、weekly skipped_busy。它们不证明当前进程卡住，也未在本轮修复。
- 当前无交易时段，不能证明下一自然分钟/H1/Event/Push成功。不生成测试生产Bar、不改cursor、不重放/补发，不新建监控任务。

## 证据与验证

`output/runtime-step1-20261024/{initial,final,reference-owner-samples,l-streams,summary}.json`；十服务独立身份：`output/data-three-repair-20261023/final-runtime-readback/identity-step1-final.json`。

在exact发布树执行：

```sh
PYTHONDONTWRITEBYTECODE=1 GUIYI_LOG_DIR=/private/tmp/guiyi-step1-test-logs \
PYTHONPATH=services/quant-api:packages/quant-core \
services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
 services/quant-api/tests/reference_trading/test_forward_runtime.py \
 services/quant-api/tests/reference_trading/test_worker_entry.py \
 services/quant-api/tests/data_foundation/test_observation_stream.py \
 services/quant-api/tests/test_runtime_entry.py
```

45 passed、23 skipped（依赖独立环境的既有项）。首跑两项因默认日志目录不存在失败，创建0700独占临时目录后重跑通过；未修改产品代码。身份验证器首跑因输出路径不在其固定目录拒绝，改为合规新输出路径后通过；无生产副作用。`git diff --check`通过。

本轮只读证据采集，生产写入/下载/通知/重启均0。下一最小运行验收条件为下一权威Session自然分钟采集→消费者→H1正常推进；旧缺口和历史修复仍按其他步骤处理。
