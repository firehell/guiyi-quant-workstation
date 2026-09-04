# `develop` 收敛实施结果

日期：2026-09-04
状态：`DEVELOP_CONVERGED_CANDIDATE`
实施 baseline：`18a62382685b6deb92010968d4a5a920952fa206`
任务分支：`chore/develop-convergence`
设计：`docs/tasks/2026-09-04-develop-convergence-design.md`
计划：`docs/tasks/2026-09-04-develop-convergence-implementation-plan.md`

## Owner 分发决定

`NEWOW_SCREENSHOT_POLICY=RETAIN`
`DISTRIBUTION_STATUS=DISTRIBUTION_APPROVED_BY_OWNER`

该状态只覆盖 `docs/research/newow-v3.2.82/screenshots/**`，不覆盖原始页面响应、逐 Bar 股票数据或 RQData/Canonical 原文。

## Baseline inventory

- Git status：clean
- Baseline SHA：`18a62382685b6deb92010968d4a5a920952fa206`
- Branch topology：见本任务 PR 的 Task A evidence
- Open PR / Issue：见本任务 PR 的 Task A evidence
- Worktree：见本任务 PR 的 Task A evidence

## Review candidate

- Task G 候选输入 HEAD：`228f4d685c25f47915067e22aea1fce41fd618f0`。
- Task A–F 已完成各自实现、自审、修复轮和独立 commit；当前只进入 Draft PR 候选准备，不提前声明最终收敛完成。
- 最终 exact-head Standards Review、Spec Review、Review 后必要检查、最终 evidence commit 与 Owner“允许集成 develop”Gate 均未执行或未取得。

## Task A–F 收口事实

- Task A 在 `18a62382685b6deb92010968d4a5a920952fa206` 建立 clean baseline 和仓库/GitHub inventory；18 行 remote topology 均为 `ahead=0`，其中 `origin` 已确认为 remote HEAD symref 而非 branch。Task A commit：`66368dcf4f445eb1db9eb46eaf1e8127f5f215db`。
- Task B 删除 35 个 tracked `.playwright-cli/**` raw capture（568,084 行），加入 ignore 与 repository guard；29 个批准保留的 Newow screenshot 逐路径和 SHA-256 绑定，未修改或删除。Task B commits：`01f38c112811b4343ab9855a2f1e5fbb1d204a82`、`ee98d1fe30ee7ad5b27e149f3a9b4958810e7e4a`。
- Task C 删除 3 个无 active inbound reference 的 `docs/superpowers/**` 非 canonical 文档，修正 Issue `#286/#259/#307` 与 PR `#333` stale metadata，并将 Newow futures 当前任务合同同步为 `IMPLEMENTED / EVIDENCE_PARTIAL`。Task C commits：`27a0de41aaa7d22ac70033825ca0c4aa33087bac`、`cb463095bfa40232edaada23f730c7acf954bdc2`。
- Task D 完成退休面、唯一 authority、页面一致性/因果研究隔离审计；FastAPI 0.138 mounted-route guard 以 RED→GREEN 修复，业务 router、策略公式和可信研究口径未改。Task D commits：`20327f345a252f3f854646d98eed9a52050f6a56`、`0ed5538636fc55940f4487409284ccd7ea1b0d94`。
- Task E 在输入 `0ed5538636fc55940f4487409284ccd7ea1b0d94` 上完成批准的 full validation matrix，记录 backend、Newow、engineering、static、Web、E2E、OpenSpec、secret 与 Git checks 的实际输出；`isolated_postgresql` 和 `manual_acceptance` 按计划未运行。本地 `develop@15a557669e39895dc7f243d319f48fb2a695887c` 的并发用户 commit 未被吸收或覆盖。Task E commits：`f074fec1b32632b87ea5df695404317f8bd0c90a`、`a300262cda5957e55fc8d235bf8024733da769e5`。
- Task F 对 16 个普通远端 branch 逐项完成 fresh tip、`ahead_by=0`、ancestor、open PR、worktree 和保护身份预检后显式删除；保留 `main`、`develop`、active release `codex/release-v1.9.15`、当前 task branch、三个本地 worktree及 remote HEAD symref。Task F commit：`228f4d685c25f47915067e22aea1fce41fd618f0`。

