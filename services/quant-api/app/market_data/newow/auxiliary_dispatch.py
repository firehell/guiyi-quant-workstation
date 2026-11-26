"""Dispatch Newow display calculations using the Quant Core feature contract."""

from datetime import datetime

from guiyi_quant.compute.owned import owned_indicator
from guiyi_quant.newow.product_auxiliary import AuxiliaryLayer
from guiyi_quant.newow.product_contracts import ProductBar, ProductIdentity


def calculate_auxiliary_component(
    identity: ProductIdentity,
    bars: tuple[ProductBar, ...],
    component: str,
    *,
    as_of: datetime,
) -> AuxiliaryLayer[object]:
    if not isinstance(identity, ProductIdentity):
        raise ValueError("NEWOW_AUXILIARY_INVALID_INPUT")
    definition = owned_indicator(f"newow.{component}", frequency=identity.frequency.value, use="web")
    if definition.calculate is None:
        raise ValueError("NEWOW_AUXILIARY_CALCULATOR_MISSING")
    result = definition.calculate(identity, bars, as_of=as_of)
    if (
        not isinstance(result, AuxiliaryLayer)
        or result.name != component
        or result.formula_version != definition.formula_version
        or result.repainting != definition.repainting
        or result.formal_signal_eligible
    ):
        raise ValueError("NEWOW_AUXILIARY_REGISTRY_MISMATCH")
    return result
