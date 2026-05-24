"""TrendDetector — 趋势检测器

检测数值列的线性趋势、拐点、均线交叉，生成趋势洞察。
"""

import numpy as np
import pandas as pd
from models.insight import Insight


class TrendDetector:
    """检测数值列的趋势：线性回归、一阶导数拐点、MA5/MA20交叉。"""
    MIN_R2: float = 0.15  # minimum R² to emit trend insight

    def detect(self, df: pd.DataFrame, columns: list[str]) -> list:
        """对指定的数值列执行趋势检测，返回 Insight 列表。

        Returns:
            list[Insight]: 趋势洞察，无显著趋势时返回空列表。
        """
        insights: list = []

        for col in columns:
            if col not in df.columns:
                continue

            series = df[col].dropna()
            if not np.issubdtype(series.dtype, np.number):
                continue

            n = len(series)
            if n < 2:
                continue  # 单行或全NaN

            y = series.values.astype(np.float64)
            if np.std(y) == 0:
                continue  # 常量列

            # 线性回归 y ~ x
            x = np.arange(n, dtype=np.float64)
            slope, intercept = np.polyfit(x, y, 1)
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = max(0.0, min(1 - ss_res / ss_tot, 1.0))

            # 拐点：一阶差分符号变化
            dy = np.diff(y)
            inflection_points = [
                int(i) for i in range(1, len(dy))
                if dy[i - 1] != 0 and dy[i] != 0
                and np.sign(dy[i - 1]) != np.sign(dy[i])
            ]

            # MA5 vs MA20 交叉
            ma_cross = None
            if n >= 20:
                ma5 = pd.Series(y).rolling(5).mean()
                ma20 = pd.Series(y).rolling(20).mean()
                if not pd.isna(ma5.iloc[-1]) and not pd.isna(ma20.iloc[-1]):
                    ma_cross = "MA5>MA20" if ma5.iloc[-1] > ma20.iloc[-1] else "MA5<MA20"

            # 斜率归一化效应量
            slope_normalized = slope / (np.std(y) / np.sqrt(n))

            direction = "上升" if slope > 0 else "下降"
            title = f"{col}呈{direction}趋势"
            desc = f"线性趋势斜率={slope:+.2f}/步, R²={r2:.2f}"

            # Skip columns with negligible trend
            if r2 < self.MIN_R2:
                continue

            insights.append(Insight(
                type="trend",
                source="trend_detector",
                title=title,
                description=desc,
                effect_size=abs(slope_normalized),
                score=r2,
                confidence=r2,
                columns=[col],
                payload={
                    "n_samples": n,
                    "slope": float(slope),
                    "r2": r2,
                    "inflection_points": inflection_points,
                    "ma_cross": ma_cross,
                },
            ))

        return insights
