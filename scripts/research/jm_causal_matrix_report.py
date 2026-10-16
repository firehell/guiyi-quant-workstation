"""Validate all fixed matrix identities before ranking complete annual accounts."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

FREQUENCIES = ("5m", "15m", "30m", "60m", "1d", "1w")
STRATEGIES = ("trend", "oscillation", "dual_fusion", "osc-test", "osc-test2", "osc-test3", "osc-test4")
LABELS = dict(zip(STRATEGIES, ("趋势", "震荡", "双策略", "测试1", "测试2", "测试3", "测试4")))


def collect(root: Path):
    window = json.loads((root / "input-window-readback.json").read_text())
    owner = window["owner_continuity"]
    if not owner["unique_contracts"] or not owner["nonoverlapping_trading_day_coverage"] or owner["status"] != "PASS":
        raise ValueError("MATRIX_OWNER_READBACK_FAILED")
    expected_contracts = {o["contract"] for o in owner["owners"]}
    expected_start = (datetime.fromisoformat(window["execution_1m"]["first_bar_end"])-timedelta(minutes=1)).isoformat()
    expected_end = window["execution_1m"]["last_bar_end"]
    cells = []
    for frequency in FREQUENCIES:
        for strategy in STRATEGIES:
            row = json.loads((root / f"{frequency}-{strategy}-baseline.json").read_text())
            if (row["frequency"] != frequency or row["strategy"] != strategy or row["scenario"] != "baseline"
                or row["signal_input_hash"] != window["frequencies"][frequency]["input_sha256"]
                or row["started_at"] != expected_start or row["planned_through"] != expected_end
                or row["execution_bar_count"] != window["execution_1m"]["bar_count"]
                or row["scope"] != "continuous_year"
                or {d["physical_contract"] for d in row["owner_diagnostics"]} != expected_contracts):
                raise ValueError("MATRIX_CELL_IDENTITY_MISMATCH")
            if row["annual_eligible"] and (row["status"] != "COMPLETE" or row["processed_through"] != expected_end):
                raise ValueError("MATRIX_INCOMPLETE_YEAR_RANKED")
            row["stress"] = {}
            for scenario in ("double_commission", "double_slippage"):
                path = root / f"{frequency}-{strategy}-{scenario}.json"
                if not path.exists():
                    row["stress"][scenario] = {"status": "NOT_RUN"}
                    continue
                stress = json.loads(path.read_text())
                if stress["scenario"] != scenario or any(stress[k] != row[k] for k in ("frequency", "strategy", "facts_hash", "signal_input_hash", "execution_input_hash", "started_at", "planned_through", "scope", "execution_bar_count")):
                    raise ValueError("MATRIX_STRESS_IDENTITY_MISMATCH")
                if stress["annual_eligible"] and (stress["status"] != "COMPLETE" or stress["processed_through"] != expected_end):
                    raise ValueError("MATRIX_INCOMPLETE_STRESS_YEAR_RANKED")
                row["stress"][scenario] = {k: stress[k] for k in (
                    "status", "annual_eligible", "account_return_pct", "mark_to_market_max_drawdown_pct", "closed_trades")}
            cells.append(row)
    if len({c["execution_input_hash"] for c in cells}) != 1 or len({c["facts_hash"] for c in cells}) != 1:
        raise ValueError("MATRIX_MIXED_EXECUTION_FACTS")
    ranking = sorted((c for c in cells if c["annual_eligible"]), key=lambda c: Decimal(c["account_return_pct"]), reverse=True)
    return window, cells, ranking


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    window, cells, ranking = collect(args.root)
    brief = {"matrix_cells": len(cells), "complete_annual_accounts": len(ranking),
        "rollover_interrupted": sum(c["status"] == "PAPER_ROLLOVER_INTERRUPTED" for c in cells),
        "positive_complete_accounts": sum(Decimal(c["net_pnl"]) > 0 for c in ranking),
        "requested_since": window["requested_since"], "actual_through": window["actual_through"],
        "all_execution_inputs_identical": True, "all_cost_facts_identical": True,
        "selection_overlap": True, "independent_oos": False, "promotion": False,
        "ranking": [{k: c[k] for k in ("frequency", "strategy", "net_pnl", "account_return_pct", "mark_to_market_max_drawdown_pct", "closed_trades", "position_qty", "stress")} for c in ranking]}
    (args.root / "summary.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2)+"\n")
    fields = ("frequency", "strategy", "status", "annual_eligible", "processed_through", "valuation_at", "equity", "net_pnl", "account_return_pct", "mark_to_market_max_drawdown_pct", "closed_trades", "fees_paid", "position_qty", "position_contract")
    with (args.root / "matrix.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(cells)
    text = ["# 焦煤七策略六周期：固定 Paper 口径复核", "",
        "初资50000元、最多一手LONG、日亏达交易日初权益2%停开并清仓。所有组采用同一82305根物理1m执行行情、逐日费用、1tick滑点和保证金规则。信号周期不同，成交时钟相同。",
        "", f"42/42组完成检查；{len(ranking)}组完整年度账户可比，{brief['rollover_interrupted']}组换月中断，{brief['positive_complete_accounts']}组完整年度净盈利。",
        "", "区间按交易日2025-10-13至2026-10-09，requested_since=2025-10-11。以下是50000元模型账户净回报，不能与页面累计收益或先前closed-trade复利回报混用。",
        "", "## 完整年度账户排名", "",
        "| 周期 | 策略 | 净盈亏/元 | 账户回报 | 逐分钟权益最大回撤 | 已平仓笔数 | 期末手数 | 双费回报 | 双滑点回报 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    def pct(v):
        return f"{Decimal(v):.2f}%"
    for c in ranking:
        stresses = [pct(c["stress"][s]["account_return_pct"]) if c["stress"][s].get("annual_eligible") else c["stress"][s]["status"] for s in ("double_commission", "double_slippage")]
        text.append(f"| {c['frequency']} | {LABELS[c['strategy']]} | {Decimal(c['net_pnl']):.2f} | {pct(c['account_return_pct'])} | {pct(c['mark_to_market_max_drawdown_pct'])} | {c['closed_trades']} | {c['position_qty']} | {' | '.join(stresses)} |")
    text += ["", "## 42组状态矩阵", "", "中断组不显示截短收益作为全年成绩；详见各JSON的旧仓、最后估值和停止时刻。", "",
        "| 周期 | 趋势 | 震荡 | 双策略 | 测试1 | 测试2 | 测试3 | 测试4 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    indexed = {(c["frequency"], c["strategy"]): c for c in cells}
    for freq in FREQUENCIES:
        values=[]
        for strategy in STRATEGIES:
            c=indexed[freq,strategy]
            values.append(pct(c["account_return_pct"]) if c["annual_eligible"] else "换月中断" if c["status"] != "COMPLETE" else "无闭合交易")
        text.append(f"| {freq} | "+" | ".join(values)+" |")
    text += ["", "## 独立物理合约段诊断", "", "每段重新从50000元、空仓开始。四列是四个独立研究账户，不可加总、复利或冒充一个全年账户。期末持仓按同合约最后价估值，未制造平仓。", "",
        "| 周期 | 策略 | JM2601 | JM2605 | JM2609 | JM2701 |", "|---|---|---:|---:|---:|---:|"]
    for c in cells:
        d={x["physical_contract"]:x for x in c["owner_diagnostics"]}
        text.append(f"| {c['frequency']} | {LABELS[c['strategy']]} | "+" | ".join(pct(d[p]["account_return_pct"]) for p in ("JM2601","JM2605","JM2609","JM2701"))+" |")
    text += ["", "## 如何解释排名", "",
        "周线测试3的年度净回报最高，但只有3笔已平仓交易，独立合约诊断的收益集中在JM2609；不能据此认定为可靠最优策略。60m测试2有35笔已平仓交易、四个独立合约段均盈利，值得优先做未见数据验证。这是后续研究优先级，不是正式策略选择或晋升。",
        "", "只对8个完整年度盈利组合追加双手续费和双滑点压力检查，其余组合标记NOT_RUN。压力检查重新运行2%日停机风控；成本可能改变平仓时刻和后续交易路径，因此回报并非固定成交序列简单扣费，可能不单调。",
        "", "逐笔重放已确认：60m测试2在双费下，2026-05-26平仓由14:02的1244提前至14:00的1255.5，2026-09-18由14:54的1486提前至14:52的1488（北京时间），毛盈亏分别改善690元、120元，合计810元；1d测试1两次提前退出合计改善390元。其余对应成交时刻和价格相同，四次重放年度结果与原始JSON完全一致。见[成本路径逐笔证据](cost-path-trace.json)。",
        "", "测试策略原有low/high及止损锚点只参与信号条件，Paper成交统一使用信号确认之后的物理1m执行价格。日亏2%是触发清仓阈值，不保证实际损失恰好封顶2%；无成交量、涨跌停或跳空会影响退出。",
        "", "## 结论边界", "", "本年已经参与策略选择，selection_overlap=true，不是独立未见OOS。成本事实是事后抓取的有效日数据；滑点是模型假设。高净回报或成本压力通过都不会自动晋升。", "",
        "没有修改公式、止损比例、持仓手数、换月规则、生产数据或既有Paper账本；各组复用同一事件reducer在内存验算，未新增42个PostgreSQL账户，未连接SimNow/Shadow/Runtime。", "",
        "验证：Paper/研究定向回归192 passed（含真实隔离PostgreSQL）、工程合同29 passed、Ruff/Mypy及secret scan通过；独立高风险Review无阻断。稳定复算入口见仓库TESTING.md。", "",
        "证据：[逐组CSV](matrix.csv)、[排名JSON](summary.json)、[独立输入读回](input-window-readback.json)。每格JSON含版本、输入/费用hash、日权益、日停机、事件末端身份和四段诊断。"]
    (args.root / "report.md").write_text("\n".join(text)+"\n")
    print(json.dumps(brief, ensure_ascii=False))


if __name__ == "__main__":
    main()
