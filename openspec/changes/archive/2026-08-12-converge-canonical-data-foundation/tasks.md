## DFD-01：Canonical 合同重置

- [x] 1.1 将 active OpenSpec、项目事实源、长期决策、架构、数据合同和测试入口重置为八表、单月
  `part.parquet`、三个 CLI、Direct/Derived 与 1G/day natural resume。
- [x] 1.2 明确当前代码仍待收口，未把 DFD-02～DFD-06 或真实外部操作记作完成。
- [x] 1.3 严格验证 OpenSpec、引用一致性与独立 Review。

## DFD-02：删除退出维护面、legacy 与生成工件

- [x] 2.1 完成 scoped implementation plan；删除退出的维护面、legacy importer 和已生成工件，并关闭
  代码、测试、CLI、文档引用。
- [x] 2.2 运行受影响定向测试和旧入口/死引用扫描。

## DFD-03：Slim Storage、Catalog、Models 与 0036

- [x] 3.1 先只读确认所有正式环境仍处于 `20260808_0035`；若任一正式环境已应用 `0036`，停止
  rewrite 并改为后续 migration 计划。
- [x] 3.2 以 TDD 收口月度 storage、八表 ORM/Catalog 与最终不可逆 `0036`，删除退出模型和字段。
- [x] 3.3 运行 unit、offline SQL 和隔离 PostgreSQL migration 验证；不应用生产 migration。

## DFD-04：MarketDataService、API 与 Web 查询瘦身

- [x] 4.1 先完成 scoped implementation plan；删除退出的查询校验/响应字段，保持三种 SeriesQuery、
  pre-aggregated Derived 和 fail-closed。
- [x] 4.2 以 API、frontend unit/type/build 和 Market smoke 验证。

## DFD-05：Update、Refresh 与 Quota Resume

- [x] 5.1 先完成 scoped implementation plan；实现三个 CLI、月度自然续传、quota 中止和 refresh。
- [x] 5.2 用 fixture/temporary root/isolated DB 证明 dry-run、same-T NOOP、partial quota、下次续传和
  Direct→Derived 顺序；不调用真实 RQData。

## DFD-06：全量验证与死引用收口

- [x] 6.1 删除剩余 active 死引用和过期测试/文档，保留仅必要的 Git/Alembic/OpenSpec 历史。
- [x] 6.2 运行后端、迁移、CLI、API、前端、OpenSpec、lint/type/build 和 diff/reference 全量验证。

## DFD-07：真实数据清理与 RQData 重建（受控外部操作）

- [x] 7.1 在执行前输出精确生产 revision、表/文件目标、影响、恢复方式和 dry-run；分别取得生产
  migration、正式数据清理、真实 RQData rebuild 的一次性执行意图。
- [x] 7.2 在获授权范围内执行并记录实际结果；完成只读验收后才更新状态和归档 change。
