# Testing And Gates

更新时间：2026-07-14

事实来源：`TESTING.md`

当前状态：current。

## 文档验证

```bash
git status --short --branch
git diff --check
git diff --stat
git diff --name-only
```

## 状态词扫描

```bash
rg -n "2020|2023|82/90|8 partial|metadata_gap|READY|PARTIAL|PENDING|阿里云|腾讯云|JM2609|report_id=14|Stage 9|五个交易日" \
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md docs tasks --glob '*.md'
```

## 敏感信息扫描

```bash
rg -n -i "password|passwd|token|secret|webhook|api[_-]?key|authorization|cookie" \
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md docs/gpt docs/*.md tasks --glob '*.md'
```

扫描命中安全规则和环境变量名是允许的；不得命中真实密钥值。

## Gate 解释

- 文档验证通过不等于代码测试通过。
- 单元测试通过不等于真实运行 Gate 通过。
- 单次 smoke 不等于长期 ready。
- trust audit passed 不等于盈利或实盘。

