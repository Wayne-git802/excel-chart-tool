"""Comparison rules — deterministic peak detection and group comparison."""

from __future__ import annotations
from typing import Any

import pandas as pd


def find_peak(x_values: list[Any], y_values: list[float]) -> tuple[Any, float] | None:
    """Find the peak (max y) point. Returns (x_value, y_value) or None."""
    if not x_values or not y_values or len(x_values) != len(y_values):
        return None
    max_idx = max(range(len(y_values)), key=lambda i: y_values[i])
    return (x_values[max_idx], y_values[max_idx])


def compare_groups(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    groups: list[str],
) -> str | None:
    """Compare mean of value_col between exactly 2 groups.

    Returns: "A比B高X倍" or None if not exactly 2 groups or data insufficient.
    """
    if len(groups) != 2:
        return None

    a_name, b_name = groups[0], groups[1]
    a_vals = df[df[group_col] == a_name][value_col]
    b_vals = df[df[group_col] == b_name][value_col]

    if len(a_vals) == 0 or len(b_vals) == 0:
        return None

    a_mean = a_vals.mean()
    b_mean = b_vals.mean()

    if b_mean == 0:
        return None

    ratio = a_mean / b_mean
    if ratio >= 1:
        return f"{a_name}比{b_name}高{ratio:.1f}倍"
    else:
        return f"{a_name}比{b_name}低{1/ratio:.1f}倍"
