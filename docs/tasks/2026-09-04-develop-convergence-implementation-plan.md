# `develop` 收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将全分支内容已进入后的 `develop` 收敛为唯一、可验证、可继续开发的集成基线，同时清除原始浏览器采集污染、陈旧文档与元数据，并安全清理无独有提交的普通残留 branch。

**Architecture:** 采用前向、证据驱动的仓库治理流程。先在最新 clean `develop` 上冻结 exact baseline 和只读 inventory，再按“分发安全 → 文档与元数据 → 退役面与 authority → 全量验证 → branch 清理 → exact-head Review”的单向顺序推进；任何不满足删除、语义或验证前提的对象都 fail-closed，不通过猜测或历史重写处理。

**Tech Stack:** Git、Git worktree、GitHub CLI/API、Python 3、pytest、Ruff、Mypy、Node.js、pnpm、Playwright、OpenSpec。

**Spec:** `docs/tasks/2026-09-04-develop-convergence-design.md`

**Execution profile:** Lane 2；Codex App + CLI automation；Sol；高推理；新会话；Plan-then-execute；从最新 `develop` 创建独立 `chore/develop-convergence` task branch/worktree；独立 Standards/Spec Review；最终合入 `develop` 前保留人工 Gate。

## Global Constraints

- 设计 PR #334 及本计划先完成 Review 并合入 `develop`；实施不得直接从 `docs/develop-convergence-design` 分支继续。
- 实施开始时从最新 clean `develop` 创建新 task branch/worktree，并把 40 字符 baseline SHA 写入结果文档。
- `NEWOW_SCREENSHOT_POLICY=RETAIN`，必须保留 `docs/research/newow-v3.2.82/screenshots/**`。
- `DISTRIBUTION_STATUS=DISTRIBUTION_APPROVED_BY_OWNER`，只覆盖现有 Newow screenshot，不覆盖原始 HTML、JavaScript、接口响应、逐 Bar 股票数据或 RQData/Canonical 原文。
- `.playwright-cli/**` 必须在确认无 active consumer 后从当前 Git tree 删除，并由 `.gitignore` 阻止再次进入。
- 不修改 Newow、HTDY、SuBing、Range Detector 的策略或指标公式；不改变成交时序、OOS 口径或可信研究定义。
- 不恢复已退役 Strategy、Backtest、Execution Review、Attention、Trend Focus、Main Force Mirror、N Structure、旧 SuBing Watch 或兼容 reader。
- 不修改 `main`，不合入 PR #333，不创建 tag 或 GitHub Release，不执行 Runtime promotion、真实 RQData/Canonical/production DB/Redis/Scope 写入，不发送真实通知。
- 不修改 GitHub branch protection、ruleset 或 required checks，不进行 rebase shared history、force push 或 history rewrite。
- PR #333 的 `codex/release-v1.9.15` branch 在 Release 流程结束前必须保留；本任务只修正 stale metadata。
- 任何普通 branch 只有在 `ahead_by=0`、非 diverged、无 open PR、未被本地 worktree checkout、远端 tip 未前移时才能删除。
- 任何策略、数据、migration、Runtime 或可信口径冲突均停止本计划对应 Slice，并拆为独立 Lane 3 任务。
- 每个任务结束后提交一个可独立审查的 commit；不得全量暂存无关文件。
- 完成状态只能是 `DEVELOP_CONVERGED`，不能声明 `RELEASED`、`RUNTIME_READY`、`NEWOW_PRODUCT_COMPLETE` 或 `PAPER_ACCOUNT_READY`。

---

## File Structure

### 创建

- `docs/tasks/2026-09-04-develop-convergence-result.md`：记录实施 baseline、inventory、对象分类、GitHub 元数据变更、branch 清理、验证和最终 exact head；不复制完整日志。
- `tests/engineering/test_repository_hygiene.py`：执行仓库级 guard，防止 `.playwright-cli/`、`docs/superpowers/` 和未记录的截图分发状态重新进入 active tree。

### 修改

- `.gitignore`：加入 `.playwright-cli/`。
- `docs/research/newow-v3.2.82/README.md`：记录 `DISTRIBUTION_APPROVED_BY_OWNER` 和方案 A 的边界。
- `STATUS.md`：只修正 PR #333 current head、旧 Review 适用 SHA 和 stale 状态；不改变 Release/Runtime 真实结论。
- `TESTING.md`：增加 repository-hygiene 定向验证命令。
- `docs/tasks/*`：仅在 inventory 证明存在双重 active authority 时修正状态或删除被替代文件。
- `tests/engineering/test_canonical_consistency.py`：仅在现有测试缺少已批准退役/版本 identity guard 时做最小补强；优先把新仓库清洁规则放入独立 `test_repository_hygiene.py`。

### 删除候选

- `.playwright-cli/**`：全部 tracked browser/raw capture。
- `docs/superpowers/specs/2026-08-31-newow-layered-strategy-reconstruction-design.md`。
- `docs/superpowers/plans/2026-09-04-newow-futures-validation.md`。
- `docs/superpowers/plans/2026-09-04-newow-page-v2-real-futures-evidence.md`。
- inventory 证明已经被当前 active contract 取代且无 inbound consumer 的其他重复 task doc。

### GitHub 元数据

- Issue #286：关闭为 `not_planned` / superseded。
- Issue #259：关闭为 `not_planned` / superseded。
- Issue #307：更新为 `subing_ths_15m_v3` 和当前 pending Gate，保持 open。
- PR #333：修正 current head 与旧 Review 适用范围，保持 open，不改 base、不合入。

---

### Task A: 建立 exact baseline、worktree 与只读 inventory

**Files:**
- Create: `docs/tasks/2026-09-04-develop-convergence-result.md`
- Read: `STATUS.md`
- Read: `AGENTS.md`
- Read: `docs/DEVELOPMENT.md`
- Read: `PROJECT_SOURCE.md`
- Read: `DECISIONS.md`
- Read: `docs/ARCHITECTURE.md`
- Read: `TESTING.md`
- Read: `docs/tasks/2026-09-04-develop-convergence-design.md`

**Interfaces:**
- Consumes: 设计 PR #334 已合入后的最新 clean `develop`。
- Produces: `BASELINE_SHA`、task worktree、branch/PR/Issue/worktree/tracked-file inventory，以及后续 Task B–G 使用的删除和保留分类。

- [ ] **Step 1: 确认设计和计划已经进入 `develop`**

Run:

```bash
git fetch --prune origin
BASELINE_SHA="$(git rev-parse origin/develop)"
git show "${BASELINE_SHA}:docs/tasks/2026-09-04-develop-convergence-design.md" \
  | grep -F 'DESIGN_APPROVED / READY_FOR_IMPLEMENTATION_PLAN'
git show "${BASELINE_SHA}:docs/tasks/2026-09-04-develop-convergence-implementation-plan.md" \
  | grep -F '# `develop` 收敛 Implementation Plan'
printf '%s\n' "${BASELINE_SHA}"
```

Expected:

```text
两次 grep 均返回匹配行
BASELINE_SHA 为 40 字符 SHA
```

若设计或计划尚未进入 `develop`，停止实施，不从设计分支直接继续。

- [ ] **Step 2: 创建独立 task worktree**

Run:

