"""InsightCluster — dedup + consensus amplification for detected insights.

Groups raw insights by type, resolves duplicates, and produces ClusteredInsight
objects with aggregated confidence scores.
"""

from collections import defaultdict
from models.insight import Insight, ClusteredInsight


class InsightCluster:
    """Clusters raw insights by type, amplifying consensus signals."""

    def cluster(self, raw_insights: list[Insight]) -> list[ClusteredInsight]:
        """Group raw insights by type, return clustered results.

        Insights of the same type (e.g. 'trend', 'correlation') are grouped
        together and their confidence scores are amplified when multiple
        detectors agree.
        """
        if not raw_insights:
            return []

        # Group by type
        groups: dict[str, list[Insight]] = defaultdict(list)
        for ins in raw_insights:
            groups[ins.type].append(ins)

        # Build ClusteredInsight per group
        clustered = []
        for _type, members in groups.items():
            ci = ClusteredInsight.from_insights(members)
            clustered.append(ci)

        return clustered
