#!/usr/bin/env python3
"""Impact classification and active-surface consistency scanning.

Pure repository-local checks. Does not mutate Git remotes, Runtime, data, or
GitHub rules. Collaboration metadata is never used as authorization.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


def _load_personal_workflow():
    module_path = Path(__file__).resolve().parent / "personal_workflow.py"
    spec = importlib.util.spec_from_file_location("personal_workflow", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load personal_workflow.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_workflow = _load_personal_workflow()


class ValidationDomain(StrEnum):
    DOCS = "Docs"
    ENGINEERING = "Engineering"
    BACKEND = "Backend"
    WEB = "Web"
    DATA_CORE = "DataCore"
    STRATEGY = "Strategy"
    RUNTIME = "Runtime"
    MIGRATION = "Migration"
    ALL_SAFE = "AllSafe"


class FindingSeverity(StrEnum):
    ERROR = "error"
    WARN = "warn"


class FindingType(StrEnum):
    COLLABORATION_BLOCKER = "collaboration_blocker"
    RETIRED_REFERENCE = "retired_reference"
    MISSING_BOUNDARY = "missing_boundary"
    MISSING_FILE = "missing_file"
    RETAINED_RETIRED_ASSET = "retained_retired_asset"


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    finding_type: FindingType
    severity: FindingSeverity
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "finding_type": self.finding_type.value,
            "severity": self.severity.value,
            "detail": _workflow.redact_text(self.detail, max_length=384),
        }


ACTIVE_CANONICAL_PATHS: tuple[str, ...] = (
    "AGENTS.md",
    "STATUS.md",
    "PROJECT_SOURCE.md",
    "DECISIONS.md",
    "docs/DEVELOPMENT.md",
    "docs/PERSONAL_DEVELOPMENT_WORKFLOW.md",
)

RETIRED_PATHS: tuple[str, ...] = (
    "docs/WORKTREE_RELEASE_WORKFLOW.md",
    "docs/decisions/ADR-WS-003-develop-release-worktree-lifecycle.md",
    "docs/decisions/ADR-WS-004-five-layer-manual-pr.md",
)

_ROOT_DOC_NAMES = {
    "AGENTS.md",
    "STATUS.md",
    "PROJECT_SOURCE.md",
    "DECISIONS.md",
    "TESTING.md",
    "README.md",
    "SECURITY.md",
}

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

PROTECTED_BOUNDARIES: Mapping[str, str] = {
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
        r"(?:通知|notification).{0,160}(?:研究观察|observation-only).{0,100}"
        r"(?:非交易指令|不是交易指令|not.{0,20}trading instruction)"
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


def normalize_repo_relative(path: str | Path) -> str:
    text = str(path).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def classify_changed_paths(paths: Iterable[str | Path]) -> frozenset[ValidationDomain]:
    """Map changed repository-relative paths to validation domains.

    ``AllSafe`` is never emitted here; it is a profile that unions domains.
    """

    domains: set[ValidationDomain] = set()
    for raw in paths:
        rel = normalize_repo_relative(raw)
        if not rel:
            continue
        lower = rel.lower()
        name = Path(rel).name

        if lower.startswith("docs/") or name in _ROOT_DOC_NAMES or lower.endswith(".md"):
            if lower.startswith("docs/tasks/") or name in _ROOT_DOC_NAMES or lower.startswith("docs/"):
                domains.add(ValidationDomain.DOCS)
            elif lower.endswith(".md"):
                domains.add(ValidationDomain.DOCS)

        if (
            lower.startswith("scripts/engineering/")
            or lower.startswith("tests/engineering/")
            or lower.startswith(".codex/")
            or lower.startswith(".github/workflows/")
            or name in {"Makefile", "GNUmakefile"}
        ):
            domains.add(ValidationDomain.ENGINEERING)

        if lower.startswith("apps/quant-web/") or lower.startswith("apps/"):
            domains.add(ValidationDomain.WEB)

        if "alembic" in lower or "/migrations/" in lower or lower.endswith("/migration.py"):
            domains.add(ValidationDomain.MIGRATION)

        if any(
            token in lower
            for token in (
                "runtime",
                "live_",
                "/live/",
                "notification",
                "wecom",
                "qywx",
            )
        ):
            domains.add(ValidationDomain.RUNTIME)

        if any(
            token in lower
            for token in (
                "strategy",
                "backtest",
                "signal",
                "htdy",
                "indicator",
            )
        ):
            domains.add(ValidationDomain.STRATEGY)

        if any(
            token in lower
            for token in (
                "data_core",
                "data-core",
                "market_data",
                "parquet",
                "manifest",
                "catalog",
                "main_contract",
                "dataset_key",
            )
        ):
            domains.add(ValidationDomain.DATA_CORE)

        if lower.startswith("services/quant-api/") or lower.startswith("packages/quant-core/"):
            domains.add(ValidationDomain.BACKEND)

        if not domains:
            domains.add(ValidationDomain.ENGINEERING)

    if not domains:
        return frozenset({ValidationDomain.DOCS})
    return frozenset(domains)


_PROFILE_ORDER: tuple[ValidationDomain, ...] = (
    ValidationDomain.DOCS,
    ValidationDomain.ENGINEERING,
    ValidationDomain.BACKEND,
    ValidationDomain.WEB,
    ValidationDomain.DATA_CORE,
    ValidationDomain.STRATEGY,
    ValidationDomain.RUNTIME,
    ValidationDomain.MIGRATION,
)


def select_validation_profiles(
    domains: Iterable[ValidationDomain | str],
    *,
    all_safe: bool = False,
) -> list[ValidationDomain]:
    """Return deterministic ordered profiles for local validation."""

    if all_safe:
        return [ValidationDomain.ALL_SAFE]

    selected = {
        domain if isinstance(domain, ValidationDomain) else ValidationDomain(domain)
        for domain in domains
    }
    selected.discard(ValidationDomain.ALL_SAFE)
    if not selected:
        return [ValidationDomain.DOCS]
    return [domain for domain in _PROFILE_ORDER if domain in selected]


def preserve_unrelated_dirty_paths(
    before_paths: Iterable[str | Path],
    after_paths: Iterable[str | Path],
    task_scope: Iterable[str | Path],
) -> tuple[str, ...]:
    """Return unrelated paths whose membership changed (should be empty).

    The helper never mutates the worktree; callers compare path sets only.
    """

    before = {normalize_repo_relative(path) for path in before_paths}
    after = {normalize_repo_relative(path) for path in after_paths}
    scope = {normalize_repo_relative(path) for path in task_scope}
    unrelated_before = before - scope
    unrelated_after = after - scope
    drift = sorted((unrelated_before ^ unrelated_after) | (unrelated_before - after) | (after - before - scope))
    return tuple(path for path in drift if path)


def split_clauses(text: str) -> list[str]:
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


def is_collaboration_blocker(clause: str) -> bool:
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


def _iter_active_surface_files(repo_root: Path) -> list[Path]:
    surfaces: list[Path] = []
    scanner_path = (repo_root / "scripts" / "engineering" / "repository_consistency.py").resolve()
    for relative in ACTIVE_CANONICAL_PATHS:
        surfaces.append(repo_root / relative)
    for relative in (
        "TESTING.md",
        "README.md",
        "docs/PERSONAL_DEVELOPMENT_WORKFLOW.md",
    ):
        path = repo_root / relative
        if path.is_file() and path not in surfaces:
            surfaces.append(path)

    for base in (
        repo_root / ".codex",
        repo_root / "scripts" / "engineering",
        repo_root / ".github" / "workflows",
        repo_root / "docs" / "tasks",
    ):
        if not base.exists():
            continue
        if base.is_file():
            surfaces.append(base)
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix.lower() in {
                ".md",
                ".py",
                ".ps1",
                ".sh",
                ".yml",
                ".yaml",
                ".toml",
                ".rules",
            }:
                if path.resolve() == scanner_path:
                    continue
                surfaces.append(path)
    return surfaces


def scan_active_surfaces(repo_root: Path | str) -> list[Finding]:
    root = Path(repo_root).resolve()
    findings: list[Finding] = []

    for relative in ACTIVE_CANONICAL_PATHS:
        if not (root / relative).is_file():
            findings.append(
                Finding(
                    relative,
                    FindingType.MISSING_FILE,
                    FindingSeverity.ERROR,
                    "active canonical file is missing",
                )
            )
    for relative in RETIRED_PATHS:
        if (root / relative).exists():
            findings.append(
                Finding(
                    relative,
                    FindingType.RETAINED_RETIRED_ASSET,
                    FindingSeverity.ERROR,
                    "retired workflow/ADR asset remains in the active tree",
                )
            )

    texts: dict[str, str] = {}
    for path in _iter_active_surface_files(root):
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        texts[relative] = text
        for clause in split_clauses(text):
            if _RETIRED_PATH_REFERENCE.search(clause):
                findings.append(
                    Finding(
                        relative,
                        FindingType.RETIRED_REFERENCE,
                        FindingSeverity.ERROR,
                        clause[:240],
                    )
                )
            if _RETIRED_IDENTIFIERS.search(clause) and not _RETIREMENT_CONTEXT.search(clause):
                findings.append(
                    Finding(
                        relative,
                        FindingType.RETIRED_REFERENCE,
                        FindingSeverity.ERROR,
                        f"ADR lacks superseded context: {clause[:200]}",
                    )
                )
            if is_collaboration_blocker(clause):
                findings.append(
                    Finding(
                        relative,
                        FindingType.COLLABORATION_BLOCKER,
                        FindingSeverity.ERROR,
                        clause[:240],
                    )
                )

    canonical_blob = "\n".join(
        texts[path] for path in ACTIVE_CANONICAL_PATHS if path in texts
    )
    for name, pattern in PROTECTED_BOUNDARIES.items():
        if re.search(pattern, canonical_blob, re.IGNORECASE | re.DOTALL) is None:
            findings.append(
                Finding(
                    "AGENTS.md",
                    FindingType.MISSING_BOUNDARY,
                    FindingSeverity.ERROR,
                    f"protected boundary missing or weakened: {name}",
                )
            )

    findings.sort(key=lambda item: (item.path, item.finding_type.value, item.detail))
    return findings


class TaskDisposition(StrEnum):
    ACTIVE_CONTRACT = "active_contract"
    HISTORICAL_FACT = "historical_fact"
    FROZEN_RUNTIME_CONSUMED = "frozen_runtime_consumed"
    SUPERSEDED_UNREFERENCED = "superseded_unreferenced"


# Explicit disposition seeds for files still present under docs/tasks/.
# Deleted historical contracts are recovered only via Git history.
_FROZEN_RUNTIME_TASKS = frozenset()
_ACTIVE_CONTRACT_TASKS = frozenset(
    {
        "GY-DATA-CORE-V2.md",
    }
)
_HISTORICAL_FACT_TASKS = frozenset()


@dataclass(frozen=True, slots=True)
class TaskDispositionRecord:
    path: str
    disposition: TaskDisposition
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "disposition": self.disposition.value,
            "detail": _workflow.redact_text(self.detail, max_length=240),
        }


def _task_file_referenced(repo_root: Path, relative: str) -> bool:
    needle = relative.replace("\\", "/")
    name = Path(needle).name
    search_roots = (
        repo_root / "AGENTS.md",
        repo_root / "STATUS.md",
        repo_root / "PROJECT_SOURCE.md",
        repo_root / "DECISIONS.md",
        repo_root / "TESTING.md",
        repo_root / "README.md",
        repo_root / "docs",
        repo_root / "services",
        repo_root / "scripts",
        repo_root / "tests",
    )
    for root in search_roots:
        if root.is_file():
            try:
                text = root.read_text(encoding="utf-8")
            except OSError:
                continue
            if needle in text or name in text:
                if root.resolve() == (repo_root / needle).resolve():
                    continue
                return True
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".py", ".ps1", ".yml", ".yaml", ".toml", ".rules"}:
                continue
            try:
                if path.resolve() == (repo_root / needle).resolve():
                    continue
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if needle in text or name in text:
                return True
    return False


def inventory_task_dispositions(repo_root: Path | str) -> list[TaskDispositionRecord]:
    """Classify every docs/tasks/*.md file with exactly one disposition."""

    root = Path(repo_root).resolve()
    tasks_dir = root / "docs" / "tasks"
    records: list[TaskDispositionRecord] = []
    if not tasks_dir.is_dir():
        return records

    for path in sorted(tasks_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        relative = path.relative_to(root).as_posix()
        name = path.name
        if name in _FROZEN_RUNTIME_TASKS:
            records.append(
                TaskDispositionRecord(
                    relative,
                    TaskDisposition.FROZEN_RUNTIME_CONSUMED,
                    "Runtime/code still consumes this frozen contract or binding",
                )
            )
            continue
        if name in _ACTIVE_CONTRACT_TASKS:
            records.append(
                TaskDispositionRecord(
                    relative,
                    TaskDisposition.ACTIVE_CONTRACT,
                    "active business or future-work contract",
                )
            )
            continue
        if name in _HISTORICAL_FACT_TASKS:
            records.append(
                TaskDispositionRecord(
                    relative,
                    TaskDisposition.HISTORICAL_FACT,
                    "completed execution or incident fact; not current authorization",
                )
            )
            continue
        referenced = _task_file_referenced(root, relative)
        if referenced:
            records.append(
                TaskDispositionRecord(
                    relative,
                    TaskDisposition.HISTORICAL_FACT,
                    "referenced historical task file without active authorization role",
                )
            )
        else:
            records.append(
                TaskDispositionRecord(
                    relative,
                    TaskDisposition.SUPERSEDED_UNREFERENCED,
                    "no active caller or business boundary; eligible for ordinary deletion",
                )
            )

    names = [Path(item.path).name for item in records]
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate task disposition records")
    return records


def build_result(repo_root: Path, findings: Sequence[Finding]) -> Any:
    checks = []
    if findings:
        for finding in findings:
            checks.append(
                _workflow.CheckResult(
                    name=finding.finding_type.value,
                    status=_workflow.CheckStatus.FAILED,
                    detail=f"{finding.path}: {finding.detail}",
                )
            )
        status = _workflow.ResultStatus.FAILED
    else:
        checks.append(
            _workflow.CheckResult(
                name="active_surface_consistency",
                status=_workflow.CheckStatus.PASSED,
                detail="no collaboration blockers or retired active references",
            )
        )
        status = _workflow.ResultStatus.OK

    return _workflow.StableResult(
        tool="scripts/engineering/repository_consistency.py",
        operation=_workflow.ToolOperation.CONSISTENCY,
        mode=_workflow.ResultMode.READ_ONLY,
        status=status,
        checks=tuple(checks),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan active surfaces for personal-development consistency."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--task-inventory",
        action="store_true",
        help="Print in-memory task disposition inventory (not a receipt).",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return 2 if code != 0 else 0

    if args.root is None:
        repo_root = Path(__file__).resolve().parents[2]
    else:
        repo_root = args.root.resolve()
        if not repo_root.is_dir():
            print("invalid --root", file=sys.stderr)
            return 2

    inventory = inventory_task_dispositions(repo_root)
    if args.task_inventory:
        payload = {
            "schema_version": 1,
            "operation": "task_disposition_inventory",
            "status": "ok",
            "tasks": [item.to_dict() for item in inventory],
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0

    findings = scan_active_surfaces(repo_root)
    # Fail if any docs/tasks file could not be classified (should be unreachable).
    if (repo_root / "docs" / "tasks").is_dir():
        expected = {
            path.name
            for path in (repo_root / "docs" / "tasks").glob("*.md")
            if path.name != "README.md"
        }
        classified = {Path(item.path).name for item in inventory}
        missing = sorted(expected - classified)
        if missing:
            findings.append(
                Finding(
                    "docs/tasks",
                    FindingType.MISSING_FILE,
                    FindingSeverity.ERROR,
                    f"unclassified task files: {', '.join(missing)}",
                )
            )

    result = build_result(repo_root, findings)
    if args.json:
        print(result.to_json())
    else:
        if findings:
            print(f"[FAIL] findings={len(findings)}")
            for finding in findings[:50]:
                print(f"  {finding.path}: {finding.finding_type.value}: {finding.detail[:160]}")
            if len(findings) > 50:
                print(f"  ... and {len(findings) - 50} more")
        else:
            print("[OK] active surfaces are consistent with personal development mode")
            print(f"[OK] task dispositions={len(inventory)}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
