"""CorrDetector — Pearson correlation-based insight detector."""

from itertools import combinations

import numpy as np
import pandas as pd

from models.insight import Insight


class CorrDetector:
    """Detects strong Pearson correlations between numeric columns."""

    THRESHOLD: float = 0.6

    def detect(self, df: pd.DataFrame, columns: list[str]) -> list[Insight]:
        numeric_cols = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]
        if len(numeric_cols) < 2:
            return []

        corr_matrix = df[numeric_cols].corr()
        n_samples = len(df)
        insights: list[Insight] = []

        for a, b in combinations(numeric_cols, 2):
            r = corr_matrix.loc[a, b]
            if pd.isna(r):
                continue
            r = float(r)
            if abs(r) < self.THRESHOLD:
                continue
            direction = "正" if r > 0 else "负"
            insights.append(Insight(
                type="correlation",
                source="corr_detector",
                title=f"{a}与{b}高度{direction}相关 (r={r:.2f})",
                description="",
                score=abs(r),
                effect_size=abs(r),
                confidence=abs(r),
                columns=[a, b],
                payload={"n_samples": n_samples, "r": r, "col_a": a, "col_b": b},
            ))

        return insights
