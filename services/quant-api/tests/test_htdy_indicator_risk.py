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


def test_htdy_xma_and_derived_signals_are_forbidden_for_trusted_signals() -> None:
    review = read_doc("INDICATOR_RISK_REVIEW.md")

    for token in ("`XMA`", "`ZK1/ZD1/ZD2`", "`VAR23`"):
        assert f"| {token} | `forbidden_for_backtest_signal`" in review

    for token in ("`黄K/白K`", "`买多信号/卖空信号`", "`XG`", "`XG2`"):
        assert f"| {token} | `observation_only`" in review

    assert "不得写入 `signal_events`" in review
    assert "不得进入企业微信提醒" in review


def test_htdy_backward_helpers_are_only_rewrite_candidates() -> None:
    review = read_doc("INDICATOR_RISK_REVIEW.md")

    assert "| `DDX` | `candidate_after_rewrite` | 否 | 否 | 否 |" in review
    assert "| `V2/V5/V10/V20` | `candidate_after_rewrite` | 否 | 否 | 否 |" in review
    assert "| `REF/MA/EMA/SMA/LLV/COUNT/CROSS` | `candidate_after_rewrite` | 否 | 否 | 否 |" in review
    assert "单独看可后向，但不得自动升级整个公式" in review


def test_htdy_docs_cross_reference_web_alignment_and_remaining_gates() -> None:
    spec = read_doc("INDICATOR_SPEC.md")
    readme = read_doc("README.md")

    assert "Web 观察层对齐状态" in spec
    assert "白K 按 `BODYH>ZK1 AND BODYH>OVERLOW` 判断" in spec
    assert "`XG` 以红色 `XG观察` 显示" in spec
    assert "`XG2` 未在 Web 展示" in spec
    assert "2. [已完成] Web 观察层对齐" in spec
    assert "4. [未开始] Golden Sample 验收" in spec
    assert "INDICATOR_SPEC.md" in readme
    assert "INDICATOR_RISK_REVIEW.md" in readme
    assert "STRATEGY_SPEC.md" in readme