```bash
git worktree add \
  /Volumes/扩展盘/guiyi-quant-workstation/.worktrees/develop-convergence \
  -b chore/develop-convergence \
  "${BASELINE_SHA}"
cd /Volumes/扩展盘/guiyi-quant-workstation/.worktrees/develop-convergence
git status --short
git branch --show-current
git rev-parse HEAD
```

Expected:

```text
git status --short 无输出
branch = chore/develop-convergence
HEAD = BASELINE_SHA
```

- [ ] **Step 3: 读取 canonical 和 task contract**

Run:

```bash
sed -n '1,240p' STATUS.md
sed -n '1,260p' AGENTS.md
sed -n '1,220p' docs/DEVELOPMENT.md
sed -n '1,260p' PROJECT_SOURCE.md
sed -n '1,260p' DECISIONS.md
sed -n '1,320p' docs/ARCHITECTURE.md
sed -n '1,320p' TESTING.md
sed -n '1,420p' docs/tasks/2026-09-04-develop-convergence-design.md
```

Expected: 所有文件可读；不存在未解决的事实源冲突。若发现策略、数据、Runtime 或 Release 语义冲突，记录为 blocker 并停止 mutation。

- [ ] **Step 4: 生成 Git、worktree 和远端 branch inventory**

Run:

```bash
mkdir -p /tmp/guiyi-develop-convergence

git status --short > /tmp/guiyi-develop-convergence/status.txt
git worktree list --porcelain > /tmp/guiyi-develop-convergence/worktrees.txt
git for-each-ref \
  --format='%(refname:short)|%(objectname)' \
  refs/remotes/origin \
  | sort > /tmp/guiyi-develop-convergence/remote-branches.txt

while IFS='|' read -r ref sha; do
  case "${ref}" in
    origin/HEAD|origin/main|origin/develop) continue ;;
  esac
  branch="${ref#origin/}"
  merge_base="$(git merge-base origin/develop "${ref}")"
  ahead="$(git rev-list --count origin/develop.."${ref}")"
  behind="$(git rev-list --count "${ref}"..origin/develop)"
  printf '%s|%s|%s|%s|%s\n' \
    "${branch}" "${sha}" "${merge_base}" "${ahead}" "${behind}"
done < /tmp/guiyi-develop-convergence/remote-branches.txt \
  | sort > /tmp/guiyi-develop-convergence/branch-topology.txt

cat /tmp/guiyi-develop-convergence/branch-topology.txt
```

Expected: 每行均含 branch、40 字符 tip、40 字符 merge-base、ahead、behind。任何普通 branch 的 ahead 非 0 时，在结果文档标记 `UNMERGED_BRANCH_BLOCKER`，并禁止 Task F 删除该 branch。

- [ ] **Step 5: 生成 GitHub PR 和 Issue inventory**

Run:

```bash
gh pr list \
  --repo firehell/guiyi-quant-workstation \
  --state open \
  --limit 100 \
  --json number,title,headRefName,headRefOid,baseRefName,isDraft,state,url \
  > /tmp/guiyi-develop-convergence/open-prs.json

gh issue list \
  --repo firehell/guiyi-quant-workstation \
  --state open \
  --limit 200 \
  --json number,title,state,url,updatedAt \
  > /tmp/guiyi-develop-convergence/open-issues.json

python3 -m json.tool /tmp/guiyi-develop-convergence/open-prs.json
python3 -m json.tool /tmp/guiyi-develop-convergence/open-issues.json
```

Expected: 输出为合法 JSON。记录 PR #333 current head；若 PR #333 不存在、已关闭、base 不为 `main` 或 head branch 不为 `codex/release-v1.9.15`，停止 Task C 的 PR 修改并更新计划。

- [ ] **Step 6: 生成 tracked artifact、large file、文档和 version inventory**

Run:

```bash
git ls-files -z \
  | xargs -0 -I{} sh -c 'test -f "$1" && printf "%s|%s\n" "$(wc -c < "$1")" "$1"' _ {} \
  | sort -nr > /tmp/guiyi-develop-convergence/tracked-files-by-size.txt

git ls-files '.playwright-cli/**' \
  > /tmp/guiyi-develop-convergence/playwright-cli-tracked.txt

git ls-files 'docs/superpowers/**' \
  > /tmp/guiyi-develop-convergence/superpowers-tracked.txt

git ls-files 'docs/tasks/**' 'docs/research/**' 'openspec/specs/**' \
  | sort > /tmp/guiyi-develop-convergence/docs-and-specs.txt

git grep -n -E \
  'subing_strategy_v1|subing_watch_15m_v1|Daily Watch|execution_review|main_force_mirror_v2|market_trend_focus|market_radar|docs/superpowers/' \
  -- ':!docs/tasks/2026-09-04-develop-convergence-design.md' \
     ':!docs/tasks/2026-09-04-develop-convergence-implementation-plan.md' \
  > /tmp/guiyi-develop-convergence/retired-reference-scan.txt || true

python3 - <<'PY'
from pathlib import Path
import json
import re
import tomllib

root = Path('.')
pyproject = tomllib.loads((root / 'services/quant-api/pyproject.toml').read_text())
web = json.loads((root / 'apps/quant-web/package.json').read_text())
version_source = (root / 'services/quant-api/app/version.py').read_text()
match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', version_source)
assert match is not None
print({
    'backend': pyproject['project']['version'],
    'web': web['version'],
    'app_version': match.group(1),
})
PY
```

Expected: inventory 文件生成；version 输出三个值一致。此步骤不删除任何文件。

- [ ] **Step 7: 创建结果文档初始骨架**

Run:

```bash
BASELINE_SHA="$(git rev-parse HEAD)"
cat > docs/tasks/2026-09-04-develop-convergence-result.md <<EOF
# \`develop\` 收敛实施结果

日期：2026-09-04  
状态：\`IN_PROGRESS\`  
实施 baseline：\`${BASELINE_SHA}\`  
任务分支：\`chore/develop-convergence\`  
设计：\`docs/tasks/2026-09-04-develop-convergence-design.md\`  
计划：\`docs/tasks/2026-09-04-develop-convergence-implementation-plan.md\`

## Owner 分发决定

\`NEWOW_SCREENSHOT_POLICY=RETAIN\`  
\`DISTRIBUTION_STATUS=DISTRIBUTION_APPROVED_BY_OWNER\`

该状态只覆盖 \`docs/research/newow-v3.2.82/screenshots/**\`，不覆盖原始页面响应、逐 Bar 股票数据或 RQData/Canonical 原文。

## Baseline inventory

- Git status：clean
- Baseline SHA：\`${BASELINE_SHA}\`
- Branch topology：见本任务 PR 的 Task A evidence
- Open PR / Issue：见本任务 PR 的 Task A evidence
- Worktree：见本任务 PR 的 Task A evidence

## 初始 blocker

- 尚待 Task B–G 验证。

## 变更记录

- 尚未执行 mutation。

## 验证

- 尚未运行完成矩阵。

## Branch 清理

- 尚未执行。

## Review 与集成

- 尚未执行。
EOF

git diff -- docs/tasks/2026-09-04-develop-convergence-result.md
```

Expected: 文档写入真实 40 字符 baseline，无 `TBD`、`TODO` 或伪造通过数量。

