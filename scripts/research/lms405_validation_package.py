"""Package existing LMS evidence and validation gaps, without market writes or fills."""

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from guiyi_quant.lms405.validation import (
    FrozenRules,
    REQUIRED_RULES,
    causal_preflight,
    compare_labels,
)

# Relevant references only; other-version risk numbers are not 4.0.5 evidence.
RULE_SOURCES = {
    "KEYBAR": "E07;E53;E54;E58",
    "ENVIRONMENT": "E01;E41;E48;E51;E57",
    "ZONE_GENERATOR": "E48;E56;E57",
    "STAND_FIRM": "E48;E55",
    "ENTRY": "E02;E43;E53",
    "PROTECTION": "E41;E43;E48",
    "RESTORE_EXIT": "E41;E43;E52",
    "TIMEFRAME_POLICY": "E26;E48",
    "QUANTITY_POLICY": "E11;E50",
}


def build_package(root: Path, frozen_at: datetime) -> dict:
    research = root / "docs/research/lms405"
    inputs = [
        research / "sources.csv",
        research / "evidence/action-timeline.csv",
        research / "evidence/rule-identification.csv",
        research / "evidence/batch3.json",
        root / "packages/quant-core/guiyi_quant/lms405/__init__.py",
        root / "packages/quant-core/guiyi_quant/lms405/validation.py",
        root / "scripts/research/lms405_validation_package.py",
    ]
    hashes = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in inputs
    }
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    with inputs[0].open(newline="") as f:
        sources = list(csv.DictReader(f))
    ids = [s["id"] for s in sources]
    if len(ids) != len(set(ids)) or any(
        not s["id"] or not s["url"].startswith("https://weibo.com/") for s in sources
    ):
        raise ValueError("INVALID_SOURCE_INDEX")
    with inputs[1].open(newline="") as f:
        observations = list(csv.DictReader(f))
    with inputs[2].open(newline="") as f:
        constraints = list(csv.DictReader(f))
    if any(o["source"] not in ids for o in observations):
        raise ValueError("OBSERVATION_SOURCE_MISSING")
    references = [s for c in constraints for s in c["sources"].split(";")]
    if any(s not in ids for s in references if re.fullmatch(r"E\d+", s)):
        raise ValueError("RULE_SOURCE_MISSING")
    unresolved_references = sorted(set(references) - set(ids))
    batch = json.loads(inputs[3].read_text())
    # These files contain evidence observations, never a prediction or Fill stream.
    frozen = FrozenRules(
        "lms405-validation-v0.1",
        tuple(sorted(ids)),
        ("POSITION_SEMANTICS",),
        REQUIRED_RULES,
        frozen_at,
        digest,
    )
    for o in observations:
        o["source_url"] = next(s["url"] for s in sources if s["id"] == o["source"])
    failures = [
        dict(category="UNKNOWN_ORIGINAL_RULE", reason=r, sources=RULE_SOURCES[r])
        for r in REQUIRED_RULES
    ]
    failures += [
        dict(
            category="BEHAVIOR_EVIDENCE",
            reason="NO_COMPLETE_TIMED_LIFECYCLE",
            sources="E11;E49;E50",
        ),
        dict(category="HOLDOUT", reason="NO_UNSEEN_HOLDOUT", sources=";".join(ids)),
        dict(category="DATA", reason="FG2609_LOCAL_WINDOW_MISSING", sources="E43"),
        dict(category="ALIGNMENT", reason="NO_AUTHOR_BAR_OHLC", sources="E48;E51"),
        dict(
            category="ACCESS",
            reason="CHROME_CONNECTION_UNAVAILABLE_SKIPPED",
            sources="E26",
        ),
    ]
    failures += [
        dict(category="RULE_REFERENCE_UNRESOLVED", reason=r, sources="E07;E55")
        for r in unresolved_references
    ]
    for row in failures:
        row["source_urls"] = " ".join(
            s["url"] for s in sources if s["id"] in row["sources"].split(";")
        )
    return dict(
        identity="lms405-validation-package-v0.1",
        status="PARTIAL",
        frozen_at=frozen_at.isoformat(),
        rule_scope_fingerprint=frozen.fingerprint,
        definition_digest=digest,
        input_hashes=hashes,
        source_count=len(sources),
        constraint_count=len(constraints),
        development_count=len(sources),
        holdout_count=0,
        author_complete_lifecycles=batch["full_lifecycle_cases"],
        author_bar_samples=batch["author_bar_samples"],
        behavior_metrics=compare_labels([], []),
        behavior_metrics_scope="NO_ELIGIBLE_AUTHOR_CASES; NOT_DISLOSED_ACTION_REPLAY",
        causal=causal_preflight(frozen, {}),
        observations=observations,
        failures=failures,
        work_packages=[
            dict(
                step=6,
                name="决策与持仓管理",
                tool="EXTERNAL_CONDITION_GATE",
                original_status="TRIGGERS_UNKNOWN",
            ),
            dict(
                step=7,
                name="冻结规则与重放",
                tool="HASHED_SCOPE_AND_CHECKPOINT",
                original_status="FORMULA_FREEZE_BLOCKED",
            ),
            dict(
                step=8,
                name="留出及跨合约验证",
                tool="LABEL_METRICS_AND_CONTAMINATION_CHECK",
                original_status="NO_HOLDOUT",
            ),
            dict(
                step=9,
                name="因果可执行性",
                tool="CAUSAL_PREFLIGHT",
                original_status="EXECUTION_FACTS_MISSING",
            ),
            dict(
                step=10,
                name="失败归因",
                tool="SOURCE_LINKED_GAPS",
                original_status="PARTIAL",
            ),
            dict(
                step=11,
                name="研究包交付",
                tool="JSON_CSV_MARKDOWN",
                original_status="PARTIAL_REPLICATION",
            ),
        ],
        executable=False,
        no_download=True,
        no_production_write=True,
        original_formula_identified=False,
    )


def publish(report: dict, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    # Never overwrite an earlier run. report.json is written last as completion artifact.
    with (output / "failures.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["category", "reason", "sources", "source_urls"]
        )
        writer.writeheader()
        writer.writerows(report["failures"])
    lines = [
        "# LMS 4.0.5 后续六项研究结果",
        "",
        "状态：PARTIAL；因果研究：BLOCKED。",
        "",
        f"来源 {report['source_count']} 条；完整作者生命周期 {report['author_complete_lifecycles']}；留出 {report['holdout_count']}。",
        "匹配率、成交及收益没有可验收样本，不提供数值。",
        "",
        "冻结的是研究范围、代码和证据身份，不是已还原的原版公式。",
        "",
        "|步骤|工作包|原版验收|",
        "|---|---|---|",
    ]
    lines += [
        f"|{r['step']}|{r['name']}|{r['original_status']}|"
        for r in report["work_packages"]
    ]
    lines += ["", "## 未满足条件", ""]
    lines += [
        f"- {r['category']}: {r['reason']}（{r['sources']}）"
        for r in report["failures"]
    ]
    lines += [
        "",
        "来源链接与输入哈希见 report.json、failures.csv。",
        "未创建订单、成交、账户、正式策略或 Runtime；工具单元测试不等于作者行为匹配。",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-at", required=True, type=datetime.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    report = build_package(root, args.freeze_at)
    publish(report, args.output)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "source_count",
                    "holdout_count",
                    "author_complete_lifecycles",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