## 变更记录

- 删除 tracked `.playwright-cli/**`；Git 历史未重写。
- `.gitignore` 已加入 `.playwright-cli/`。
- Newow screenshot 保留，状态为 `DISTRIBUTION_APPROVED_BY_OWNER`。
- 未恢复或分发原始页面响应、逐 Bar 输入或 RQData/Canonical 原文。
- 删除三个 `docs/superpowers/*` 非 canonical 文件；replacement 与无 active inbound reference 已核验。
- Issue `#286`、`#259` 已关闭为 `NOT_PLANNED`，仅表示 superseded，不冒充旧计划完成。
- Issue `#307` 已更新为 `subing_ths_15m_v3` 当前合同并保持 open。
- PR `#333` metadata 已对齐 current head `2eb33e6d9f8195847b908e399539c5e12f5ff7b6`，旧 SHA Review 标记为 `RELEASE_REVIEW_STALE`。
- `STATUS.md` 仅同步 PR current-head/stale Review 事实；`TESTING.md` 仅增加 repository-hygiene 命令与非授权边界。
- Task C fix round 1 将 Newow futures current task contract 从 blanket pending 同步为 `IMPLEMENTED / EVIDENCE_PARTIAL`：9/9 真实 series 已验证，18 个 D1/60m OOS 单元 passed，9 个 W1 单元因 execution facts 不足 blocked，完整冻结包独立复算仍待补齐。
- Task D 完成 retired surface、single authority 与 Newow research boundary 审计。Fix round 1 修复 FastAPI 0.138 `_IncludedRouter` 使 engineering mounted-route guard 退化为空检查的普通测试回归；未修改业务 router 或策略公式。

## 验证

