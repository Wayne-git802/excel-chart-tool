import numpy as np
import pandas as pd

from models.insight import Insight


class DistAnalyzer:
    """Detect interesting distribution properties in numeric columns."""

    def detect(self, df: pd.DataFrame, columns: list[str]) -> list[Insight]:
        insights: list[Insight] = []

        for col in columns:
            if col not in df.columns:
                continue
            series = df[col].dropna()
            n = len(series)
            if n < 20 or not np.issubdtype(series.dtype, np.number):
                continue

            s = float(series.skew())
            k = float(series.kurtosis())
            vc = series.value_counts()
            top3 = vc.head(3).sum() / n

            if abs(s) > 1:
                direction = "右偏" if s > 0 else "左偏"
                insights.append(Insight(
                    type="distribution", source="dist_analyzer",
                    title=f"{col}分布{direction} (skew={s:+.1f})",
                    description=f"列 '{col}' 偏度={s:.2f}，呈{direction}分布，n={n}",
                    effect_size=abs(s) / 3, score=abs(s) / 3,
                    confidence=0.6, columns=[col],
                    payload={"property": "skew", "skew": s, "excess_kurtosis": k, "n_samples": n},
                ))

            if k > 0:  # excess kurtosis > 0 → heavier tails than normal
                insights.append(Insight(
                    type="distribution", source="dist_analyzer",
                    title=f"{col}肥尾分布 (excess kurt={k:.1f})",
                    description=f"列 '{col}' 超值峰度={k:.2f}，分布尾部比正态分布更厚，n={n}",
                    effect_size=min(abs(k) / 5, 1.0), score=min(abs(k) / 5, 1.0),
                    confidence=0.6, columns=[col],
                    payload={"property": "kurtosis", "skew": s, "excess_kurtosis": k, "n_samples": n},
                ))

            if top3 > 0.5:
                insights.append(Insight(
                    type="distribution", source="dist_analyzer",
                    title=f"{col}高度集中 (top3={top3:.1%})",
                    description=f"列 '{col}' Top-3 值占比 {top3:.1%}，n={n}",
                    effect_size=top3, score=top3, confidence=0.6, columns=[col],
                    payload={"property": "concentration", "skew": s, "excess_kurtosis": k, "n_samples": n},
                ))

        return insights