- [ ] **Step 8: 提交只读 inventory 结果骨架**

Run:

```bash
git add docs/tasks/2026-09-04-develop-convergence-result.md
git diff --cached --check
git commit -m "docs: record develop convergence baseline"
```

Expected: 仅提交结果文档；无业务代码或仓库清理。

---

### Task B: 删除 `.playwright-cli/**`，保留批准截图并建立分发 guard

**Files:**
- Create: `tests/engineering/test_repository_hygiene.py`
- Modify: `.gitignore`
- Modify: `docs/research/newow-v3.2.82/README.md`
- Modify: `docs/tasks/2026-09-04-develop-convergence-result.md`
- Delete: `.playwright-cli/**`

**Interfaces:**
- Consumes: Task A 的 baseline inventory 和 Owner 截图方案 A。
- Produces: 无 tracked `.playwright-cli/**`、明确的截图 Owner 分发状态，以及可执行 repository guard。

- [ ] **Step 1: 证明 `.playwright-cli/**` 没有 active consumer**

Run:

```bash
git grep -n -F '.playwright-cli' -- \
  ':!docs/tasks/2026-09-04-develop-convergence-design.md' \
  ':!docs/tasks/2026-09-04-develop-convergence-implementation-plan.md' \
  ':!docs/tasks/2026-09-04-develop-convergence-result.md' || true

git grep -n -E \
  'browser-page-|browser-signals-|multi-period-browser|oscillation-browser|subplots-browser' \
  -- ':!docs/research/newow-v3.2.82/evidence/full-local-evidence-manifest.json' \
     ':!docs/tasks/2026-09-04-develop-convergence-design.md' \
     ':!docs/tasks/2026-09-04-develop-convergence-implementation-plan.md' || true
```

Expected: 不得出现源码、测试、构建脚本或 active canonical consumer。若存在 consumer，先停止删除并将其迁移方案追加到设计/计划 Review，不在本步骤猜测替代输入。

- [ ] **Step 2: 运行删除前 secret/distribution scan**

Run:

```bash
python3 scripts/engineering/secret_scan.py --json \
  > /tmp/guiyi-develop-convergence/secret-scan-before-cleanup.json
python3 -m json.tool /tmp/guiyi-develop-convergence/secret-scan-before-cleanup.json
```

Expected: 命令成功。若发现真实凭据，停止普通收敛并报告安全事件；不得自行重写历史。

- [ ] **Step 3: 写入首先失败的 raw-capture guard**

Create `tests/engineering/test_repository_hygiene.py`:

```python
"""Repository-level hygiene contracts for the converged develop baseline."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tracked_paths(pathspec: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", pathspec],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def test_local_browser_capture_directory_is_not_tracked_and_is_ignored() -> None:
    assert _tracked_paths(".playwright-cli/**") == ()

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".playwright-cli/probe.json"],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0


def test_newow_screenshot_distribution_owner_decision_is_explicit() -> None:
    readme = (
        ROOT / "docs/research/newow-v3.2.82/README.md"
    ).read_text(encoding="utf-8")
    assert "DISTRIBUTION_APPROVED_BY_OWNER" in readme
    assert "不构成法律意见" in readme

    screenshots = _tracked_paths("docs/research/newow-v3.2.82/screenshots/**")
    assert screenshots
    assert all(
        Path(relative).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        for relative in screenshots
    )
```