- Task C guard RED：删除前定向 guard 以 `1 failed` 指出三个 tracked `docs/superpowers/**` 文件。
- Task C guard GREEN：删除后 `tests/engineering/test_repository_hygiene.py` 为 `3 passed`。
- Task C authority scan：首轮扫描没有识别 Newow futures current task contract 与 dossier 的证据状态漂移；fix round 1 已将该 task contract 同步到 dossier 已有事实，保留完整冻结包与 W1 的 pending Gate。旧 Newow V1 文档保留独立版本身份，UI 冲突优先级由 current Market Detail design 明确。
- Task D canonical/retirement：`19 passed, 1 skipped`，exit 0。
- Task D owner readback：CLI domain 仅 `data, runtime`；Alert Rule 仅 `htdy_original_15m, subing_ths_alert_15m_v1`；SuBing formula 为 `subing_ths_15m_v3`。递归展开 mounted router 后确认 active Market 精确为 6 条 HTTP GET：`/api/v1/market/bars/page`、`/api/v1/market/dominants`、`/api/v1/market/newow/trend-detail`、`/api/v1/market/research/home-overview`、`/api/v1/market/research/product`、`/api/v1/market/state`，以及 1 条 WebSocket：`/api/v1/market/ws`；每个 method/path 只有一个冻结 endpoint owner。
- Task D authority scan：6 个 hit 全部人工分类通过。其中 5 个是 Web 显式 series label/choice/type/preference，无 resolver 或 fallback；1 个是 session-anchor repair 在已解析 Canonical root 内对 D1/W1 做不变性 hash 的维护完整性 guard，不是 Historical consumer。旧 SuBing/Trend Focus/Main Force Mirror/market radar active hit 为 0。
- Task D research boundary scan：原固定 scan 59 个 hit 均属显式边界元数据、fail-closed 能力校验、页面参考字段或独立 causal research 版本。Fix round 1 补充 `page[-_]parity|profit_pct|band_signal|newow_causal_next_open_costed_v1` 扫描共 14 个 hit：`main_rise.profit_pct` 只是 BUILD/CLEAR 页面 MA45 参考价差；causal adapter 仅读 `band_signal.action`、当前 `bar.bar_end` 与 `band_signal.formula_version`，不读 `price/profit_pct/hold_bars`，并独立按 next-open/cost/execution facts 计算 PnL。`profit_pct` 无 API/Web/Alert/Runtime/account consumer。Newow 照妖镜固定 `repainting=true` 且 `formal_signal_eligible=false`，causal executor 拒绝其 formula；`reference_change_pct` 明确标记为非真实成交、未计成本/限价/换月的页面参考变化。
- Task D Newow 全量 regression：`553 passed`，exit 0，191.49s。
- Task D 提交前验证：canonical/retirement 复跑 `19 passed, 1 skipped`，OpenSpec strict `8 passed, 0 failed`，secret scan `finding_count=0`，全部 exit 0。
- Task D fix round 1 RED→GREEN：active Market inventory 新 guard 首次以 `actual=[]` 对 7 个预期 owner 失败（`1 failed`）；递归 mounted-route helper 后 active inventory + retired route 定向为 `2 passed`。Newow main-rise/causal 定向为 `36 passed`。
- Task D fix round 1 提交前验证：canonical/retirement `20 passed, 1 skipped`；Ruff `All checks passed!`；OpenSpec strict `8 passed, 0 failed`；secret scan `finding_count=0`；diff check clean；全部 exit 0。
- Task D 四项结论：`retired surface = PASS`；`single authority = PASS`；`research boundary = PASS`；`merge regression = fixed in Task D fix round 1`。`LANE3_BLOCKER = NONE`。
- Task E 验证输入 HEAD：`0ed5538636fc55940f4487409284ccd7ea1b0d94`；验证于 `2026-09-05 01:20 CST` 前完成，未连接 RQData、production PostgreSQL/Redis，未写 Canonical/Scope，未发送通知，未切换 Runtime。
- Task E clean/diff：初始 `git status --short` 与依赖同步后 `git status --short` 均无输出；`git diff --check` exit 0，0.01s。
- Task E 锁定依赖：`uv sync --project services/quant-api --locked` exit 0，0.02s；`pnpm --dir apps/quant-web install --frozen-lockfile` exit 0，0.25s；无 tracked lock 漂移。
- Task E Backend full：`PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q -m "not isolated_postgresql and not manual_acceptance" services/quant-api/tests` 为 `1633 passed, 3 skipped, 15 deselected`，exit 0，199.77s（wall 200.61s）。
- Task E Newow collection/execution readback：对 `services/quant-api/tests/newow` 使用同一 marker 排除条件追加完整回归，`553 passed`，exit 0，191.79s（wall 192.12s）；该 fresh 输出明确证明 Newow tests 被收集和执行，未引用 Task D 旧结果代替。
- Task E engineering full：`PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q tests/engineering` 为 `71 passed`，exit 0，56.09s（wall 56.36s）。为明确 readback 两个必要 owner，追加定向 `test_repository_hygiene.py + test_canonical_consistency.py`，`16 passed`，exit 0，2.80s（wall 3.27s）。
- Task E Python static：Ruff `All checks passed!`，exit 0，0.05s；Mypy `Success: no issues found in 110 source files`，exit 0，6.53s。
- Task E Web ownership/unit/build：Alert Rule ownership `passed`，exit 0，0.66s；Web unit `327 tests / 326 pass / 1 skipped / 0 failed`，exit 0，3.37s；`vue-tsc -b && vite build` 和 bundle-topology 成功，3057 modules transformed，exit 0，4.18s。
- Task E Playwright E2E：`71 passed`，exit 0，1.3m（wall 76.09s）。日志中的 `NETWORK` / `HTTP_502` / `ECONNREFUSED` 来自显式的 unavailable/fail-closed 场景，对应测试全部通过。
- Task E OpenSpec/security/Git：OpenSpec strict `8 passed, 0 failed`，exit 0，1.08s；secret scan `finding_count=0`，exit 0，1.47s；`git diff "$(git merge-base HEAD origin/develop)"...HEAD --check` exit 0；检查时 worktree clean。
- Task E develop comparison：批准的实施 baseline 是 fresh clean `origin/develop@18a62382685b6deb92010968d4a5a920952fa206`，不是本地 `develop`。Task E 完成矩阵后的 `git fetch origin develop` exit 0，4.97s，fresh `origin/develop` 仍为 baseline；因此仅按批准计划不需要 rebaseline 或重跑受影响矩阵。2026-09-05 Task E review fix 的 fresh fetch 后，本地 `develop@15a557669e39895dc7f243d319f48fb2a695887c` 比 `origin/develop` ahead 1，是主 worktree 中的另一并发用户提交，不属于 implementation baseline；本任务未合并、修改或覆盖它，也不声明未来集成冲突已消失。
- Task E 矩阵结论：必要项全部 exit 0，记录真实数量和时间；`isolated_postgresql` 与 `manual_acceptance` 按计划明确未运行，不以本地完整矩阵声明 production、release 或 Runtime 验收。

