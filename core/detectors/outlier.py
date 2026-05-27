"""OutlierDetector — statistical outlier detection via IQR and Z-score."""

from typing import List

import numpy as np
import pandas as pd

from models.insight import Insight


class OutlierDetector:
    """Detects statistical outliers in numeric columns using IQR and Z-score methods."""

    def detect(self, df: pd.DataFrame, columns: list[str]) -> List[Insight]:
        insights: List[Insight] = []

        for col in columns:
            series = df[col].dropna()
            n = len(series)
            if n < 10:
                continue

            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            iqr_count = int(((series < lower) | (series > upper)).sum())

            mean, std = series.mean(), series.std(ddof=0)
            zscore_count = int((np.abs((series - mean) / std) > 3).sum()) if std > 0 else 0

            for count, method in [(iqr_count, "iqr"), (zscore_count, "zscore")]:
                if count == 0:
                    continue
                ratio = count / n
                insights.append(Insight(
                    type="outlier",
                    source="outlier_detector",
                    effect_size=ratio,
                    score=ratio,
                    confidence=min(0.9, ratio * 2),
                    title=f"{col}列存在{count}个异常值",
                    description=f"{col}列{method}方法检测到{count}个异常值（共{n}条数据）",
                    columns=[col],
                    payload={
                        "n_samples": n,
                        "outlier_count": count,
                        "outlier_ratio": ratio,
                        "method": method,
                    },
                ))

        return insights