- [ ] **Step 4: 运行 guard，确认它按预期失败**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py
```

Expected: FAIL；至少因为 `.playwright-cli/**` 仍被跟踪、`.gitignore` 尚未忽略 probe 或 dossier 尚无 `DISTRIBUTION_APPROVED_BY_OWNER`。

- [ ] **Step 5: 删除 tracked capture 并加入 ignore**

Run:

```bash
printf '\n# local browser capture artifacts\n.playwright-cli/\n' >> .gitignore
git rm -r -- .playwright-cli

git ls-files '.playwright-cli/**'
git check-ignore -v .playwright-cli/probe.json
```

Expected:

```text
git ls-files 无输出
git check-ignore 指向 .gitignore 中的 .playwright-cli/ 规则
```

不得删除 `docs/research/newow-v3.2.82/screenshots/**`。

- [ ] **Step 6: 更新 Newow dossier 的 Owner 分发状态**

Replace README 中“若仓库将设为公开，还应由仓库所有者确认第三方页面截图的公开分发权限”一段为：

```markdown
## Owner 截图分发决定

2026-09-04，仓库 Owner 明确选择方案 A，批准
`docs/research/newow-v3.2.82/screenshots/**` 中现有截图继续保留在当前公开 GitHub
仓库：

```text
DISTRIBUTION_STATUS = DISTRIBUTION_APPROVED_BY_OWNER
NEWOW_SCREENSHOT_POLICY = RETAIN
```

该状态只记录 Owner 的仓库分发选择，不构成法律意见，也不扩大对第三方内容的
权利声明。它不覆盖牛哇完整 HTML、JavaScript、原始接口响应、股票/指数逐 Bar
输入或 RQData/Canonical 原始事实；这些内容仍不得进入 GitHub-safe dossier。
```

- [ ] **Step 7: 运行 guard，确认通过**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py
```

Expected: PASS。

- [ ] **Step 8: 确认仓库没有同类 raw capture 替代副本**

Run:

```bash
git ls-files \
  | grep -E '(^|/)(browser-page-|browser-signals-|multi-period-browser|oscillation-browser|subplots-browser)' \
  && exit 1 || true

git ls-files 'docs/research/newow-v3.2.82/screenshots/**' \
  | wc -l
```

Expected: 第一条无输出；第二条大于 0。

- [ ] **Step 9: 更新结果文档并提交**

在结果文档“变更记录”中写入：

```text
- 删除 tracked `.playwright-cli/**`；Git 历史未重写。
- `.gitignore` 已加入 `.playwright-cli/`。
- Newow screenshot 保留，状态为 `DISTRIBUTION_APPROVED_BY_OWNER`。
- 未恢复或分发原始页面响应、逐 Bar 输入或 RQData/Canonical 原文。
```

Run:

```bash
git add .gitignore \
  docs/research/newow-v3.2.82/README.md \
  docs/tasks/2026-09-04-develop-convergence-result.md \
  tests/engineering/test_repository_hygiene.py
git add -u .playwright-cli
git diff --cached --check
git commit -m "chore: remove tracked browser capture artifacts"
```

Expected: commit 只包含本 Task 文件。

---

### Task C: 收敛非 canonical 文档、task authority、Issue、PR 和 `STATUS.md`

**Files:**
- Modify: `tests/engineering/test_repository_hygiene.py`
- Modify: `STATUS.md`
- Modify: `TESTING.md`
- Modify: `docs/tasks/2026-09-04-develop-convergence-result.md`
- Delete: `docs/superpowers/specs/2026-08-31-newow-layered-strategy-reconstruction-design.md`
- Delete: `docs/superpowers/plans/2026-09-04-newow-futures-validation.md`
- Delete: `docs/superpowers/plans/2026-09-04-newow-page-v2-real-futures-evidence.md`
- GitHub metadata: Issue #286、#259、#307；PR #333

**Interfaces:**
- Consumes: Task A inventory、Task B repository guard 和 current GitHub readback。
- Produces: 无 tracked `docs/superpowers/**` active source、无陈旧 SuBing/Newow Issue authority、PR #333 metadata 与 current head 一致。

- [ ] **Step 1: 重新读取 PR #333 exact head，并固定停止条件**

Run:

```bash
RC_HEAD="$(gh pr view 333 \
  --repo firehell/guiyi-quant-workstation \
  --json headRefOid \
  --jq .headRefOid)"
printf '%s\n' "${RC_HEAD}"
test "${RC_HEAD}" = "2eb33e6d9f8195847b908e399539c5e12f5ff7b6"
```

Expected: 当前 head 仍为 `2eb33e6d9f8195847b908e399539c5e12f5ff7b6`。若不一致，停止本 Task，重新审查 PR body、current head 和 Review 适用范围后修订计划；不得把旧模板应用到新 head。

- [ ] **Step 2: 证明三个 `docs/superpowers/*` 文件已有明确替代事实源**

Run:

```bash
git grep -n -F \
  'docs/superpowers/specs/2026-08-31-newow-layered-strategy-reconstruction-design.md' \
  -- ':!docs/tasks/2026-09-04-develop-convergence-design.md' \
     ':!docs/tasks/2026-09-04-develop-convergence-implementation-plan.md' || true

git grep -n -F \
  'docs/superpowers/plans/2026-09-04-newow-futures-validation.md' \
  -- ':!docs/tasks/2026-09-04-develop-convergence-design.md' \
     ':!docs/tasks/2026-09-04-develop-convergence-implementation-plan.md' || true

git grep -n -F \
  'docs/superpowers/plans/2026-09-04-newow-page-v2-real-futures-evidence.md' \
  -- ':!docs/tasks/2026-09-04-develop-convergence-design.md' \
     ':!docs/tasks/2026-09-04-develop-convergence-implementation-plan.md' || true

for replacement in \
  docs/research/newow-v3.2.82/README.md \
  docs/research/newow-v3.2.82/REPORT.md \
  docs/tasks/2026-09-04-newow-page-parity-research-kernels.md \
  docs/tasks/2026-09-04-newow-futures-validation.md \
  docs/research/newow-v3.2.82/evidence/futures-validation-summary.json \
  docs/research/newow-v3.2.82/evidence/oos-cost-stress-matrix.json; do
  test -f "${replacement}"
done
```

Expected: 不存在除本收敛 Spec/Plan 外的 inbound active reference；全部 replacement 存在。若旧文件含 replacement 中不存在的唯一 active 合同，停止删除并提交 plan amendment，不自行决定迁移位置。

- [ ] **Step 3: 写入首先失败的非 canonical 文档 guard**

Append to `tests/engineering/test_repository_hygiene.py`:

```python

def test_noncanonical_superpowers_documents_are_not_tracked() -> None:
    assert _tracked_paths("docs/superpowers/**") == ()
```

- [ ] **Step 4: 运行 guard，确认按预期失败**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py::test_noncanonical_superpowers_documents_are_not_tracked
```

Expected: FAIL，并列出当前三个 tracked 文件。

- [ ] **Step 5: 删除三个非 canonical 文件**

Run:

```bash
git rm -- \
  docs/superpowers/specs/2026-08-31-newow-layered-strategy-reconstruction-design.md \
  docs/superpowers/plans/2026-09-04-newow-futures-validation.md \
  docs/superpowers/plans/2026-09-04-newow-page-v2-real-futures-evidence.md

git ls-files 'docs/superpowers/**'
```

Expected: `git ls-files` 无输出。Git 不跟踪空目录，无需创建 README 或 archive。

- [ ] **Step 6: 运行 guard，确认通过**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py
```

Expected: PASS。

- [ ] **Step 7: 审计 `docs/tasks/*` 的双重 authority**

Run:

```bash
find docs/tasks -maxdepth 1 -type f -print | sort

git grep -n -E \
  '状态：`?(DESIGN_REVIEWED|READY_FOR_IMPLEMENTATION|ACTIVE|CURRENT|权威)' \
  -- 'docs/tasks/*.md' \
  > /tmp/guiyi-develop-convergence/task-authority-scan.txt || true

cat /tmp/guiyi-develop-convergence/task-authority-scan.txt
```

Review each current topic against this fixed map:

```text
Market Detail current design:
  docs/tasks/2026-09-03-market-detail-v1-remaining-design.md
  docs/tasks/2026-09-03-market-detail-v1-remaining-implementation-plan.md

Newow page/research contracts:
  docs/tasks/2026-09-04-newow-page-parity-research-kernels.md
  docs/tasks/2026-09-04-newow-futures-validation.md
  docs/research/newow-v3.2.82/README.md
  docs/research/newow-v3.2.82/REPORT.md

SuBing warm-up current contracts:
  docs/tasks/2026-09-04-subing-live-contract-warmup-design.md
  docs/tasks/2026-09-04-subing-live-contract-warmup-implementation-plan.md

Develop convergence current contracts:
  docs/tasks/2026-09-04-develop-convergence-design.md
  docs/tasks/2026-09-04-develop-convergence-implementation-plan.md
```

Expected: 不存在同一主题两份同时声称 active authority 的文件。发现额外冲突时，只能删除有明确替代关系且无 consumer 的文件；否则在结果文档记录 blocker 并停止 Task C。

- [ ] **Step 8: 更新 `STATUS.md` 的 PR #333 元数据，不改变 Release/Runtime 结论**

在 `v1.9.15 Release candidate` 行中明确写入：

```markdown
| `v1.9.15` Release candidate | PR `#333` 仍指向 `main`，head branch 为 `codex/release-v1.9.15`，当前 GitHub head 为 `2eb33e6d9f8195847b908e399539c5e12f5ff7b6`。PR body 中原 `a9a9ed02c2b172af36795722326dde001e95b7ab` 的全量验证和双轴 Review 只适用于该旧 SHA；current head 因后续 warm-up plan schema 修改处于 `RELEASE_REVIEW_STALE`，必须重新验证和 Review。该 PR 尚未合入 `main`、创建 tag、发布 GitHub Release，也未执行 PF 数据 apply、Runtime promotion 或自然验收。当前全量 `develop` 不属于该 RC。 |
```

保留 `v1.9.14`、production Runtime、Scope、自然 failure 和 pending Gate 的真实内容。

- [ ] **Step 9: 更新 `TESTING.md` 的 repository-hygiene 命令**

Add under “工程一致性与静态检查”:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py \
  tests/engineering/test_canonical_consistency.py
```

并写明该命令只检查 Git tree、canonical identity 和安全边界，不授权 branch 删除、Issue/PR 修改、Release、Runtime 或生产写入。

- [ ] **Step 10: 更新 Issue #307 为 current v3，保持 open**

Create `/tmp/guiyi-develop-convergence/issue-307.md`:

```markdown
## 当前目标

```text
operational 60 个期货品种
→ completed actual_dominant 15m
→ subing_ths_15m_v3
→ immutable exact AlertEvent
→ one-shot PushPlus
→ Market Web Event marker
→ Owner 人工判断
```

## 当前冻结身份

```text
rule_code = subing_ths_alert_15m_v1
formula_version = subing_ths_15m_v3
kind = indicator_observation
frequency = 15m
series_kind = actual_dominant
auto_order = false
```

v3 的数学公式仍为 MACD(12,26,9) exact CROSS + `EMA(CLOSE, 21)`；v3 只冻结修正后的 RQData session Bar/时间、同 physical-contract warm-up 和 rollover 身份。零轴、Range、量能/OI、ATR、EMA 斜率和多周期共振都不是 V1 Gate。

## 当前事实源

- 当前 Release、Runtime、Scope、自然 evidence 与 Gate：`STATUS.md`
- 稳定产品边界：`PROJECT_SOURCE.md`
- 工程授权与安全边界：`AGENTS.md`
- 长期身份和不变量：`DECISIONS.md`
- active 业务合同：`openspec/specs/subing-ths-alert/spec.md`
- warm-up 设计与计划：
  - `docs/tasks/2026-09-04-subing-live-contract-warmup-design.md`
  - `docs/tasks/2026-09-04-subing-live-contract-warmup-implementation-plan.md`

旧的 `2026-09-02-subing-ths-alert-15m-v1-*` 文档已经退出当前 Git tree，不再作为 active source。

## Pending Gate

本 Issue 保持 open，直到以下真实闭环全部完成：

1. 当前 exact RC 重新完成验证和双轴 Review；
2. Owner 独立批准 `main` merge、annotated tag 和 GitHub Release；
3. exact-tag PF2611 read-only plan；
4. Owner 引用 exact plan hash 批准真实 RQData/Canonical apply；
5. Owner 独立批准 Runtime promotion；
6. 自然 completed SuBing 15m Event 进入 immutable `AlertEvent`；
7. one-shot PushPlus provider acceptance；
8. Owner 确认微信实际收到同一自然 Event。

synthetic、replay、backfill、手工发送、provider accepted 或代码测试均不能替代自然 Event 与实际送达确认。本 Issue 不授权订单、账户、自动交易、生产数据写入、Runtime 切换或真实通知。
```

Run:

```bash
gh issue edit 307 \
  --repo firehell/guiyi-quant-workstation \
  --body-file /tmp/guiyi-develop-convergence/issue-307.md

gh issue view 307 \
  --repo firehell/guiyi-quant-workstation \
  --json state,body \
  --jq '{state: .state, has_v3: (.body | contains("subing_ths_15m_v3")), has_old_docs: (.body | contains("2026-09-02-subing-ths-alert-15m-v1-spec.md"))}'
```

Expected:

```json
{"state":"OPEN","has_v3":true,"has_old_docs":false}
```

- [ ] **Step 11: 关闭 Issue #286 为 superseded/not planned**

Run:

```bash
gh issue comment 286 \
  --repo firehell/guiyi-quant-workstation \
  --body '该 Issue 的 `subing_watch_15m_v1` / SMA21 / 保留旧策略路径已被当前 `subing_ths_alert_15m_v1` + `subing_ths_15m_v3` observation 合同取代。当前仍需完成的自然 Event、Release、Runtime 和实际微信送达 Gate 继续由 Issue #307、`STATUS.md` 与 active OpenSpec 承担。关闭为 superseded/not planned；这不表示 Issue #307 或任何外部 Gate 已完成。'

gh issue close 286 \
  --repo firehell/guiyi-quant-workstation \
  --reason 'not planned'

gh issue view 286 \
  --repo firehell/guiyi-quant-workstation \
  --json state,stateReason \
  --jq .
```

Expected: `state=CLOSED`，`stateReason=NOT_PLANNED`。

- [ ] **Step 12: 关闭 Issue #259 为 superseded/not planned**

Run:

```bash
gh issue comment 259 \
  --repo firehell/guiyi-quant-workstation \
  --body '该旧七层 proprietary/clean-room 研究路线已被当前 Newow 范围取代：项目只继续公开可验证、适用于个人期货量化的策略、指标、页面决策和 causal-research；六种私有服务端选股、私有排名/推荐和 AI 自然语言逐字复刻固定为 `UNKNOWN / OUT_OF_SCOPE`。替代事实源为 `docs/research/newow-v3.2.82/`、`docs/tasks/2026-09-04-newow-page-parity-research-kernels.md` 与 `docs/tasks/2026-09-04-newow-futures-validation.md`。关闭为 superseded/not planned，不声明旧七层计划已全部完成，也不构成策略晋升、Release 或 Runtime 授权。'

gh issue close 259 \
  --repo firehell/guiyi-quant-workstation \
  --reason 'not planned'

gh issue view 259 \
  --repo firehell/guiyi-quant-workstation \
  --json state,stateReason \
  --jq .
```

Expected: `state=CLOSED`，`stateReason=NOT_PLANNED`。

- [ ] **Step 13: 修正 PR #333 stale metadata**

Create `/tmp/guiyi-develop-convergence/pr-333.md`:

```markdown
## Current release-candidate state

- Base release: `v1.9.14@ca15456eaff988db4fe61c37657ca37302a7f977`
- Head branch: `codex/release-v1.9.15`
- Current GitHub head: `2eb33e6d9f8195847b908e399539c5e12f5ff7b6`
- Previously reviewed candidate: `a9a9ed02c2b172af36795722326dde001e95b7ab`
- Current status: `RELEASE_METADATA_REFRESHED / RELEASE_REVIEW_STALE`

The verification counts and independent Standards/Spec Reviews previously recorded for
`a9a9ed02c2b172af36795722326dde001e95b7ab` apply only to that exact SHA. The branch
subsequently moved to `2eb33e6d9f8195847b908e399539c5e12f5ff7b6` for a warm-up plan schema
alignment. The current head has not inherited the old exact-head verification or Review.

## Intended release scope

- SuBing completed actual-dominant 15m replay from same physical-contract Canonical history plus completed Live bars;
- hash-locked, default-read-only physical-contract warm-up command and Catalog/Canonical superset validation;
- Market Detail A-D staged workspaces for Trend, HTDY, SuBing and Free;
- Newow futures validation/research kernels;
- fail-closed Market Runtime promotion preflight.

Market Detail B3 Alert Scope Control and Slice E final cutover remain deferred. The current
full `develop` branch is not automatically part of this Release candidate.

## Required next gate

Before any release authorization, the current exact head must independently repeat:

- applicable full verification;
- Standards Review;
- Spec Review;
- GitHub checks readback.

A future exact RC must be identified by its current 40-character SHA. No prior test report,
review, configuration or branch name authorizes merge to `main`, tag creation, GitHub
Release publication, Runtime promotion, PF2611 RQData/Canonical apply, Scope changes or
notification sends.

## Gates not crossed

This PR remains open and unmerged. It does not authorize or perform `main` merge, annotated
tag creation, GitHub Release publication, Runtime promotion, production data mutation,
Scope changes or real notification delivery.
```

Run:

```bash
gh pr edit 333 \
  --repo firehell/guiyi-quant-workstation \
  --body-file /tmp/guiyi-develop-convergence/pr-333.md

gh pr view 333 \
  --repo firehell/guiyi-quant-workstation \
  --json state,baseRefName,headRefName,headRefOid,body \
  --jq '{state: .state, base: .baseRefName, head: .headRefName, sha: .headRefOid, stale: (.body | contains("RELEASE_REVIEW_STALE"))}'
```

Expected:

```json
{"state":"OPEN","base":"main","head":"codex/release-v1.9.15","sha":"2eb33e6d9f8195847b908e399539c5e12f5ff7b6","stale":true}
```

- [ ] **Step 14: 更新结果文档并提交 repository changes**

记录：

```text
- 删除三个 `docs/superpowers/*` 非 canonical 文件；replacement 已核验。
- #286、#259 已关闭为 not planned，不冒充完成。
- #307 已更新为 v3 并保持 open。
- PR #333 metadata 已对齐 current head，Review 标记 stale。
- `STATUS.md` 与 `TESTING.md` 已同步最小必要事实。
```

Run:

```bash
git add STATUS.md TESTING.md \
  tests/engineering/test_repository_hygiene.py \
  docs/tasks/2026-09-04-develop-convergence-result.md
git add -u docs/superpowers
git diff --cached --check
git commit -m "docs: converge repository authorities and metadata"
```

Expected: commit 不包含策略公式、业务功能、Release 或 Runtime mutation。

---

### Task D: 审计退役面、双重 authority 和合并回归

**Files:**
- Read: `tests/engineering/test_canonical_consistency.py`
- Read: active API、CLI、Web、Runtime、Newow 和 Alert registries
- Modify: `docs/tasks/2026-09-04-develop-convergence-result.md`
- Modify source/test files only after a concrete failing test proves an ordinary merge regression; any semantic change requires plan amendment or separate Lane 3 task.

**Interfaces:**
- Consumes: Task B/C 已清理的 Git tree 和现有 executable canonical tests。
- Produces: 一份可审查的 authority/retired-surface结论；无未经计划的业务改动。

- [ ] **Step 1: 运行 canonical consistency 和退休面定向测试**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py \
  services/quant-api/tests/test_subing_retirement.py \
  services/quant-api/tests/alembic/test_subing_retirement_migration.py
```

Expected: PASS。任何 failure 先记录原始测试名和错误，不立即改代码。

- [ ] **Step 2: 运行 active route、CLI、version 和 Alert owner readback**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api python - <<'PY'
from app.guiyi_cli.main import build_parser
from app.main import app
from app.alerts.registry import alert_rule_definitions
from guiyi_quant.indicators.subing_ths import SubingThs15mKernel

routes = sorted({route.path for route in app.routes if hasattr(route, 'path')})
parser = build_parser()
domain = next(action for action in parser._actions if action.dest == 'domain')
print({
    'public_market_routes': [path for path in routes if path.startswith('/api/v1/market')],
    'cli_domains': sorted(domain.choices),
    'alert_rules': sorted(definition.rule_code for definition in alert_rule_definitions()),
    'subing_formula': SubingThs15mKernel.formula_version,
})
PY
```

Expected:

```text
cli_domains = data, runtime
alert_rules = htdy_original_15m, subing_ths_alert_15m_v1
subing_formula = subing_ths_15m_v3
```

任何额外 active strategy/backtest/research CLI domain 或旧 SuBing formula 都是 blocker。

- [ ] **Step 3: 运行静态 authority scan**

Run:

```bash
git grep -n -E \
  'glob\(.*parquet|rglob\(.*parquet|series_kind.*fallback|actual_dominant.*continuous|subing_watch_15m_v1|subing_strategy_v1|main_force_mirror_v2|market_trend_focus|market_radar' \
  -- 'services/quant-api/app/**' 'packages/quant-core/**' 'apps/quant-web/src/**' \
  > /tmp/guiyi-develop-convergence/authority-scan.txt || true

cat /tmp/guiyi-develop-convergence/authority-scan.txt
```

Review every hit against active canonical. Expected: 无 Historical consumer 绕过 `MarketDataService`、无 actual_dominant 自判主力/跨频 fallback、无旧 active surface。研究文档、测试中的负面断言和删除迁移 lineage 可以存在，但不得是 active consumer。

- [ ] **Step 4: 审计 repainting、page-parity 和 causal-research 隔离**

Run:

```bash
git grep -n -E \
  'repainting|page_parity|formal_signal_eligible|newow_causal_next_open_costed_v1|reference_change_pct' \
  -- 'packages/quant-core/**' 'services/quant-api/app/**' 'apps/quant-web/src/**' \
  > /tmp/guiyi-develop-convergence/research-boundary-scan.txt || true

cat /tmp/guiyi-develop-convergence/research-boundary-scan.txt

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  services/quant-api/tests/newow
```

Expected: Newow regression suite PASS；repainting primitive 不进入 formal signal/backtest/Alert/Runtime；page-parity reference 不冒充 causal 或账户收益。

- [ ] **Step 5: 分类 failure，不越权修复**

Use this fixed decision table:

```text
普通导入、类型、route、build 或测试回归
  -> 先写最小 failing regression test
  -> 做最小修复
  -> 运行定向测试
  -> 单独 commit

策略公式、成交时序、数据身份、migration、Runtime 或可信口径冲突
  -> 在 result 文档标记 LANE3_BLOCKER
  -> 不修改相关代码
  -> 停止进入 Task F/G
```

不得以“收敛”为理由调整参数、简化 fail-closed 约束或删除 causality 测试。

- [ ] **Step 6: 记录审计结论并提交**

在结果文档中逐项记录：

```text
retired surface = PASS / BLOCKED
single authority = PASS / BLOCKED
research boundary = PASS / BLOCKED
merge regression = NONE / fixed commit / blocker
```

Run:

```bash
git add docs/tasks/2026-09-04-develop-convergence-result.md
git diff --cached --check
git commit -m "docs: record develop authority audit"
```

Expected: 若无普通回归，commit 只更新结果文档；若有普通回归，每个修复已在独立 commit 中完成并有对应 test evidence。

---

### Task E: 运行完整验证矩阵并冻结 exact task head

**Files:**
- Modify: `docs/tasks/2026-09-04-develop-convergence-result.md`

**Interfaces:**
- Consumes: Task B–D 的最终 Git tree。
- Produces: full validation evidence、`VALIDATED_HEAD` 和进入 branch cleanup 的授权条件。

- [ ] **Step 1: 确认 worktree clean except result update**

Run:

```bash
git status --short
git diff --check
```

Expected: 无未解释 dirty 文件；所有代码/文档改变都已提交。

- [ ] **Step 2: 同步依赖锁定状态**

Run:

```bash
uv sync --project services/quant-api --locked
pnpm --dir apps/quant-web install --frozen-lockfile
```

Expected: 两条命令 exit 0，且 `git status --short` 不产生锁文件漂移。

- [ ] **Step 3: 运行 Backend full suite**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  -m "not isolated_postgresql and not manual_acceptance" \
  services/quant-api/tests
```

Expected: exit 0，0 failed。记录真实 passed/skipped/deselected 数，不复制旧 RC 数量。

- [ ] **Step 4: 运行 engineering suite**

Run:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering
```

Expected: exit 0，包含 `test_repository_hygiene.py` 和 `test_canonical_consistency.py`。

- [ ] **Step 5: 运行 Ruff 和 Mypy**

Run:

```bash
uv run --project services/quant-api python -m ruff check \
  services/quant-api/app services/quant-api/tests \
  packages/quant-core/guiyi_quant tests/engineering

PYTHONPATH=services/quant-api:packages/quant-core \
MYPYPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api mypy \
  --explicit-package-bases \
  --ignore-missing-imports \
  services/quant-api/app packages/quant-core/guiyi_quant
```

Expected: 两条命令 exit 0。

- [ ] **Step 6: 运行 Web ownership、unit、build 和 E2E**

Run:

```bash
pnpm --dir apps/quant-web run check:alert-rules
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
pnpm --dir apps/quant-web test:e2e
```

Expected: 四条命令 exit 0；记录真实 unit/E2E 数量和 build 结果。

- [ ] **Step 7: 运行 OpenSpec、secret scan 和 diff checks**

Run:

```bash
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json \
  > /tmp/guiyi-develop-convergence/secret-scan-final.json
python3 -m json.tool /tmp/guiyi-develop-convergence/secret-scan-final.json
git diff "$(git merge-base HEAD origin/develop)"...HEAD --check
git status --short
```

Expected:

```text
OpenSpec exit 0
secret scan 0 findings
Git diff check exit 0
worktree clean
```

- [ ] **Step 8: 重新检查 `develop` 是否前移**

Run:

```bash
git fetch origin develop
ORIGINAL_BASELINE="$(sed -n 's/^实施 baseline：`\([0-9a-f]\{40\}\)`.*/\1/p' \
  docs/tasks/2026-09-04-develop-convergence-result.md)"