### Task E 可持久命令证据

以下命令均在 `chore/develop-convergence` 的隔离 worktree 中执行。完整耗时矩阵的代码输入 HEAD 是 `0ed5538636fc55940f4487409284ccd7ea1b0d94`；当时 fresh `origin/develop` 与批准 baseline 都是 `18a62382685b6deb92010968d4a5a920952fa206`。

1. 初始 clean/diff 和锁定依赖：

   ```bash
   git status --short
   /usr/bin/time -p git diff --check
   /usr/bin/time -p uv sync --project services/quant-api --locked
   /usr/bin/time -p pnpm --dir apps/quant-web install --frozen-lockfile
   git status --short
   ```

   五条命令均 exit 0；两次 status 无输出，diff 0.01s，`uv sync` 0.02s，`pnpm install` 0.25s，无 tracked lock 漂移。

2. Backend full：

   ```bash
   PYTHONPATH=services/quant-api:packages/quant-core \
     /usr/bin/time -p uv run --project services/quant-api pytest -q \
     -m "not isolated_postgresql and not manual_acceptance" \
     services/quant-api/tests
   ```

   Exit 0；`1633 passed, 3 skipped, 15 deselected`，pytest 199.77s，wall 200.61s。

3. Newow fresh collection/execution readback：

   ```bash
   PYTHONPATH=services/quant-api:packages/quant-core \
     /usr/bin/time -p uv run --project services/quant-api pytest -q \
     -m "not isolated_postgresql and not manual_acceptance" \
     services/quant-api/tests/newow
   ```

   Exit 0；`553 passed`，pytest 191.79s，wall 192.12s。这是 Task E fresh 完整 Newow 目录回归，不是 Task D 旧数量的复用。

4. Engineering full 与显式 repository/canonical readback：

   ```bash
   PYTHONPATH=services/quant-api:packages/quant-core \
     /usr/bin/time -p uv run --project services/quant-api pytest -q \
     tests/engineering

   PYTHONPATH=services/quant-api:packages/quant-core \
     /usr/bin/time -p uv run --project services/quant-api pytest -q \
     tests/engineering/test_repository_hygiene.py \
     tests/engineering/test_canonical_consistency.py
   ```

   两条命令均 exit 0；full `71 passed`，pytest 56.09s，wall 56.36s；显式 readback `16 passed`，pytest 2.80s，wall 3.27s。

5. Python static：

   ```bash
   /usr/bin/time -p uv run --project services/quant-api python -m ruff check \
     services/quant-api/app services/quant-api/tests \
     packages/quant-core/guiyi_quant tests/engineering

   PYTHONPATH=services/quant-api:packages/quant-core \
   MYPYPATH=services/quant-api:packages/quant-core \
     /usr/bin/time -p uv run --project services/quant-api mypy \
     --explicit-package-bases \
     --ignore-missing-imports \
     services/quant-api/app packages/quant-core/guiyi_quant
   ```

   两条命令均 exit 0；Ruff `All checks passed!`，0.05s；Mypy `Success: no issues found in 110 source files`，6.53s。

