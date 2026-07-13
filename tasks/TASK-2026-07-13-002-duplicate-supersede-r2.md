# TASK-2026-07-13-002：Manifest 重复 Active 清理（R2）

> **任务 ID**: R2-001 / R2-002  
> **风险**: R2（DB 写入 + 可能 DDL）  
> **前置**: DATA-FINAL-002 代码已合并  
> **状态**: CANDIDATE — 等待 DATA-FINAL-002 合并后激活

---

## 1. 背景

DATA-FINAL-001 诊断确认 247 组 `(symbol, contract, period=1d)` 各有 ≥2 个 Parquet 文件同时以 `data_role='primary'` 注册。DATA-FINAL-002 已在代码层增加跨文件冲突检测，但底层数据仍存在重复 active 记录。

---

## 2. R2-001：使用 duplicate_active_supersede.py 清理 247 组

- **风险**: R2（DB UPDATE 写入）
- **操作**:
  1. `python duplicate_active_supersede.py --dry-run` → 输出将标记为 superseded 的文件列表
  2. 人工抽查 5-10 组（重点检查 OHLCV 一致性）
  3. `python duplicate_active_supersede.py --confirm` → 执行标记
  4. 验证：`_find_files()` 每组只返回 1 个文件
- **回滚**: `UPDATE market_data_files SET data_role = 'primary' WHERE ...`（需记录被 supersede 的记录）
- **验证 Gate**:
  - `get_cross_file_conflicts()` 返回空列表
  - API 每交易日一条
  - `get_coverage()` 不再有多文件分组

---

## 3. R2-002：入库注册时增加唯一性约束

- **风险**: R2（代码 + 可能 DB DDL）
- **操作**:
  1. 在 `_apply_active_filters()` 或入库管道注册 `market_data_files` 时，检查同 `(symbol, contract, period, start_time, end_time)` 是否已有 `data_role='primary'` 记录
  2. 若已有 → 新文件标记为 `candidate` 或拒绝注册
  3. 可选：在 DB 层增加 `UNIQUE INDEX` 或 `EXCLUDE CONSTRAINT`
- **测试**: 模拟两次入库同 key → 第二次应被拦截或标记为 candidate
