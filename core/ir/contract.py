"""Core IR — Contract / Decision types."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnalysisIntent:
    """Typed analysis intent extracted from user query by LLM."""

    type: str  # "trend" | "comparison" | "distribution" | "correlation" | "overview" | "UNKNOWN"
    confidence: float  # 0.0 ~ 1.0
    explicit_chart: str | None = None  # user-specified chart: "line" | "bar" | ...
    entities: dict[str, Any] = field(default_factory=dict)  # {"metrics": ["销售额"], "filter_hint": "只看张三"}

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "confidence": self.confidence,
            "explicit_chart": self.explicit_chart,
            "entities": self.entities,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisIntent":
        return cls(
            type=d["type"],
            confidence=d["confidence"],
            explicit_chart=d.get("explicit_chart"),
            entities=d.get("entities", {}),
        )


@dataclass(frozen=True)
class FilterCondition:
    """A single filter condition. Multiple conditions are AND-ed."""

    column: str  # canonical name (after validation)
    operator: str  # "in" | "eq" | "neq" | "gt" | "lt" | "gte" | "lte" | "between"
    value: Any  # scalar for eq/gt/lt, list for in, tuple for between

    def to_dict(self) -> dict:
        return {
            "column": self.column,
            "operator": self.operator,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FilterCondition":
        return cls(column=d["column"], operator=d["operator"], value=d["value"])


@dataclass(frozen=True)
class FilterSpec:
    """Structured row filter specification."""

    conditions: list[FilterCondition] = field(default_factory=list)
    persist: bool = False  # True → sticky (cross-turn), False → one-shot

    def is_empty(self) -> bool:
        return len(self.conditions) == 0

    def to_dict(self) -> dict:
        return {
            "conditions": [c.to_dict() for c in self.conditions],
            "persist": self.persist,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FilterSpec":
        return cls(
            conditions=[FilterCondition.from_dict(c) for c in d.get("conditions", [])],
            persist=d.get("persist", False),
        )


@dataclass(frozen=True)
class CapabilityResult:
    """Output of CapabilityGate check."""

    allowed: bool
    reason: str = ""  # empty if allowed


@dataclass(frozen=True)
class ChartDecision:
    """Deterministic chart decision from Contract engine."""

    chart_type: str  # "line" | "bar" | "scatter" | "histogram" | "pie" | "boxplot"
    x_column: str
    y_columns: list[str] = field(default_factory=list)
    title: str = ""
    decision_source: str = "fallback"  # "explicit_user" | "profile_rule" | "fallback"

    @classmethod
    def none(cls) -> "ChartDecision":
        """Sentinel: no valid chart possible."""
        return cls(chart_type="", x_column="", decision_source="none")

    def is_none(self) -> bool:
        return self.chart_type == "" and self.decision_source == "none"

    def to_dict(self) -> dict:
        return {
            "chart_type": self.chart_type,
            "x_column": self.x_column,
            "y_columns": self.y_columns,
            "title": self.title,
            "decision_source": self.decision_source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChartDecision":
        return cls(
            chart_type=d["chart_type"],
            x_column=d["x_column"],
            y_columns=d.get("y_columns", []),
            title=d.get("title", ""),
            decision_source=d.get("decision_source", "fallback"),
        )
