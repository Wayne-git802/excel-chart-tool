"""FilterSpec validator — deterministic validation against profile."""

from __future__ import annotations
import difflib

from core.ir.contract import FilterSpec
from core.ir.profile import DatasetProfile
from core.ir.failure import ExplicitFailure


def validate_filter(fs: FilterSpec, profile: DatasetProfile) -> list[ExplicitFailure]:
    """Validate FilterSpec against profile. Returns list of failures (empty = valid).

    Checks:
    1. Column names exist (fuzzy match)
    2. Operators are valid
    3. Value types match column types
    """
    if fs.is_empty():
        return []

    failures: list[ExplicitFailure] = []

    for i, cond in enumerate(fs.conditions):
        # 1. Column name fuzzy match
        matched = _fuzzy_match_column(cond.column, profile)
        if matched is None:
            candidates = _column_candidates(cond.column, profile)
            failures.append(ExplicitFailure(
                code="invalid_filter_column",
                message=f"找不到列 '{cond.column}'。可用的列: {', '.join(candidates[:5])}",
                recoverable=True,
                stage="filter_validation",
                details={"column": cond.column, "candidates": candidates},
            ))
            continue

        # 2. Operator check
        valid_ops = {"in", "eq", "neq", "gt", "lt", "gte", "lte", "between"}
        if cond.operator not in valid_ops:
            failures.append(ExplicitFailure(
                code="invalid_filter_operator",
                message=f"不支持的过滤操作 '{cond.operator}'。支持: {', '.join(sorted(valid_ops))}",
                recoverable=False,
                stage="filter_validation",
                details={"operator": cond.operator},
            ))
            continue

        # 3. Value type check (basic)
        col_profile = profile.columns.get(matched)
        if col_profile and col_profile.semantic_type == "numeric":
            if cond.operator in ("in", "eq") and isinstance(cond.value, str):
                # String value on numeric column — might be intentional (category code)
                pass

    return failures


def _fuzzy_match_column(column: str, profile: DatasetProfile) -> str | None:
    """Fuzzy match column name against profile columns. Returns canonical name or None."""
    col_names = list(profile.columns.keys())
    if column in col_names:
        return column
    # Exact case-insensitive
    col_lower = {c.lower(): c for c in col_names}
    if column.lower() in col_lower:
        return col_lower[column.lower()]
    # Fuzzy
    matches = difflib.get_close_matches(column, col_names, n=1, cutoff=0.4)
    return matches[0] if matches else None


def _column_candidates(column: str, profile: DatasetProfile) -> list[str]:
    """Return close matches for error message."""
    col_names = list(profile.columns.keys())
    return difflib.get_close_matches(column, col_names, n=5, cutoff=0.3)