CURRENT_DEVELOP="$(git rev-parse origin/develop)"
printf 'original=%s\ncurrent=%s\n' "${ORIGINAL_BASELINE}" "${CURRENT_DEVELOP}"
test "${ORIGINAL_BASELINE}" = "${CURRENT_DEVELOP}"
```

Expected: 两个 SHA 相同。若 `develop` 前移，先 merge latest `origin/develop` 到 task branch，重建 Task A inventory，并重新运行全部受影响验证；旧输出不覆盖新 head。

- [ ] **Step 9: 写入真实验证结果并提交**

将每条命令、exit code、真实测试数量和时间写入结果文档；不得写“应该通过”或复用旧 PR 结果。

Run:

```bash
git add docs/tasks/2026-09-04-develop-convergence-result.md
git diff --cached --check
git commit -m "docs: record develop convergence validation"
VALIDATED_HEAD="$(git rev-parse HEAD)"
printf '%s\n' "${VALIDATED_HEAD}"
```

Expected: `VALIDATED_HEAD` 为 40 字符 SHA。该 SHA 进入 Task F；后续任何 commit 都使旧验证不再覆盖 final head，必须按影响重跑。

---

### Task F: 安全清理普通残留 branch 和无用 worktree

**Files:**
- Modify: `docs/tasks/2026-09-04-develop-convergence-result.md`
- Git refs: 仅删除通过全部 preflight 的普通残留 branch。

**Interfaces:**
- Consumes: Task E 通过的 `VALIDATED_HEAD`、Task A branch inventory 和当前 PR/worktree readback。
- Produces: 只剩 `main`、`develop`、active release、当前 task/review 以及有明确保留理由的 branch。

- [ ] **Step 1: 重新生成 branch、PR 和 worktree readback**

Run:

```bash
git fetch --prune origin
git worktree list --porcelain \
  > /tmp/guiyi-develop-convergence/worktrees-before-delete.txt

