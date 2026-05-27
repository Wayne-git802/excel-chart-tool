"""SeasonDetector — detects seasonal patterns in time-series numeric columns."""

import numpy as np
import pandas as pd
from models.insight import Insight


class SeasonDetector:
    MIN_SAMPLES: int = 30
    MIN_ACF_PEAK: float = 0.3
    MAX_LAG: int = 20

    def detect(self, df: pd.DataFrame, columns: list[str]) -> list[Insight]:
        insights: list[Insight] = []
        numeric_cols = [
            c for c in columns
            if c in df.columns and np.issubdtype(df[c].dtype, np.number)
        ]

        for col in numeric_cols:
            series = df[col].dropna()
            n = len(series)
            if n < self.MIN_SAMPLES:
                continue

            std = series.std()
            if std == 0 or pd.isna(std):
                continue

            # ACF via np.correlate on standardized series
            x = (series - series.mean()) / std
            acf = np.correlate(x, x, mode="full")[n - 1:] / n

            # Find strongest peak at lags 2..MAX_LAG
            end = min(self.MAX_LAG + 1, len(acf))
            if end <= 2:
                continue
            acf_window = acf[2:end]
            peak_idx = int(np.argmax(acf_window))
            peak = float(acf_window[peak_idx])
            lag = peak_idx + 2

            if peak <= self.MIN_ACF_PEAK:
                continue

            title = f"{col}存在{lag}步周期 (ACF={peak:.2f})"
            description = f"列'{col}'检测到{lag}步自相关周期，自相关峰值={peak:.3f}"

            insights.append(Insight(
                type="seasonal",
                source="season_detector",
                title=title,
                description=description,
                effect_size=peak,
                score=peak,
                confidence=min(peak * 1.5, 0.95),
                columns=[col],
                payload={
                    "n_samples": n,
                    "period": lag,
                    "acf_peak": peak,
                    "lag": lag,
                },
            ))

        return insights
