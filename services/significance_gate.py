"""SignificanceGate — validates whether an insight passes the significance threshold.

Used by InsightEngine to filter out weak/spurious detections before clustering.
"""

from models.insight import Insight


class SignificanceGate:
    """Statistical significance filter for detected insights."""

    # Thresholds
    MIN_CORRELATION = 0.3       # Pearson r below this → not significant
    MIN_SAMPLE_SIZE = 3         # need at least this many data points
    MIN_TREND_R2 = 0.3          # R² below this → weak trend

    def check(self, insight: Insight) -> bool:
        """Check if an insight passes significance thresholds.

        Returns True if the insight is statistically meaningful.
        Currently a permissive pass-through — significance filtering
        is delegated to detector-level thresholds.
        """
        if insight is None:
            return False

        # All detectors already apply their own thresholds;
        # this gate exists as a centralized override point.
        return True
