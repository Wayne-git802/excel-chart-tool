"""Operation IR — pure data structures, zero dependencies.

Phase 1: FilterOp, SortOp, LimitOp, ChartPatchOp.
All frozen dataclasses. No UI/rendering logic.

Design note: No Op base class inheritance — Python 3.11 dataclass
inheritance requires all child fields to have defaults if parent has any.
Standalone dataclasses are cleaner for this use case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Literal
import uuid


class OpClass(Enum):
    APPEND = auto()
    REPLACE = auto()


# ── FilterOp (APPEND) ────────────────────────

@dataclass(frozen=True)
class FilterOp:
    """
    Phase 1: column_range / value_match / expression.
    No row_slice (depends on sort order, Phase 2).
    """
    filter_type: Literal["column_range", "value_match", "expression"]
    column: str | None = None
    params: dict = field(default_factory=dict)
    op_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    op_version: int = 1
    op_class: OpClass = field(default=OpClass.APPEND, init=False)


# ── SortOp (REPLACE) ─────────────────────────

@dataclass(frozen=True)
class SortOp:
    column: str
    direction: Literal["asc", "desc"] = "desc"
    op_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    op_version: int = 1
    op_class: OpClass = field(default=OpClass.REPLACE, init=False)


# ── LimitOp (REPLACE) ────────────────────────

@dataclass(frozen=True)
class LimitOp:
    n: int
    op_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    op_version: int = 1
    op_class: OpClass = field(default=OpClass.REPLACE, init=False)


# ── ChartPatchOp (REPLACE) ───────────────────

@dataclass(frozen=True)
class ChartPatchOp:
    """
    User chart preference, NOT final chart.
    Final chart resolved dynamically by ChartResolver.
    """
    chart_type: str | None = None
    x_column: str | None = None
    y_columns: tuple[str, ...] | None = None
    title: str | None = None
    op_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    op_version: int = 1
    op_class: OpClass = field(default=OpClass.REPLACE, init=False)


# ── Union type ───────────────────────────────

Operation = FilterOp | SortOp | LimitOp | ChartPatchOp
