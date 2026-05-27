"""Trend detection — deterministic linear regression for trend_direction."""

from __future__ import annotations


def detect_trend(values: list[float]) -> str | None:
    """Simple linear regression slope → trend direction.

    Args:
        values: y-values in order.

    Returns:
        "upward" | "downward" | "unclear" | None (insufficient data)
    """
    if not values or len(values) < 3:
        return None

    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n

    # Slope = Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)
    numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return None

    slope = numerator / denominator

    # R²
    y_pred = [y_mean + slope * (i - x_mean) for i in range(n)]
    ss_res = sum((values[i] - y_pred[i]) ** 2 for i in range(n))
    ss_tot = sum((values[i] - y_mean) ** 2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

    if r_squared < 0.3:
        return "unclear"

    if slope > 0:
        return "upward"
    elif slope < 0:
        return "downward"
    else:
        return None