6. Web ownership/unit/build/E2E：

   ```bash
   /usr/bin/time -p pnpm --dir apps/quant-web run check:alert-rules
   /usr/bin/time -p pnpm --dir apps/quant-web test
   /usr/bin/time -p pnpm --dir apps/quant-web build
   /usr/bin/time -p pnpm --dir apps/quant-web test:e2e
   ```

   四条命令均 exit 0；ownership passed，0.66s；unit `327 tests / 326 pass / 1 skipped / 0 failed`，3.37s；`vue-tsc -b` + Vite + bundle topology passed，3057 modules，4.18s；Playwright `71 passed`，1.3m（wall 76.09s）。E2E 的 `NETWORK` / `HTTP_502` / `ECONNREFUSED` 是 unavailable/fail-closed 负路径场景的预期日志，不是 suite failure。

7. OpenSpec、secret 和提交前 Git checks：

   ```bash
   /usr/bin/time -p openspec validate --specs --strict --no-interactive
   mkdir -p /tmp/guiyi-develop-convergence
   /usr/bin/time -p python3 scripts/engineering/secret_scan.py --json \
     > /tmp/guiyi-develop-convergence/secret-scan-final.json
   python3 -m json.tool /tmp/guiyi-develop-convergence/secret-scan-final.json
   git merge-base HEAD origin/develop
   git diff "$(git merge-base HEAD origin/develop)"...HEAD --check
   git status --short
   ```

   全部 exit 0；OpenSpec `8 passed, 0 failed`，1.08s；secret scan `finding_count=0`，1.47s；merge-base 为 baseline，branch diff clean，status 无输出。

8. Fresh remote-baseline comparison：

   ```bash
   /usr/bin/time -p git fetch origin develop
   ORIGINAL_BASELINE="$(sed -n 's/^实施 baseline：`\([0-9a-f]\{40\}\)`.*/\1/p' \
     docs/tasks/2026-09-04-develop-convergence-result.md)"
   CURRENT_DEVELOP="$(git rev-parse origin/develop)"
   printf 'original=%s\ncurrent=%s\n' "${ORIGINAL_BASELINE}" "${CURRENT_DEVELOP}"
   test "${ORIGINAL_BASELINE}" = "${CURRENT_DEVELOP}"
   ```

   Fetch 和比较都 exit 0，fetch 4.97s；`original=current=18a62382685b6deb92010968d4a5a920952fa206`。因此仅对 `origin/develop` 基线按批准计划判定无需 rebaseline。

9. 结果文档修改后 checks：

   ```bash
   /usr/bin/time -p git diff --check
   /usr/bin/time -p openspec validate --specs --strict --no-interactive
   /usr/bin/time -p python3 scripts/engineering/secret_scan.py --json \
     > /tmp/guiyi-develop-convergence/secret-scan-final.json
   python3 -m json.tool /tmp/guiyi-develop-convergence/secret-scan-final.json
   git diff "$(git merge-base HEAD origin/develop)"...HEAD --check
   git status --short
   ```

   全部 exit 0；working-tree diff 1.09s；OpenSpec `8 passed, 0 failed`，0.97s；secret scan `finding_count=0`，1.40s；最后 status 仅有预期的结果文档修改。

10. Validation evidence commit 和 readback：

    ```bash
    git add docs/tasks/2026-09-04-develop-convergence-result.md
    git status --short
    git diff --cached --name-only
    /usr/bin/time -p git diff --cached --check
    /usr/bin/time -p git commit -m "docs: record develop convergence validation"
    VALIDATED_HEAD="$(git rev-parse HEAD)"
    printf '%s\n' "${VALIDATED_HEAD}"
    git status --short
    git show --stat --oneline --decorate --no-renames HEAD
    ```

    全部 exit 0；staged path 只有本文档，cached diff clean 0.01s；validation evidence commit 为 `f074fec1b32632b87ea5df695404317f8bd0c90a`，commit 1.10s，提交后 status 无输出。

