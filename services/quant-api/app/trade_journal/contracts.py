"""Validated inputs for personal records and references to owning domains."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Product = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}$")]
Contract = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,3}[0-9]{1,2}(0[1-9]|1[0-2])$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=8000)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Identity = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
Direction = Literal["LONG", "SHORT"]
Period = Literal["day", "week"]
Source = Literal["SIMNOW", "SUBING_PAPER", "TQKQ_HISTORY", "NEWOW_REFERENCE", "RQALPHA_BACKTEST"]
Dimension = Literal["market", "entry", "management", "exit", "execution"]
Rating = Literal["MET", "PARTLY_MET", "MISSED", "UNASSESSED", "NOT_APPLICABLE"]
DIMENSIONS = ("market", "entry", "management", "exit", "execution")
OPENING_ACTIONS = frozenset({"OPEN", "ADD"})
EXECUTION_SOURCES = frozenset({"SIMNOW", "SUBING_PAPER", "TQKQ_HISTORY"})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(Input):
    expected_version: int = Field(ge=0)
    trading_day: date
    product: Product | None = None
    title: Title
    direction: Literal["LONG", "SHORT", "WATCH"] = "WATCH"
    frequencies: list[Literal["1m", "5m", "15m", "30m", "60m", "1d", "1w"]] = Field(default_factory=list, max_length=7)
    market: Note = ""
    entry: Note = ""
    stop: Note = ""
    target: Note = ""
    sizing: Note = ""
    scenarios: Note = ""


class CaseCreate(Input):
    trading_day: date
    product: Product
    contract: Contract
    direction: Direction
    title: Title
    plan_id: UUID | None = None
    plan_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_identity(self):
        if self.contract.rstrip("0123456789") != self.product:
            raise ValueError("合约必须属于所选品种")
        if (self.plan_id is None) != (self.plan_version is None):
            raise ValueError("请选择计划的确切版本")
        return self


class Assessment(Input):
    rating: Rating = "UNASSESSED"
    tags: list[Tag] = Field(default_factory=list, max_length=12)
    note: Note = ""


class Review(Input):
    dimensions: dict[Dimension, Assessment] = Field(default_factory=dict)
    takeaway: Note = ""
    next_action: Note = ""


class CaseUpdate(Input):
    expected_version: int = Field(ge=1)
    title: Title
    closed: bool
    review: Review | None = None


class ManualEvent(Input):
    kind: Literal["OPEN", "ADD", "REDUCE", "STOP", "TAKE_PROFIT", "CLOSE", "NOTE"]
    occurred_at: AwareDatetime
    trading_day: date
    note: Note = ""
    price: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    quantity: int | None = Field(default=None, gt=0, le=1_000_000)

    @model_validator(mode="after")
    def check_note(self):
        if self.kind == "NOTE" and (not self.note or self.price is not None or self.quantity is not None):
            raise ValueError("备注须包含文字，价格和手数应填写在操作记录中")
        return self


class SourceKey(Input):
    source: Source
    scope: Identity
    native_id: Identity
    trading_day: date


class Link(SourceKey):
    replaces_manual: UUID | None = None


class EventRemoval(Input):
    reason: Title


class Summary(Input):
    expected_version: int = Field(ge=0)
    environment: Note = ""
    observations: Note = ""
    missed: Note = ""
    execution: Note = ""
    next_action: Note = ""
    case_ids: list[UUID] = Field(default_factory=list, max_length=100)
