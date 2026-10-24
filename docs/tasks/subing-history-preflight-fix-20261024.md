# 苏冰历史续算、追加入口前置校验修复

范围：只修复任务内 AL15m known INTERRUPTED 续算和 RB 四周期追加入口；不改变公式、来源、Scope、Runtime 或通知策略，不在本步骤启动全量历史补建。

## 根因与修复

两个任务脚本在 private bootstrap 前导入 `app.guiyi_cli.reference_commands`，其传递依赖已加载 `app.db.session`，连接池按开发 fallback 初始化。独立进程核对 `db_session_imported_before_bootstrap=true`、`engine_matches_bootstrapped_configuration=false`（只输出布尔，不读取凭据到报告）。两次只读诊断均在 Catalog 维护 lease 建连处发生 OperationalError，未抵达原生 mutation。

将私有配置加载提前到首次应用导入之前；默认离线 plan-only 仍不读私有配置。新增 `--check-only` 在完整来源/检查点校验后退出，禁止进入原生 resume/advance；记录安全错误类型和仓库代码位置，不输出异常详情、SQL 或连接配置。旧失败目录只含 PREFLIGHT/result，均无 intent/report，保持不变；修复版使用 v2 独占目录，仍禁止未知提交或同一效果目录重跑。

这两个入口为任务内维护工具，位于 `output/data-three-repair-20261023/`，不是正式 Runtime 源码修改。正式 release/tag 保持 v1.15.18/gen23。

## 实际验证

修复前初始化顺序回归测试：2 failed、2 passed；修复后包含 check-only、默认离线、来源/检查点漂移、未知结果拒绝、重复 intent 拒绝、旧经济事实及有效期边界：

```sh
.worktrees/release-v1.15.18/services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider output/data-three-repair-20261023/test_v18_subing_bootstrap_offline.py output/data-three-repair-20261023/test_v18_subing_resume_offline.py output/data-three-repair-20261023/test_v18_subing_rb_advance_offline.py
```

结果：18 passed。独立 Review 无 Confirmed Issue；16 项初始组合由 reviewer 独立复跑通过，后补2项 check-only 初始化测试通过。

真实只读检查均 PREFLIGHT_PASSED、production_writes=0：

- AL15m：原 candidate d50102e9cf35419e92c2b0004c2d8e9d，225792/320074 输入，完整 source token、manifest、最后 batch receipt、checkpoint 和原生 resume position 一致。原计划/预算不改。
- RB15m/30m/60m/1d：原 processed 58020/30287/17692/2554，当前 input 58395/30483/17807/2571，四路 exact append 与旧事实摘要均通过。
- 两个 v2-check 目录无 intent、native report，未调用续算、追加、下载、通知或 Runtime 切换。

汇总：`output/subing-preflight-fix-20261024/verified.json`。原始完整读回分别见 `subing-native-resume-v2-fdadb5574d2207fb1fd033777ed08a88a9cc95af34bbf03733e13825cadab0a9-check/result.json`、`subing-rb-advance-v2-7247423f3dddc5761b18d4681f6c9a52a54f54f44561cc8382dde725875b717e-check/result.json`（均在上述 data-three-repair 目录）。

## 结论与剩余工作

前置校验失败已修复，允许继续精确历史续算/追加；不代表历史计算完成。本步未执行 apply。下一步执行前仍须现场确认旧 writer 已退出、没有同路维护者，并重新校验来源、锁与检查点；CLI 的 writer-exited 参数不能替代事实证明。未知提交停止且只读核对，已知预算中断保留原生 resume token，禁止自动循环重试。无需为本任务重复申请 owner 授权。
