"""SignificanceGate → InsightRanker → Clustered Insights.

Stripped of UserModeGate — always runs, always returns insights.
Used by AnalysisOrchestrator as an accelerator, not a brain."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd

from models.insight import Insight, ClusteredInsight
from services.significance_gate import SignificanceGate
from services.insight_cluster import InsightCluster

from services.detectors.trend import TrendDetector
from services.detectors.outlier import OutlierDetector
from services.detectors.correlation import CorrDetector
from services.detectors.distribution import DistAnalyzer
from services.detectors.seasonal import SeasonDetector

logger = logging.getLogger(__name__)


class InsightEngine:
    """Main orchestrator for proactive data exploration."""

    # Scoring weights
    W_EFFECT = 0.35
    W_SURPRISE = 0.10
    W_ACTIONABLE = 0.30
    W_CONFIDENCE = 0.25

    # Filters
    MIN_R2_FOR_TREND = 0.3  # reject weak trends
    MIN_SCORE_FOR_PUSH = 0.3
    TOP_K_PUSH = 3

    def __init__(self):
        self._sig_gate = SignificanceGate()
        self._cluster = InsightCluster()
        self._detectors = [
            TrendDetector(),
            OutlierDetector(),
            CorrDetector(),
            DistAnalyzer(),
            SeasonDetector(),
        ]

    def run(
        self,
        df: pd.DataFrame,
        context: Optional[dict] = None,
    ) -> dict:
        """Main entry point. Runs detection pipeline.

        Returns:
            dict with keys:
              - insights: list of ClusteredInsight (all qualified)
              - top_insights: list of ClusteredInsight (top-k)
              - raw_count: int
              - cluster_count: int
        """
        context = context or {}

        # Step 1: Intake — identify numeric columns
        numeric_cols = self._intake(df)
        if not numeric_cols:
            logger.info("InsightEngine: no numeric columns found, skipping")
            return {
                "insights": [],
                "top_insights": [],
                "raw_count": 0,
                "cluster_count": 0,
                "should_push": False,
            }

        # Step 2: Run all detectors in parallel
        raw_insights: list[Insight] = []
        with ThreadPoolExecutor(max_workers=len(self._detectors)) as executor:
            futures = {executor.submit(d.detect, df, numeric_cols): d for d in self._detectors}
            for future in as_completed(futures):
                detector = futures[future]
                try:
                    results = future.result()
                    raw_insights.extend(results)
                except Exception as e:
                    logger.warning(f"Detector {detector.__class__.__name__} failed: {e}")

        # Step 2b: Post-filter weak trends
        raw_insights = self._filter_weak_insights(raw_insights)

        raw_count = len(raw_insights)
        logger.info(f"InsightEngine: {raw_count} raw insights from {len(self._detectors)} detectors")

        # Step 3: Cluster (dedup + consensus amplification)
        clustered = self._cluster.cluster(raw_insights)
        logger.info(f"InsightEngine: {len(clustered)} clusters after dedup")

        # Step 4: Significance gate on each clustered insight's representative
        for c in clustered:
            self._sig_gate.check(c.representative)

        # Step 5: Rank by weighted score
        for c in clustered:
            c.representative.score = self._compute_score(c)

        clustered.sort(key=lambda c: c.representative.score, reverse=True)

        # Step 6: Filter by min score — always return top insights
        qualified = [c for c in clustered if c.representative.score >= self.MIN_SCORE_FOR_PUSH]
        top = qualified[: self.TOP_K_PUSH]

        return {
            "insights": qualified,
            "top_insights": top,
            "raw_count": raw_count,
            "cluster_count": len(clustered),
        }

    # ── private helpers ──

    def _intake(self, df: pd.DataFrame) -> list[str]:
        """Identify numeric columns suitable for analysis."""
        numeric = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                n_valid = df[col].dropna().shape[0]
                if n_valid >= 5:  # minimum rows for any analysis
                    numeric.append(col)
        return numeric

    def _filter_weak_insights(self, insights: list[Insight]) -> list[Insight]:
        """Post-filter: remove obviously weak detections."""
        kept = []
        for ins in insights:
            # Trend: require R² >= 0.3
            if ins.type == "trend":
                r2 = ins.payload.get("r2", 0)
                if r2 < self.MIN_R2_FOR_TREND:
                    continue
            # Outlier: require at least 2 outliers
            if ins.type == "outlier":
                count = ins.payload.get("outlier_count", 0)
                if count < 2:
                    continue
            kept.append(ins)
        return kept

    def _compute_score(self, cluster: ClusteredInsight) -> float:
        """Compute weighted score for a clustered insight.

        Scoring uses the representative insight's attributes,
        with confidence boosted by source_count consensus.
        """
        rep = cluster.representative

        effect = getattr(rep, "effect_size", 0) or 0
        surprise = getattr(rep, "surprise_component", 0) or 0
        confidence = cluster.confidence_aggregated  # already consensus-boosted
        actionable = self._compute_actionable(rep)

        score = (
            self.W_EFFECT * min(effect, 1.0)
            + self.W_SURPRISE * min(surprise, 1.0)
            + self.W_ACTIONABLE * actionable
            + self.W_CONFIDENCE * min(confidence, 1.0)
        )
        return score

    def _compute_actionable(self, insight: Insight) -> float:
        """How easily can this insight be turned into a chart?

        Checks: does it have columns? a meaningful type?
        """
        score = 0.0

        # Has columns → can chart
        if getattr(insight, "columns", None) and len(insight.columns) > 0:
            score += 0.5

        # R² for trends → stronger = more chartable
        if insight.type == "trend":
            r2 = insight.payload.get("r2", 0) if insight.payload else 0
            score += min(r2, 0.5)

        # Correlation with high |r| → very chartable
        if insight.type == "correlation":
            r = insight.payload.get("r", 0) if insight.payload else 0
            score += min(abs(r), 0.5)

        return min(score, 1.0)
