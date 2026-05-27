"""Distribution detection for numeric columns — deterministic."""

from __future__ import annotations
import math
from typing import Any


def detect_distribution(values: list[float]) -> str | None:
    """Classify distribution shape for a numeric column.

    Returns: "normal" | "right_skewed" | "left_skewed" | "uniform" | None (insufficient data)
    """
    if not values or len(values) < 4:
        return None

    n = len(values)
    mean = sum(values) / n

    # Variance
    variance = sum((x - mean) ** 2 for x in values) / n
    if variance == 0:
        return None  # constant column

    # Skewness (Pearson's moment coefficient)
    std = math.sqrt(variance)
    skew = sum(((x - mean) / std) ** 3 for x in values) / n

    # Kurtosis
    kurt = sum(((x - mean) / std) ** 4 for x in values) / n

    if skew > 0.5:
        return "right_skewed"
    elif skew < -0.5:
        return "left_skewed"
    elif kurt < 2.5:
        return "uniform"
    elif abs(skew) < 0.5 and 2.5 <= kurt <= 4.0:
        return "normal"
    else:
        return None  # ambiguous
