"""Single-product candidate acceptance CLI; explicit read-only operations only."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
from .context import Candidate
from .evidence import EvidenceStore
from .preflight import (
    legacy_identities,
    read_preview,
    validate_assets,
    validate_preview,
)
from .stages import require_stage


def saved_preview(candidate: Candidate, body: dict) -> dict:
    if "api" in body:
        return validate_preview(candidate, body["api"], body["web"])
    results = []
    for origin in (candidate.api_origin, candidate.web_origin):
        report = {}
        for row in body["rows"]:
            if row["origin"] != origin:
                continue
            if row["path"] == "/api/preview/identity":
                report["identity"] = row["payload"]
            if row["path"] == "/api/v1/market/newow/product-capabilities":
                report["capabilities"] = row["payload"]
        results.append(report)
    return validate_preview(candidate, *results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare",
        help="Freeze configuration and native legacy identities; no DB/provider",
    )
    for name in (
        "product",
        "worktree",
        "since",
        "through",
        "as-of",
        "schema",
        "api-origin",
        "web-origin",
        "output",
    ):
        prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--web-code-sha")
    preflight = commands.add_parser(
        "preflight",
        help="Require frozen source, native identities and 12 disabled assets",
    )
    preflight.add_argument("--output", type=Path, required=True)
    preflight.add_argument("--assets", type=Path, required=True)
    preflight.add_argument(
        "--saved-preview", type=Path, help="Validate historical GET evidence offline"
    )
    preflight.add_argument(
        "--execute-get",
        action="store_true",
        help="Perform four bounded loopback GETs; no retry or redirects",
    )
    collect = commands.add_parser(
        "capture",
        help="Explicit candidate-only UI observations; stops on failure, no replay",
    )
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument(
        "--cli",
        type=Path,
        required=True,
        help="Absolute existing Playwright CLI executable",
    )
    collect.add_argument("--session", required=True)
    collect.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly run read-only browser scenarios",
    )
    for command in ("index", "audit"):
        sub = commands.add_parser(
            command,
            help="Offline evidence hashes"
            if command == "index"
            else "Offline 19-scene numerical audit, visual remains pending",
        )
        sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        store = EvidenceStore(Path(args.output).absolute())
        if args.command == "prepare":
            data = vars(args).copy()
            data["code_sha"] = subprocess.check_output(
                ["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
                cwd=args.worktree,
                text=True,
                timeout=15,
            ).strip()
            candidate = Candidate.from_mapping(data)
            context = candidate.frozen_check()
            legacy = legacy_identities(candidate)
            # All preparation is complete before any authoritative-looking file is emitted.
            for name in (
                "candidate.json",
                "context-check.json",
                "legacy-expected-identities.json",
            ):
                if store.path(name).exists():
                    raise FileExistsError(name)
            store.write("candidate.json", candidate.to_mapping())
            store.write("context-check.json", context)
            store.write("legacy-expected-identities.json", legacy)
            result = dict(
                status="PREPARED",
                product=candidate.product,
                code_sha=candidate.code_sha,
                provider_calls=0,
                production_writes=0,
            )
        elif args.command in ("capture", "index", "audit"):
            candidate = Candidate.from_mapping(store.read("candidate.json"))
            if args.command == "capture":
                if not args.execute:
                    raise ValueError("EXPLICIT_CAPTURE_EXECUTION_REQUIRED")
                from .collection import capture

                result = capture(candidate, store.root, args.cli, args.session)
            else:
                from .bundle import build_index, audit_bundle

                result = (
                    build_index(candidate, store)
                    if args.command == "index"
                    else audit_bundle(candidate, store)
                )
                store.write(
                    "evidence-index.json"
                    if args.command == "index"
                    else "offline-audit.json",
                    result,
                )
            if result.get("status") == "BLOCKED":
                print(json.dumps(result, ensure_ascii=False))
                return 1
        else:
            candidate = Candidate.from_mapping(store.read("candidate.json"))
            context = candidate.frozen_check()
            legacy = store.read("legacy-expected-identities.json")
            if legacy != legacy_identities(candidate):
                raise ValueError("LEGACY_IDENTITY_CHANGED")
            assets = validate_assets(candidate, json.loads(args.assets.read_text()))
            require_stage("preflight", dict(context=context, legacy=legacy), candidate)
            if args.execute_get == bool(args.saved_preview):
                raise ValueError("SELECT_SAVED_OR_EXPLICIT_GET")
            preview = (
                read_preview(candidate)
                if args.execute_get
                else saved_preview(
                    candidate, json.loads(args.saved_preview.read_text())
                )
            )
            checks = dict(
                context=context, legacy=legacy, assets=assets, preview=preview
            )
            require_stage("capture", checks, candidate)
            result = candidate.proof(
                checks=checks,
                verification="LIVE_PREVIEW_GET"
                if args.execute_get
                else "SAVED_PREVIEW_ONLY",
                source_asset_input_sha256=__import__("hashlib")
                .sha256(args.assets.read_bytes())
                .hexdigest(),
                no_automatic_attempt_or_retry=True,
            )
            store.write("preflight-check.json", result)
        printed = (
            {k: v for k, v in result.items() if k not in ("rows", "evidence")}
            if args.command in ("index", "audit")
            else result
        )
        print(json.dumps(printed, ensure_ascii=False))
        return 0
    except Exception as exc:
        # No dependency URL, SQL, credentials or traceback in CLI diagnostics.
        code = (
            str(exc)
            if isinstance(exc, ValueError)
            and str(exc).isupper()
            and len(str(exc)) <= 100
            else type(exc).__name__
        )
        print(json.dumps(dict(status="BLOCKED", code=code)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