`f074fec1b32632b87ea5df695404317f8bd0c90a` 是完整矩阵的 validation evidence commit，但 Git commit SHA 不可能自引用地写入生成它自身的 tree：任何写入该 SHA 的 amend 都会生成新 SHA。Task E review fix 只修改本文档，因 `origin/develop` 未前移而不重跑耗时矩阵，只重跑文档受影响 checks。Task F 不得硬编码消费 `f074fec1b...`，必须在开始时 fresh 执行 `git rev-parse HEAD` 并消费当时的 exact current head。

## Branch 清理

- Task F 输入 `VALIDATED_HEAD`：`a300262cda5957e55fc8d235bf8024733da769e5`。fresh fetch 前后 `origin/develop` 均为批准 baseline `18a62382685b6deb92010968d4a5a920952fa206`，未触发 rebaseline stop condition。
- Step 1 open PR readback 只有 #333：`codex/release-v1.9.15@2eb33e6d9f8195847b908e399539c5e12f5ff7b6 -> main`。Task F 时尚无 `chore/develop-convergence` implementation PR；按 Owner 后续交接，Draft implementation PR 在 Task G 创建，当前 task branch 仍为显式保护项。
- 分类时已从 candidates 显式排除本仓库显示的 remote HEAD symref `origin`，以及 `origin/HEAD`、`origin/main`、`origin/develop`。
- 16 个普通远端 branch 在删除前逐项通过：`ahead_by=0`、为 fresh `origin/develop` 祖先、ahead log 为空、无 open PR、无 worktree checkout、fresh fetched tip 与审计 tip 相同，且非 `main`/`develop`/active release/current task。全部以显式 branch name 逐项删除，没有 force、通配符、`xargs` 或 history rewrite。

`DELETED`：

- `codex/full-history-residual-repair-004b-closure@8814990e4aa947b71ba730aac1b0458b98306705`
- `codex/newow-page-v2-coverage-discovery@d2dc53049700d10dab30ee710ca38f7bff21e891`
- `docs/candidate-validation-v1-plan@9b1c8e5f4bb860fca1ae0dd981766ce5187d7a41`
- `docs/develop-convergence-design@324d14afdfb6ff4e071df32b68b8b7cbc0e0b71e`
- `docs/market-detail-v1-remaining-plan@6702bd861789adb2fc97c90ad37f3f88800f547a`
- `docs/market-home-niuwah-implementation-plan@db5265badbd3899ff03bcc7b49e511687a3beb72`
- `docs/n-structure-v1-plan@a00e10f6d3fc976cd6eff9d358225756c19c1ad5`
- `docs/newow-layered-strategy-reconstruction-spec@985120f75293f087293adb128e68a73d82e46acc`
- `docs/newow-slice-b-cup-engine-spec@e15d87a918eeb128efa790ef185cdfcf0bbed4d4`
- `docs/newow-slice-b-plan-alignment@5653fc58009014c00da6f4c53a2cfcc38cc1da6f`
- `docs/subing-ths-alert-15m-v1-implementation-plan@16a8e26bdaa7302ff0046ea5213cff0192b7333c`
- `docs/subing-ths-alert-15m-v1-plan@f1b65b5e001bdb043999c52a803cbfe5b829852a`
- `feature/jm-historical-catchup-foundation-s6-02@7f7e633e0abf01198f7159fea46fa252ba1fda55`
- `feature/newow-trend-page-parity@4085f4dc7e07e29ed4a7981ab19dc9750e5fab0b`
- `task/demo-20260715-003-github-native-v3-final-e2e@b269828830ce639df0758d6915c747834860e959`
- `task/demo-wb-v3-001@75e25e4576f76ea2a43c9feedfd9e99d3eb635cd`

`RETAINED`：无未合并/分叉的普通远端 branch。

`PRESERVED`：

- `main@10d19c3a2b266fb0aefb9abd320d96ff46d410aa`：core branch。
- `develop@18a62382685b6deb92010968d4a5a920952fa206`：core branch 与 fresh remote baseline。
- `codex/release-v1.9.15@2eb33e6d9f8195847b908e399539c5e12f5ff7b6`：active release 且为 open PR #333 head。
- `chore/develop-convergence@a300262cda5957e55fc8d235bf8024733da769e5`：current task branch，Task F 时无 remote ref/current PR，仍硬保留。
- `origin`：指向 `refs/remotes/origin/main` 的 remote HEAD symref，不是 branch candidate。

