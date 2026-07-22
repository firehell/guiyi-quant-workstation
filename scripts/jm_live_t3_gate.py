"""JM Live T3 只读 Gate：生成 / 审计 hash-bound 批准包。

写入边界（本脚本）：
- **只读 DB**：PostgreSQL 会话设为 ``READ ONLY``，结束后 rollback
- **create-only 文件**：批准包/审计结果禁止覆盖已存在路径
- **不**触发真实 live 下单或长期 runtime

逻辑在 ``app.services.live_t3_gate``。两种模式：
1. 准备包：``--output`` → ``build_approval_packet``
2. 审计：``--audit-packet`` + 两个 ``--run-result`` → ``build_gate_audit``
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def parse_args() -> argparse.Namespace:
    """解析 prepare（--output）或 audit（--audit-packet）模式参数。"""
    parser = argparse.ArgumentParser(description="Prepare a read-only hash-bound JM T3 approval packet")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-packet", type=Path)
    parser.add_argument("--run-result", action="append", type=Path, default=[])
    parser.add_argument("--audit-output", type=Path)
    return parser.parse_args()


def main() -> int:
    """只读采集 bound facts → 写批准包或审计结果；成功/失败用退出码表示。"""
    args = parse_args()
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.services.live_t3_gate import (
        EXECUTION_FLAGS,
        build_approval_packet,
        build_gate_audit,
        collect_bound_facts,
        load_packet,
    )

    if args.audit_packet is not None:
        if args.audit_output is None or len(args.run_result) != 2:
            raise ValueError("audit requires --audit-output and exactly two --run-result files")
        with SessionLocal() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
            facts = collect_bound_facts(
                session,
                project_root=PROJECT_ROOT,
                execution_flags=EXECUTION_FLAGS,
            )
            session.rollback()
        project_flags = {name: _enabled(os.environ, name) for name in EXECUTION_FLAGS}
        audit = build_gate_audit(
            packet=load_packet(args.audit_packet),
            current_facts=facts,
            run_results=[load_packet(path) for path in args.run_result],
            project_flags=project_flags,
        )
        _write_create_only(args.audit_output, audit)
        print(json.dumps(audit, ensure_ascii=False, indent=2, default=str))
        return 0 if audit["status"] == "passed" else 1

    if args.output is None:
        raise ValueError("prepare requires --output")

    with SessionLocal() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        facts = collect_bound_facts(
            session,
            project_root=PROJECT_ROOT,
            execution_flags=EXECUTION_FLAGS,
        )
        session.rollback()
    packet = build_approval_packet(facts)
    output = args.output.resolve(strict=False)
    _write_create_only(output, packet)
    print(json.dumps({"status": "approval_required", "packet": str(output), "packet_hash": packet["packet_hash"]}, ensure_ascii=False))
    return 0


def _write_create_only(path: Path, payload: dict) -> None:
    """仅允许新建文件；若目标已存在则拒绝覆盖（防篡改批准包）。"""
    output = path.resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _enabled(environ, name: str) -> bool:
    """环境开关是否为真（1/true/yes/on）。"""
    return str(environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
