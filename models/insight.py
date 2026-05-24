from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Insight:
    type: str
    title: str
    description: str
    score: float = 0.0
    effect_size: float = 0.0
    confidence: float = 0.0
    chart_spec_hint: Optional[dict] = None
    columns: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    source: str = ""

    def __repr__(self) -> str:
        return (
            f"Insight(type={self.type!r}, title={self.title!r}, "
            f"score={self.score:.3f}, conf={self.confidence:.3f}, "
            f"source={self.source!r})"
        )

@dataclass
class ClusteredInsight:
    representative: Insight = field(default_factory=Insight)
    source_count: int = 0
    sources: list[str] = field(default_factory=list)
    confidence_aggregated: float = 0.0
    members: list[Insight] = field(default_factory=list)

    @classmethod
    def from_insights(cls, insights: list[Insight]) -> "ClusteredInsight":
        if not insights:
            return cls()
        representative = max(insights, key=lambda i: i.confidence)
        source_count = len(insights)
        confidence_aggregated = representative.confidence * (1 + 0.15 * source_count)
        sources = list(dict.fromkeys(i.source for i in insights if i.source))
        return cls(
            representative=representative,
            source_count=source_count,
            sources=sources,
            confidence_aggregated=confidence_aggregated,
            members=insights,
        )

    def __repr__(self) -> str:
        return (
            f"ClusteredInsight(rep={self.representative.title!r}, "
            f"sources={self.sources}, n={self.source_count}, "
            f"conf_agg={self.confidence_aggregated:.3f})"
        )
