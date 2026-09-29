"""Native formula preparation and bounded GET identity gates."""

from __future__ import annotations
from importlib import import_module
import inspect
from pathlib import Path
import urllib.request
import json
import re
from .context import Candidate, FREQUENCIES, instant, need

CAPABILITIES = {
    "newow_product_capabilities_v25": "rb_intraday_candidate",
    "newow_product_capabilities_v26": "black_steel_intraday_candidate",
    "newow_product_capabilities_v27": "single_product_intraday_candidate",
}


def validate_preview(candidate: Candidate, api: dict, web: dict) -> dict:
    caps = []
    for report, expected_code in (
        (api, candidate.code_sha),
        (web, candidate.web_code_sha or candidate.code_sha),
    ):
        ident = report["identity"]
        need(
            ident.get("code_sha") == expected_code
            and ident.get("mode") == "local_candidate_readonly"
            and ident.get("realtime") is False
            and instant(ident["as_of"]) == instant(candidate.as_of),
            "PREVIEW_IDENTITY_MISMATCH",
        )
        if report is web:
            need(
                ident.get("candidate_origin") == candidate.api_origin,
                "CANDIDATE_ORIGIN_MISMATCH",
            )
        cap = report["capabilities"]
        version = cap.get("schema_version")
        need(
            version in CAPABILITIES
            and cap.get("release_stage") == CAPABILITIES[version],
            "UNKNOWN_NATIVE_CAPABILITY",
        )
        products = cap.get("intraday_products")
        # v25's native RB-only shape has no plural product list.
        need(
            products == [candidate.product]
            or version == "newow_product_capabilities_v25"
            and candidate.product == "rb"
            and products is None,
            "PREVIEW_PRODUCT_SCOPE_MISMATCH",
        )
        need(
            cap.get("open_frequencies") == [*FREQUENCIES, "1d", "1w"],
            "PREVIEW_FREQUENCY_SCOPE_MISMATCH",
        )
        caps.append(cap)
    need(caps[0] == caps[1], "API_WEB_CAPABILITIES_DIFFER")
    return candidate.proof(
        capability_schema=caps[0]["schema_version"],
        release_stage=caps[0]["release_stage"],
    )


def validate_assets(candidate: Candidate, report: dict) -> dict:
    need(
        report.get("status") == "PASS"
        and report.get("code_sha") == candidate.code_sha
        and instant(report["as_of"]) == instant(candidate.as_of)
        and report.get("product", candidate.product) == candidate.product
        and report.get("readonly") is True
        and report.get("writes") == 0
        and report.get("provider_calls") == 0,
        "ASSET_REPORT_IDENTITY",
    )
    rows = report["rows"]
    need(
        len(rows) == 4 and {r["frequency"] for r in rows} == set(FREQUENCIES),
        "ASSET_FREQUENCY_MATRIX",
    )
    count = 0
    for row in rows:
        need(
            row.get("prefix_status") == "INPUT_PREFIX_VERIFIED"
            and row.get("owners")
            and all(
                o.get("status") == "DATA_READY"
                and isinstance(o.get("contract"), str)
                and re.fullmatch(
                    re.escape(candidate.product.upper()) + r"\d{3,4}", o["contract"]
                )
                is not None
                and type(o.get("actual_bar_count")) is int
                and o["actual_bar_count"] > 0
                and type(o.get("expected_bar_count")) is int
                and o.get("actual_bar_count") == o.get("expected_bar_count")
                and o.get("no_trade_bar_count") == 0
                for o in row["owners"]
            ),
            "DATA_NOT_READY",
        )
        need(
            len({o["contract"] for o in row["owners"]}) == len(row["owners"]),
            "OWNER_DUPLICATE",
        )
        streams = row["streams"]
        need(
            len(streams) == 3
            and {s["strategy"] for s in streams}
            == {"trend", "oscillation", "dual_fusion"},
            "ASSET_STRATEGY_MATRIX",
        )
        for item in streams:
            s = item["stream"]
            summary = item["summary"]
            need(
                s.get("enabled") is False
                and s.get("activation_generation") == 0
                and summary.get("status") == "READY",
                "DISABLED_READY_REQUIRED",
            )
            need(
                s.get("product") == candidate.product
                and s.get("frequency") == row["frequency"]
                and s.get("strategy_code") == "newow_" + item["strategy"],
                "ASSET_PRODUCT_MISMATCH",
            )
            need(
                isinstance(s.get("active_revision_id"), str)
                and bool(s["active_revision_id"])
                and s.get("active_revision_id") == summary.get("revision_id")
                and s.get("latest_seq") == summary.get("seq")
                and isinstance(s.get("latest_seq"), int)
                and s["latest_seq"] > 0,
                "ASSET_REVISION_MISMATCH",
            )
            count += 1
    return candidate.proof(
        count=count, source_manifests_still_require_independent_review=True
    )


def legacy_identities(candidate: Candidate) -> dict:
    candidate.frozen_check()
    adapters = import_module("guiyi_quant.newow.product_adapters")
    fusion = import_module("guiyi_quant.newow.fusion_reference")
    contracts = import_module("guiyi_quant.newow.product_contracts")
    root = Path(candidate.worktree).resolve()
    need(
        all(
            Path(inspect.getfile(m)).resolve().is_relative_to(root)
            for m in (adapters, fusion, contracts)
        ),
        "FROZEN_IMPORT_REQUIRED",
    )
    rows = {}
    for frequency in ("1d", "1w"):
        bases = [
            adapters.build_product_identity(
                candidate.product,
                contracts.ProductStrategy(s),
                contracts.ProductFrequency(frequency),
            )
            for s in ("trend", "oscillation")
        ]
        need(
            all(b.product == candidate.product for b in bases),
            "NATIVE_LEGACY_PRODUCT_MISMATCH",
        )
        rows[frequency] = dict(
            base_identities={
                strategy: dict(
                    profile_id=base.profile_id,
                    formula_versions=list(base.formula_versions),
                )
                for strategy, base in zip(("trend", "oscillation"), bases)
            },
            source_profiles=[b.profile_id for b in bases],
            source_formula_versions=list(
                bases[0].formula_versions + bases[1].formula_versions
            ),
            reference_model_version=fusion.MODEL_VERSION,
        )
    return candidate.proof(
        authority="frozen native build_product_identity / fusion MODEL_VERSION",
        rows=rows,
        provider_calls=0,
        production_writes=0,
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("PREVIEW_REDIRECT_FORBIDDEN")


def read_preview(candidate: Candidate) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    reports = []
    for base in (candidate.api_origin, candidate.web_origin):
        report = {}
        for name, path in (
            ("identity", "/api/preview/identity"),
            ("capabilities", "/api/v1/market/newow/product-capabilities"),
        ):
            with opener.open(base + path, timeout=30) as response:
                need(response.status == 200, "PREVIEW_GET_FAILED")
                body = response.read(2_000_001)
                need(len(body) <= 2_000_000, "PREVIEW_RESPONSE_LIMIT")
                report[name] = json.loads(body)
        reports.append(report)
    return validate_preview(candidate, *reports)