`LOCAL_WORKTREE_RETAINED`：

- `/Volumes/扩展盘/guiyi-quant-workstation` | `develop@15a557669e39895dc7f243d319f48fb2a695887c` | clean，相对 `origin/develop` ahead 1 | primary/user-owned develop worktree。
- `/Volumes/扩展盘/guiyi-quant-runtime-v1.9.14-r1` | detached `ca15456eaff988db4fe61c37657ca37302a7f977` | clean | detached Runtime worktree。
- `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/develop-convergence` | `chore/develop-convergence@a300262cda5957e55fc8d235bf8024733da769e5` | clean | current task worktree，留待 Task G Owner Gate/集成 readback 后按后续授权处理。

- final `git fetch --prune origin` exit 0，3.56s；`origin/develop` 仍为 baseline。最终远端 branch 只剩 `main`、`develop`、`codex/release-v1.9.15`，open PR 只有 #333。
- 本任务未删除任何本地 worktree 或 local branch，未进入 Task G，未创建 PR，未合入 `develop`。

## Review 与集成

- 固定 Review base：`18a62382685b6deb92010968d4a5a920952fa206`。
- 固定 `REVIEW_HEAD`：`47ca4636a5edd969915492f5ebf0fb186df876ac`。
- Standards reviewer：`/root/final_standards`；结论 `APPROVED`，`P1=0 / P2=0 / P3=0`。审查确认 branch 删除 evidence、35 个 raw capture 删除、29 个批准 screenshot 保留、无 history rewrite/main/release/Runtime/production mutation，并确认完整验证矩阵对代码树仍适用；未发现 documented-standard breach 或有意义的 Fowler smell。
- Spec reviewer：`/root/final_spec`；结论 `APPROVED`，`P1=0 / P2=0 / P3=0`。审查确认截图方案 A、`.playwright-cli` 删除与 ignore、canonical/task/research 唯一分类、Issue `#286/#259/#307`、PR `#333` stale metadata、退休面、研究边界、branch 清理和完成声明均符合 design/plan；未发现缺失、范围外行为或伪实现。
- 两轴结论只批准 exact `REVIEW_HEAD`，不授权 PR ready/merge、`develop` 集成、main/tag/release、Runtime 或 production 操作。

### Review 后 Step 5 fresh targeted checks

在 exact `REVIEW_HEAD` 上于 2026-09-05 执行：

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

- Engineering targeted：exit 0，`16 passed in 2.71s`（wall 3.17s）。
- Secret scan：exit 0，`finding_count=0`，status `passed`（wall 1.46s）。
- OpenSpec strict：exit 0，`8 passed, 0 failed`（wall 1.07s）。
- Three-dot diff check：exit 0，merge-base 为 `18a62382685b6deb92010968d4a5a920952fa206`，无输出（wall 0.04s）。
- `git status --short`：exit 0，无输出。

### Final evidence identity 与 Owner Gate

- 本文档的最终 commit 不可能在自身 Git tree 中写入其自身 SHA；不得把 `REVIEW_HEAD` 虚假标作 final commit。
- Exact `FINAL_HEAD` 必须由提交后 `git rev-parse HEAD`、远端 task ref 与 PR `#335 headRefOid` 的一致 readback 冻结，并由独立 reviewers 对 documentation-only final commit 作 exact-head confirmation；该身份记录在不改变 Git tree 的 PR metadata/执行报告中。
- Owner 尚未明确回复“允许集成 develop”；PR `#335` 必须保持 Draft。Owner Gate 前不得 ready、merge 或清理当前 task worktree/branch。
- 独立未完成 Gate：PR `#333` current-head release Review；`main`/tag/GitHub Release 批准；PF2611 plan/apply；Runtime promotion；自然 SuBing Event；PushPlus provider acceptance；Owner 微信实际送达确认；Newow 后续产品化、参考交易、OOS、Shadow 与模拟账户。
