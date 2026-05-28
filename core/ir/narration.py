"""Core IR — Narration / ChartFacts types.

ChartFacts: deterministic facts, no entity labels — only entity IDs.
ComparisonFact: structured comparison, not natural language string.
NarrationContext: runtime context bundling registry + facts.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from core.ir.entity import EntityRegistry


@dataclass(frozen=True)
class ComparisonFact:
    """Structured comparison — IR, not natural language string."""

    left_entity_id: str     # "e_001"
    right_entity_id: str    # "e_002"
    metric: str             # "销售额"
    ratio: float            # 3.7
    direction: str          # "higher" | "lower"

    def __post_init__(self):
        if self.direction not in ("higher", "lower"):
            raise ValueError(f"direction must be 'higher' or 'lower', got {self.direction!r}")

    @property
    def left_value(self) -> float:
        """Reconstruct absolute values are NOT stored — only ratio is IR."""
        raise NotImplementedError("ComparisonFact stores ratio only, not absolute values")

    def to_dict(self) -> dict:
        return {
            "left_entity_id": self.left_entity_id,
            "right_entity_id": self.right_entity_id,
            "metric": self.metric,
            "ratio": self.ratio,
            "direction": self.direction,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComparisonFact":
        return cls(
            left_entity_id=d["left_entity_id"],
            right_entity_id=d["right_entity_id"],
            metric=d["metric"],
            ratio=d["ratio"],
            direction=d["direction"],
        )


@dataclass(frozen=True)
class ChartFacts:
    """Deterministic facts extracted from chart result.

    Uses entity IDs only — no raw labels. Entity labels live in EntityRegistry.
    """

    chart_type: str
    x_label: str
    y_labels: list[str] = field(default_factory=list)
    row_count: int = 0
    filter_description: str = "(全部数据)"

    # Entity references — symbolic only, no labels
    entity_ids_used: list[str] = field(default_factory=list)

    # Computed facts
    trend_direction: str | None = None          # "upward" | "downward" | "unclear" | None
    peak_entity_id: str | None = None           # entity_id of peak, not raw label
    peak_value: float | None = None             # the y-value at peak
    comparisons: list[ComparisonFact] = field(default_factory=list)  # structured, not string
    stats: dict[str, dict] = field(default_factory=dict)
    decision_source: str = "fallback"

    def to_dict(self) -> dict:
        return {
            "chart_type": self.chart_type,
            "x_label": self.x_label,
            "y_labels": self.y_labels,
            "row_count": self.row_count,
            "filter_description": self.filter_description,
            "entity_ids_used": self.entity_ids_used,
            "trend_direction": self.trend_direction,
            "peak_entity_id": self.peak_entity_id,
            "peak_value": self.peak_value,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "stats": self.stats,
            "decision_source": self.decision_source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChartFacts":
        return cls(
            chart_type=d["chart_type"],
            x_label=d["x_label"],
            y_labels=d.get("y_labels", []),
            row_count=d.get("row_count", 0),
            filter_description=d.get("filter_description", "(全部数据)"),
            entity_ids_used=d.get("entity_ids_used", []),
            trend_direction=d.get("trend_direction"),
            peak_entity_id=d.get("peak_entity_id"),
            peak_value=d.get("peak_value"),
            comparisons=[ComparisonFact.from_dict(c) for c in d.get("comparisons", [])],
            stats=d.get("stats", {}),
            decision_source=d.get("decision_source", "fallback"),
        )


@dataclass(frozen=True)
class NarrationContext:
    """Runtime context for narration — bundles registry and facts together.

    Registry is session-scoped; facts are per-chart. Keeping them separate
    avoids: (1) duplicating registry in every facts object, (2) serialization
    bloat, (3) replay inconsistency, (4) cache-unfriendly dedupe.
    """

    registry: EntityRegistry
    facts: ChartFacts
