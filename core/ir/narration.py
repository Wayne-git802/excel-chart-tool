"""Core IR — Narration / ChartFacts types."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChartFacts:
    """Deterministic facts extracted from chart result. LLM narrates from this only."""

    chart_type: str
    x_label: str
    y_labels: list[str] = field(default_factory=list)
    row_count: int = 0
    filter_description: str = "(全部数据)"

    # Computed facts — each has a precise algorithm defined in ChartFactsExtractor
    trend_direction: str | None = None  # "upward" | "downward" | "unclear" | None
    peak_point: tuple | None = None  # (x_value, y_value)
    comparison: str | None = None  # "A比B高3.7倍" | None
    stats: dict[str, dict] = field(default_factory=dict)  # {y_col: {mean, median, min, max}}
    decision_source: str = "fallback"

    def to_dict(self) -> dict:
        return {
            "chart_type": self.chart_type,
            "x_label": self.x_label,
            "y_labels": self.y_labels,
            "row_count": self.row_count,
            "filter_description": self.filter_description,
            "trend_direction": self.trend_direction,
            "peak_point": list(self.peak_point) if self.peak_point else None,
            "comparison": self.comparison,
            "stats": self.stats,
            "decision_source": self.decision_source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChartFacts":
        peak = d.get("peak_point")
        return cls(
            chart_type=d["chart_type"],
            x_label=d["x_label"],
            y_labels=d.get("y_labels", []),
            row_count=d.get("row_count", 0),
            filter_description=d.get("filter_description", "(全部数据)"),
            trend_direction=d.get("trend_direction"),
            peak_point=tuple(peak) if peak else None,
            comparison=d.get("comparison"),
            stats=d.get("stats", {}),
            decision_source=d.get("decision_source", "fallback"),
        )
