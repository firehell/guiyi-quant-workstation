"""Regression checks for the active personal-development canonical.

These checks intentionally classify authorization clauses instead of banning terms
such as PR, hash, receipt, checksum, or digest globally. Historical facts and data
integrity vocabulary remain valid; collaboration prerequisites do not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_CANONICAL_PATHS = (
    Path("AGENTS.md"),
    Path("STATUS.md"),
    Path("PROJECT_SOURCE.md"),
    Path("DECISIONS.md"),
    Path("docs/DEVELOPMENT.md"),
    Path("docs/PERSONAL_DEVELOPMENT_WORKFLOW.md"),
)
RETIRED_PATHS = (
    Path("docs/WORKTREE_RELEASE_WORKFLOW.md"),
    Path("docs/decisions/ADR-WS-003-develop-release-worktree-lifecycle.md"),
    Path("docs/decisions/ADR-WS-004-five-layer-manual-pr.md"),
)

_COLLABORATION_ARTIFACT = (
    r"(?:github\s+issue|\bissue\b|任务分支|task\s+branch|worktree|draft\s+pr|"
    r"pull\s+request|\bpr\b|独立\s*review|independent\s+review|required\s+ci|"
    r"exact[- ]head|merge\s+readback|ancestry(?:\s+(?:verification|cleanup))?|"
    r"cleanup\s+evidence|approval\s+packet|packet\s+hash|signed\s+(?:approval|receipt)|"
    r"审批包|批准包|签名收据)"
)
_RETIREMENT_CONTEXT = re.compile(
    r"(?:已被|已取代|不再(?:约束|授权|生效)|历史|旧文件|git\s+history|"
    r"supersed(?:ed|ing)|retir(?:ed|ement))",
    re.IGNORECASE,
)
_RETIRED_IDENTIFIERS = re.compile(r"\bADR-WS-00[34]\b", re.IGNORECASE)
_RETIRED_PATH_REFERENCE = re.compile(
    r"(?:docs[\\/]+WORKTREE_RELEASE_WORKFLOW\.md|"
    r"ADR-WS-003-develop-release-worktree-lifecycle\.md|"
    r"ADR-WS-004-five-layer-manual-pr\.md)",
    re.IGNORECASE,
)


def _read_canonical() -> dict[Path, str]:
    return {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in ACTIVE_CANONICAL_PATHS
    }


def _clauses(text: str) -> list[str]:
    """Return paragraph/sentence/table-cell clauses while preserving wrapped lines."""
    blocks: list[str] = []
    current: list[str] = []
    structural = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+\.\s|\|)")

    def flush() -> None:
        if current:
            blocks.append(" ".join(current))
            current.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            flush()
            continue
        if structural.match(line):
            flush()
        current.append(line)
    flush()

    clauses: list[str] = []
    for block in blocks:
        clauses.extend(
            item.strip(" -|`")
            for item in re.split(r"[。；!?！？]|\s*\|\s*", block)
            if item.strip(" -|`")
        )
    return clauses


def _is_collaboration_blocker(clause: str) -> bool:
    """Identify active authorization predicates, not historical/integrity nouns."""
    compact = " ".join(clause.split())

    direct_develop_blockers = (
        r"(?:禁止|不得|不允许|不可).{0,80}(?:直接.{0,20})?(?:在\s*`?develop`?|"
        r"(?:commit|push|提交|推送).{0,30}`?develop`?)",
        r"`?develop`?.{0,80}(?:禁止|不得|不允许|不可).{0,30}(?:编辑|测试|提交|推送|"
        r"edit|test|commit|push)",
        r"(?:must\s+not|may\s+not|cannot(?!\s+prevent)).{0,80}"
        r"(?:work|edit|test|commit|push).{0,30}\bdevelop\b",
        r"\bdevelop\b.{0,60}(?:is\s+)?forbidden",
    )
    if any(re.search(pattern, compact, re.IGNORECASE) for pattern in direct_develop_blockers):
        return True

    if not re.search(_COLLABORATION_ARTIFACT, compact, re.IGNORECASE):
        return False

    positive_predicates = (
        rf"(?<![不无])(?:必须|须|需要|应当|要求|依赖|只有|先).{{0,80}}"
        rf"{_COLLABORATION_ARTIFACT}",
        rf"{_COLLABORATION_ARTIFACT}.{{0,80}}(?<!不)(?:是|作为|构成)"
        rf"[^不，,。；]{{0,24}}(?:授权|前置|准入|必要条件)",
        rf"(?:缺少|没有|未提供).{{0,60}}{_COLLABORATION_ARTIFACT}.{{0,40}}"
        rf"(?:不得|不能|禁止|阻止|拒绝)",
        rf"(?:must\s+(?:have|use|create|pass|obtain)|requires?\s+(?:an?\s+|the\s+)?)"
        rf"{_COLLABORATION_ARTIFACT}",
        rf"{_COLLABORATION_ARTIFACT}.{{0,100}}(?:must\s+(?:exist|pass|complete|be)|"
        rf"is\s+(?:an?\s+)?(?:authorization\s+)?prerequisite|authori[sz]es|"
        rf"required\s+before)",
        rf"cannot.{{0,100}}without.{{0,40}}{_COLLABORATION_ARTIFACT}",
        rf"only.{{0,40}}{_COLLABORATION_ARTIFACT}.{{0,40}}(?:may|can)\s+"
        rf"(?:edit|test|commit|push|authorize)",
    )
    return any(re.search(pattern, compact, re.IGNORECASE) for pattern in positive_predicates)


# Each expression protects a non-collaboration business boundary from accidental
# removal. The values are searched across the canonical set because responsibilities
# are intentionally split among execution, status, product, and workflow documents.
PROTECTED_BOUNDARIES = {
    "9.1 canonical data pipeline": (
        r"RQData.{0,160}staging.{0,160}(?:validation|校验).{0,200}"
        r"(?:historical\s+canonical|Historical\s+Canonical).{0,220}"
        r"(?:八表\s+Catalog|八表\s+Catalog/MainContractMap).{0,160}MarketDataService"
    ),
    "9.2 canonical read interface": r"MarketDataService",
    "9.3 explicit dataset identity": (
        r"DatasetKey.{0,240}continuous.{0,160}actual_dominant"
    ),
    "9.4 physical-integrity failures are explicit without fallback": (
        r"(?:映射|分区|coverage|物理完整性).{0,180}(?:显式失败|不得静默|不静默|不得.*回退|不.*回退|fail)"
    ),
    "9.5 six validations": r"六项(?:硬)?校验",
    "9.7 historical/live separation": (
        r"historical\s+canonical.{0,120}live\s+observation.{0,120}(?:分离|separat|不能|不得)"
    ),
    "9.8 atomic publication integrity": (
        r"(?:原子|atomic).{0,260}(?:part\.parquet|发布)"
    ),
    "9.9 preserve last valid canonical": (
        r"(?:失败|fails?).{0,120}(?:保留|preserve).{0,100}(?:最后有效|last valid).{0,80}canonical"
    ),
    "9.10 formal data mutation intent": (
        r"(?:生产\s*DB|正式数据|production\s+(?:database|data)).{0,180}"
        r"(?:一次性执行意图|明确请求|explicit.{0,30}intent)"
    ),
    "10.1 and 10.8 no orders": (
        r"auto_order\s*=\s*false.{0,160}(?:拒绝|reject).{0,100}(?:订单|order)"
    ),
    "10.2 causal research": r"(?:禁止未来|未来函数|future-data leakage|look-ahead bias)",
    "10.3 Decimal calculations": r"(?:交易相关|trading-related).{0,120}`?Decimal`?",
    "10.4 reproducible backtests": (
        r"(?:回测|backtest).{0,180}(?:策略|strategy).{0,220}(?:trade|equity).{0,160}"
        r"(?:lineage|复算|reproduc)"
    ),
    "10.5 HTDY observation whitelist": (
        r"HTDY\s+original.{0,220}(?:observation-only|观察).{0,120}(?:白名单|whitelist|仅限|只允许)"
    ),
    "10.7 research-not-instruction boundary": (
        r"(?:研究观察|research observation).{0,80}(?:不是交易指令|非交易指令|not.{0,20}trading instruction)"
    ),
    "10.9 canonical companion": (
        r"(?:数据或指标语义|数据、策略、回测、信号或通知语义|data, strategy, backtest, signal, or notification semantics)"
        r".{0,120}(?:同一变更|same change).{0,80}(?:canonical|deep canonical)"
    ),
    "11.1-11.4 operational defaults": (
        r"live.{0,160}Runtime.{0,160}(?:真实通知|real notification).{0,160}"
        r"(?:默认关闭|default.{0,20}(?:off|disabled))"
    ),
    "11.5 separate scoped intent": (
        r"(?:release/tag|release.{0,20}tag).{0,160}(?:不授权|cannot authorize|does not authorize)"
        r".{0,160}Runtime/live"
    ),
    "11.6 historical notification suppression": (
        r"(?:repair/replay/backfill/migration/EOD|repair、replay、backfill、migration).{0,140}"
        r"(?:不补发|不发送|suppress|cannot dispatch)"
    ),
    "11.7 malformed configuration stays off": (
        r"(?:缺失、异常、过期或不一致|absent, malformed, expired, or inconsistent).{0,100}"
        r"(?:保持关闭|continue.{0,20}(?:off|disabled))"
    ),
    "11.8 observation-only notifications": (
        r"(?:通知|notification).{0,160}(?:研究观察|observation-only).{0,100}(?:非交易指令|不是交易指令|not.{0,20}trading instruction)"
    ),
    "11.9 no readiness inference": (
        r"(?:不把结果扩写成|不得.*推导|not.{0,30}infer).{0,160}"
        r"(?:盈利|profitability|long-running|production readiness|生产就绪)"
    ),
    "8.1 and 8.6 secret non-disclosure": (
        r"(?:凭据|credentials).{0,180}(?:token|webhook).{0,180}(?:不进入|禁止|不得|out of)"
    ),
    "8.2-8.5 and 8.7 input validation": (
        r"(?:外部输入|external input).{0,180}(?:类型|type).{0,180}(?:格式|format).{0,180}"
        r"(?:范围|range).{0,180}(?:允许值|allowed values)"
    ),
}


def test_active_canonical_files_exist_and_retired_assets_are_absent() -> None:
    """Validates: Requirements 12.1-12.2, 12.5-12.6."""
    missing = [path.as_posix() for path in ACTIVE_CANONICAL_PATHS if not (ROOT / path).is_file()]
    retained = [path.as_posix() for path in RETIRED_PATHS if (ROOT / path).exists()]

    assert not missing, f"missing active canonical files: {missing}"
    assert not retained, f"retired workflow/ADR assets remain active: {retained}"


def test_active_canonical_has_no_retired_active_references() -> None:
    """Validates: Requirements 2.7-2.8, 12.1-12.2, 12.5-12.6."""
    findings: list[str] = []
    for path, text in _read_canonical().items():
        for clause in _clauses(text):
            if _RETIRED_PATH_REFERENCE.search(clause):
                findings.append(f"{path.as_posix()}: retired path reference: {clause}")
            if _RETIRED_IDENTIFIERS.search(clause) and not _RETIREMENT_CONTEXT.search(clause):
                findings.append(f"{path.as_posix()}: ADR lacks superseded context: {clause}")

    assert not findings, "\n".join(findings)


def test_active_canonical_has_no_collaboration_authorization_blockers() -> None:
    """Validates: Requirements 2.7-2.8, 12.6."""
    findings = [
        f"{path.as_posix()}: {clause}"
        for path, text in _read_canonical().items()
        for clause in _clauses(text)
        if _is_collaboration_blocker(clause)
    ]

    assert not findings, "active collaboration authorization predicates:\n" + "\n".join(findings)


@pytest.mark.parametrize(
    "clause",
    [
        "PR #145 merged commit abc123; this is a completed historical fact, not authorization.",
        "The historical receipt records the observed result and grants no future authority.",
        "Publication validates the Manifest digest, physical checksum, and row count.",
        "旧 packet/hash 只作为历史事实，不构成当前授权。",
    ],
)
def test_context_aware_scan_allows_historical_and_integrity_facts(clause: str) -> None:
    """Validates: Requirements 2.7, 9.8, 12.5."""
    assert not _is_collaboration_blocker(clause)


@pytest.mark.parametrize(
    "clause",
    [
        "普通代码必须先创建 GitHub Issue 才能在 develop 开始。",
        "Only a task worktree may edit code; direct work on develop is forbidden.",
        "Approval packet hash is an authorization prerequisite for ordinary changes.",
        "Ordinary changes cannot be pushed to develop without required CI.",
        "Code changes require a pull request before local validation.",
    ],
)
def test_context_aware_scan_rejects_authorization_predicates(clause: str) -> None:
    """Validates: Requirements 2.8, 12.6."""
    assert _is_collaboration_blocker(clause)


def test_active_historical_and_integrity_clauses_remain_accepted() -> None:
    """Validates: Requirements 2.7, 9.8, 12.5."""
    clauses = [clause for text in _read_canonical().values() for clause in _clauses(text)]
    historical = [
        clause
        for clause in clauses
        if re.search(r"(?:PR|receipt|hash)", clause, re.IGNORECASE)
        and re.search(r"(?:历史|已经发生|已发生|historical|不构成.*授权)", clause, re.IGNORECASE)
    ]
    integrity = [
        clause for clause in clauses if re.search(r"(?:checksum|digest)", clause, re.IGNORECASE)
    ]

    assert historical, "expected canonical historical PR/hash/receipt facts"
    assert integrity, "expected canonical checksum/digest data-integrity clauses"
    assert not [clause for clause in historical + integrity if _is_collaboration_blocker(clause)]


def test_protected_business_boundaries_remain_canonical() -> None:
    """Validates: Requirements 8.1, 9.1-9.10, 10.1-10.9, 11.1-11.9."""
    canonical = "\n".join(_read_canonical().values())
    missing = [
        name
        for name, pattern in PROTECTED_BOUNDARIES.items()
        if re.search(pattern, canonical, re.IGNORECASE | re.DOTALL) is None
    ]

    assert not missing, "protected canonical boundaries removed or weakened: " + ", ".join(missing)
