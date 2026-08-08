from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
HTDY_DOC_ROOT = REPO_ROOT / "docs" / "strategy_specs" / "htdy"


def read_doc(name: str) -> str:
    return (HTDY_DOC_ROOT / name).read_text(encoding="utf-8")


def test_htdy_original_formula_is_documented_as_observation_only() -> None:
    spec = read_doc("INDICATOR_SPEC.md")
    strategy = read_doc("STRATEGY_SPEC.md")

    assert "huotian_dayou_original_v0" in spec
    assert "XMA(XMA(H,25),25)" in spec
    assert "买多预警:买多信号" in spec
    assert "卖空预警:卖空信号" in spec
    assert "status=observation_only" in spec
    assert "| status | `observation_only` |" in strategy
    assert "| alert_capable | `false` |" in strategy
    assert "| backtest_capable | `false` |" in strategy
    assert "| live_capable | `false` |" in strategy


def test_htdy_docs_keep_active_specs_and_git_history_pointers() -> None:
    spec = read_doc("INDICATOR_SPEC.md")
    readme = read_doc("README.md")

    assert "Web 观察层对齐状态" in spec
    assert "白K 按 `BODYH>ZK1 AND BODYH>OVERLOW` 判断" in spec
    assert "`XG` 以红色 `XG观察` 显示" in spec
    assert "`XG2` 未在 Web 展示" in spec
    assert "2. [已完成] Web 观察层对齐" in spec
    assert "4. [已完成] Golden Sample 自动数值验收和外部通达信视觉 oracle 通过" in spec
    assert "GOLDEN_SAMPLE_PASS_VISUAL_ORACLE" in spec
    assert "Git history" in spec
    assert "INDICATOR_SPEC.md" in readme
    assert "STRATEGY_SPEC.md" in readme
    assert "STRICT_V1_SPEC.md" in readme
    # One-time acceptance docs removed from working tree
    assert "INDICATOR_RISK_REVIEW.md" not in readme
    assert "OFFLINE_CANDIDATE_EVAL.md" not in readme
    assert "GOLDEN_SAMPLE_ACCEPTANCE.md" not in readme
