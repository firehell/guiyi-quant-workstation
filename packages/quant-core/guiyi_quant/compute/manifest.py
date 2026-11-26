"""Read-only installed package identity for consumer compatibility checks."""

from importlib.metadata import version
import json

from . import REGISTRY, RESULT_SCHEMA_VERSION, STATE_SCHEMA_VERSION
from .contracts import hash_parameters
from .generic import TALIB_BACKEND_VERSION
from .owned import OWNED_DEFINITIONS
from .registry import FeatureRequest


PACKAGE_NAME = "guiyi-quant-core"
COMPUTE_CONTRACT_VERSION = "guiyi_quant_compute_v1"


def require_contract(
    *, compute: str, result: str, state: str | None = None,
) -> None:
    if (compute, result) != (COMPUTE_CONTRACT_VERSION, RESULT_SCHEMA_VERSION) or (
        state is not None and state != STATE_SCHEMA_VERSION
    ):
        raise ValueError("QUANT_CORE_CONTRACT_INCOMPATIBLE")


def manifest() -> dict:
    features = {
        feature_id: {
            "category": definition.category,
            "formula_version": definition.formula_version,
            "backend_version": definition.backend_version,
            "output_schema_version": definition.output_schema_version,
            "outputs": definition.outputs,
            "allowed_uses": sorted(definition.allowed_uses),
            "modes": sorted(definition.modes),
            "repainting": definition.repainting,
            "supported_frequencies": sorted(definition.supported_frequencies),
            "input_fields": definition.input_fields,
            "default_parameter_hash": (
                hash_parameters(definition.resolve(FeatureRequest(feature_id)))
                if all(item.default is not None for item in definition.parameters.values()) else None
            ),
        }
        for feature_id, definition in REGISTRY.definitions.items()
    }
    features.update({
        feature_id: {
            "category": "owned", "formula_version": definition.formula_version,
            "output_schema_version": definition.output_schema_version,
            "outputs": definition.outputs, "allowed_uses": sorted(definition.allowed_uses),
            "repainting": definition.repainting,
            "supported_frequencies": sorted(definition.supported_frequencies),
            "input_schema_version": definition.input_schema_version,
            **({"optional_outputs": definition.optional_outputs} if definition.optional_outputs else {}),
        }
        for feature_id, definition in OWNED_DEFINITIONS.items()
    })
    return {
        "name": PACKAGE_NAME, "version": version(PACKAGE_NAME),
        "compute_contract_version": COMPUTE_CONTRACT_VERSION,
        "result_schema_version": RESULT_SCHEMA_VERSION, "state_schema_version": STATE_SCHEMA_VERSION,
        "dependencies": {"ta-lib": TALIB_BACKEND_VERSION.removeprefix("ta-lib:"), "numpy": version("numpy")},
        "features": features,
    }


if __name__ == "__main__":
    print(json.dumps(manifest(), sort_keys=True))