gh pr list \
  --repo firehell/guiyi-quant-workstation \
  --state open \
  --limit 100 \
  --json number,headRefName,headRefOid,baseRefName,state \
  > /tmp/guiyi-develop-convergence/open-prs-before-delete.json

python3 -m json.tool /tmp/guiyi-develop-convergence/open-prs-before-delete.json
```

Expected: PR #333 仍使用 `codex/release-v1.9.15`；当前 implementation PR 使用 `chore/develop-convergence`。二者都不能删除。

- [ ] **Step 2: 生成删除候选，不使用宽泛通配删除**

Create `/tmp/guiyi-develop-convergence/branch-delete-candidates.txt` from the current remote list, excluding exactly:

```text
main
develop
codex/release-v1.9.15
chore/develop-convergence
任何当前 open PR head
任何当前 worktree branch
```

Run:

```bash
git for-each-ref \
  --format='%(refname:short)' \
  refs/remotes/origin \
  | sed 's#^origin/##' \
  | grep -v '^HEAD$' \
  | sort > /tmp/guiyi-develop-convergence/all-remote-branches.txt

cat /tmp/guiyi-develop-convergence/all-remote-branches.txt
```

Expected: 候选逐行显式列出；不得使用 `git branch | xargs git push --delete` 之类宽泛命令。

- [ ] **Step 3: 对每个候选执行五项 preflight**

For each candidate `${branch}`:

```bash
remote_ref="origin/${branch}"
initial_tip="$(git rev-parse "${remote_ref}")"

