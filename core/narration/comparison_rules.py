"""Comparison rules — deterministic peak detection and group comparison.

Returns structured results (not natural language strings).
Entity ID mapping is the caller's responsibility (ChartFactsExtractor).
"""

from __future__ import annotations
from typing import Any, NamedTuple

import pandas as pd


def find_peak(x_values: list[Any], y_values: list[float]) -> tuple[Any, float] | None:
    """Find the peak (max y) point. Returns (x_value, y_value) or None.

    Returns raw x_value — caller maps to entity_id via EntityRegistry.
    """
    if not x_values or not y_values or len(x_values) != len(y_values):
        return None
    max_idx = max(range(len(y_values)), key=lambda i: y_values[i])
    return (x_values[max_idx], y_values[max_idx])


class GroupComparison(NamedTuple):
    """Structured output of compare_groups — not natural language."""

    a_label: str           # raw label for group A
    b_label: str           # raw label for group B
    a_mean: float
    b_mean: float
    ratio: float           # a_mean / b_mean
    direction: str         # "higher" | "lower"


def compare_groups(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    groups: list[str],
) -> GroupComparison | None:
    """Compare mean of value_col between exactly 2 groups.

    Returns structured GroupComparison or None.
    No natural language — entity mapping is the caller's job.
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
    direction = "higher" if ratio >= 1 else "lower"

    return GroupComparison(
        a_label=a_name,
        b_label=b_name,
        a_mean=float(a_mean),
        b_mean=float(b_mean),
        ratio=float(ratio) if direction == "higher" else float(1 / ratio),
        direction=direction,
    )