git merge-base --is-ancestor "${remote_ref}" origin/develop

test -z "$(git log --oneline origin/develop.."${remote_ref}")"

! grep -Fq "refs/heads/${branch}" \
  /tmp/guiyi-develop-convergence/worktrees-before-delete.txt

! python3 - "${branch}" <<'PY'
import json
import sys
from pathlib import Path
branch = sys.argv[1]
prs = json.loads(Path('/tmp/guiyi-develop-convergence/open-prs-before-delete.json').read_text())
raise SystemExit(0 if any(pr['headRefName'] == branch for pr in prs) else 1)
PY

git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
current_tip="$(git rev-parse "${remote_ref}")"
test "${initial_tip}" = "${current_tip}"
```

Expected: 五项均成功。任一项失败时把 branch 记录为 `RETAINED_<REASON>`，不得删除或 force。

- [ ] **Step 4: 逐个删除通过 preflight 的远端 branch**

Run one explicit command per approved branch:

```bash
git push origin --delete <exact-branch-name>
```

Expected: GitHub 返回该 exact branch 已删除。不得把 `main`、`develop`、`codex/release-v1.9.15`、`chore/develop-convergence` 或 open PR head 放入命令。

- [ ] **Step 5: 清理已经合入且未被使用的本地 branch/worktree**

Run:

```bash
git worktree list --porcelain
```

仅对已不再使用、clean、已合入的旧 task worktree执行：

```bash
git worktree remove <exact-worktree-path>
git branch -d <exact-local-branch>
```

Expected: 每次删除前 `git status --short` clean；不得 `-D`。

- [ ] **Step 6: 重新列出远端 branch 并记录结果**

Run:

```bash
git fetch --prune origin
git for-each-ref \
  --format='%(refname:short)|%(objectname)' \
  refs/remotes/origin \
  | sort
```

在结果文档逐项写明：

```text
DELETED: branch + final tip
RETAINED: branch + exact reason
PRESERVED: main / develop / release / current task
```

- [ ] **Step 7: 提交 branch 清理结果**

Run:

```bash
git add docs/tasks/2026-09-04-develop-convergence-result.md
git diff --cached --check
git commit -m "docs: record residual branch cleanup"
```

Expected: 该 commit 只记录真实 readback；branch 删除本身由 GitHub ref history体现。

---

### Task G: exact-head 双轴 Review、最终验证和 `develop` 集成

**Files:**
- Modify: `docs/tasks/2026-09-04-develop-convergence-result.md`
- PR: implementation branch → `develop`

**Interfaces:**
- Consumes: Task A–F 的完整 Git tree、真实元数据 readback 和 branch 清理结果。
- Produces: exact final task head、P1/P2=0 的 Standards/Spec Review、最终 `DEVELOP_CONVERGED` 结论和安全集成记录。

- [ ] **Step 1: 更新结果文档为 Review candidate，不提前写完成**

Set:

```text
状态 = REVIEW_PENDING
```

Write all known facts, unresolved retained branches and validation outputs. Do not write `DEVELOP_CONVERGED` yet.

Run:

```bash
git add docs/tasks/2026-09-04-develop-convergence-result.md
git diff --cached --check
git commit -m "docs: prepare develop convergence review"
REVIEW_HEAD="$(git rev-parse HEAD)"
printf '%s\n' "${REVIEW_HEAD}"
```

Expected: 40 字符 `REVIEW_HEAD`。

- [ ] **Step 2: 创建 Draft implementation PR**

Run:

```bash
git push -u origin chore/develop-convergence

gh pr create \
  --repo firehell/guiyi-quant-workstation \
  --base develop \
  --head chore/develop-convergence \
  --draft \
  --title '[Lane 2] 收敛全分支合并后的 develop' \
  --body-file docs/tasks/2026-09-04-develop-convergence-result.md
```

Expected: Draft PR 指向 `develop`，head 为 exact `REVIEW_HEAD`。

- [ ] **Step 3: 运行 Standards Review**

Reviewer must inspect the exact `REVIEW_HEAD` and report:

```text
P1 count
P2 count
branch deletion evidence
raw capture deletion evidence
no history rewrite / no main / no release / no Runtime mutation
full validation applicability
```

Expected: P1=0，P2=0。否则修复后生成新 SHA，并重跑受影响验证和两轴 Review。

- [ ] **Step 4: 运行 Spec Review**

Reviewer must compare the same exact `REVIEW_HEAD` against:

```text
docs/tasks/2026-09-04-develop-convergence-design.md
docs/tasks/2026-09-04-develop-convergence-implementation-plan.md
```

Review must cover:

```text
截图方案 A 已执行
.playwright-cli 已删除且 ignored
canonical/task/research 分类唯一
Issue #286/#259/#307 状态正确
PR #333 stale metadata 正确
退役面和研究边界未漂移
branch 清理无误删
完成声明未越权
```

Expected: P1=0，P2=0。

- [ ] **Step 5: 在 Review 后重跑最终必要检查**

Run on the exact final task head:

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py \
  tests/engineering/test_canonical_consistency.py

python3 scripts/engineering/secret_scan.py --json
openspec validate --specs --strict --no-interactive
git diff "$(git merge-base HEAD origin/develop)"...HEAD --check
git status --short
```

Expected: 全部 exit 0，secret scan 0 findings，worktree clean。

- [ ] **Step 6: 写入最终 exact-head Review 结果**

Update result document with:

```text
final task head = exact 40-character SHA
Standards Review = P1 0 / P2 0
Spec Review = P1 0 / P2 0
validation = actual command outputs
branch cleanup = actual deleted/retained list
status = DEVELOP_CONVERGED_CANDIDATE
```

Commit and repeat the targeted final checks because this documentation commit changes the head:

```bash
git add docs/tasks/2026-09-04-develop-convergence-result.md
git diff --cached --check
git commit -m "docs: finalize develop convergence evidence"
FINAL_HEAD="$(git rev-parse HEAD)"

PYTHONPATH=services/quant-api:packages/quant-core \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_repository_hygiene.py \
  tests/engineering/test_canonical_consistency.py
python3 scripts/engineering/secret_scan.py --json
openspec validate --specs --strict --no-interactive
git diff "$(git merge-base HEAD origin/develop)"...HEAD --check
```

Expected: 全部 exit 0。独立 reviewers 必须确认文档-only final commit 未改变其结论，或在 `FINAL_HEAD` 上重新签署简短 exact-head confirmation。

- [ ] **Step 7: 请求 Owner 审查并取得“允许集成 develop”**

Present:

```text
FINAL_HEAD
完整 diff 摘要
测试结果
Standards/Spec Review
删除的文件和 branch
保留 branch 及理由
Issue/PR 元数据改变
未触及 main/Release/Runtime/生产写入的证明
```

Expected: Owner 明确回复“允许集成 develop”。未取得该 Gate 不合并。

- [ ] **Step 8: 合入 `develop`**

After the explicit Gate:

```bash
gh pr ready <implementation-pr-number> \
gh pr merge <implementation-pr-number> \
  --repo firehell/guiyi-quant-workstation \
  --merge
```

Expected: PR merged into `develop`。不得修改 `main` 或 PR #333。

- [ ] **Step 9: readback 集成结果并清理当前 task worktree/branch**

Run:

```bash
git fetch --prune origin
MERGED_DEVELOP="$(git rev-parse origin/develop)"
git merge-base --is-ancestor "${FINAL_HEAD}" "${MERGED_DEVELOP}"
git log -1 --oneline origin/develop

cd /Volumes/扩展盘/guiyi-quant-workstation
git worktree remove \
  /Volumes/扩展盘/guiyi-quant-workstation/.worktrees/develop-convergence
git branch -d chore/develop-convergence
git push origin --delete chore/develop-convergence
```

Expected: `FINAL_HEAD` 是新 `origin/develop` 的祖先；task worktree cleanly removed；branch 普通删除成功；`main`、`codex/release-v1.9.15` 和 Runtime 未变化。

- [ ] **Step 10: 最终结论**

Only after Step 9 readback, report:

```text
DEVELOP_CONVERGED
```

同时明确列出仍未完成的独立 Gate：

```text
PR #333 current-head release Review
main/tag/GitHub Release approval
PF2611 plan/apply
Runtime promotion
自然 SuBing Event
PushPlus provider acceptance
Owner 微信实际送达确认
Newow 后续产品化、参考交易、OOS、Shadow 和模拟账户
```

---

## Plan Self-Review

### Spec coverage

- Exact baseline、inventory、worktree 与前移处理：Task A、Task E。
- `.playwright-cli/**` 删除、ignore、raw capture 防回归：Task B。
- 截图方案 A 和 Owner 分发状态：Task B。
- `docs/superpowers/*`、task authority、canonical：Task C。
- Issue #286/#259/#307 与 PR #333：Task C。
- 退役面、双重 authority、page-parity/repainting/causal 隔离：Task D。
- Backend/Web/OpenSpec/secret/diff 全量验证：Task E。
- branch/worktree 安全清理：Task F。
- exact-head Standards/Spec Review、Owner Gate 和 develop 集成：Task G。

### Placeholder scan

本计划不使用 `TBD`、`TODO`、未定义函数或“写适当测试”等开放指令。动态 SHA、PR number 和 branch 列表均通过明确命令读取；任何 readback 不符都有固定停止条件。

### Type and command consistency

- repository guard 统一使用 `_tracked_paths(pathspec: str) -> tuple[str, ...]`。
- baseline、validated head、review head 和 final head 均为 40 字符 Git SHA，不能互相替代。
- `codex/release-v1.9.15` 始终保留；普通 branch 清理不处理 active Release branch。
- `DISTRIBUTION_APPROVED_BY_OWNER` 只用于现有 Newow screenshots；`.playwright-cli/**` 始终删除。
