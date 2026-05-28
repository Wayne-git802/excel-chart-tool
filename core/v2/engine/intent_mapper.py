"""IntentMapper — deterministic StructuredIntent → Operation conversion.

LLM extracts raw parameters. This module resolves them against actual columns.
No inference, no guessing — only precise lookups against column profile.
"""

from __future__ import annotations

from ..ir.operations import (
    FilterOp, SortOp, LimitOp, ChartPatchOp, Operation,
)
from ..ir.column_info import ColumnInfo
from .intent_models import StructuredIntent


def map_intent_to_op(
    intent: StructuredIntent,
    columns: list[ColumnInfo],
) -> Operation | None:
    """
    Deterministic mapping from intent to operation.

    Rules:
      1. raw_column: fuzzy-match against column names
      2. raw_constraint: parse into filter params
      3. raw_direction: map to asc/desc
      4. raw_n: parse to int

    Returns None if mapping fails (caller should return error to user).
    """

    if intent.action == "unknown":
        return None

    if intent.action == "filter":
        return _map_filter(intent, columns)

    if intent.action == "sort":
        return _map_sort(intent, columns)

    if intent.action == "limit":
        return _map_limit(intent)

    if intent.action == "chart":
        return _map_chart(intent, columns)

    return None


# ── Helpers ──────────────────────────────────────────────

def _find_column(hint: str, columns: list[ColumnInfo]) -> str | None:
    """Fuzzy-match a user column hint to actual column names."""
    if not hint:
        return None
    hint_lower = hint.strip().lower()
    # Exact match
    for c in columns:
        if c.name.lower() == hint_lower:
            return c.name
    # Substring match
    for c in columns:
        if hint_lower in c.name.lower() or c.name.lower() in hint_lower:
            return c.name
    return None


def _find_numeric_column(columns: list[ColumnInfo]) -> str | None:
    """Find the first numeric column (fallback for sort/chart Y axis)."""
    for c in columns:
        if c.dtype_cn in ("整数", "小数"):
            return c.name
    return None


def _find_text_column(columns: list[ColumnInfo]) -> str | None:
    """Find the first text/category column."""
    for c in columns:
        if c.dtype_cn in ("文本",):
            return c.name
    return None


def _parse_sort_direction(raw: str) -> str:
    """Map user direction words to asc/desc."""
    r = raw.strip().lower()
    desc_words = ("降序", "从高到低", "从大到小", "desc", "大的在前",
                  "倒序", "递减", "高到低", "大到小")
    asc_words = ("升序", "从低到高", "从小到大", "asc", "小的在前",
                 "正序", "递增", "低到高", "小到大")
    for w in desc_words:
        if w in r:
            return "desc"
    for w in asc_words:
        if w in r:
            return "asc"
    return "desc"  # default


def _parse_int(raw: str) -> int | None:
    """Extract first integer from raw text."""
    import re
    nums = re.findall(r'\d+', raw)
    return int(nums[0]) if nums else None


def _parse_range_params(raw_constraint: str, column_name: str,
                        column: ColumnInfo) -> dict | None:
    """
    Parse constraint string into filter params.

    Examples:
      "2020到2025" → {min: 2020, max: 2025}
      "大于100" → {op: ">", value: 100}
      "包含手机" → {value: "手机"}
      "2020年之后" → {min: 2020}
    """
    import re
    raw = raw_constraint.strip()

    # Range: "2020-2025", "2010到2015", "2010~2015"
    nums = re.findall(r'\d+\.?\d*', raw)
    if len(nums) == 2 and any(sep in raw for sep in ('-', '到', '~', '–', '—')):
        try:
            v1 = float(nums[0]) if '.' in nums[0] else int(nums[0])
            v2 = float(nums[1]) if '.' in nums[1] else int(nums[1])
            mn, mx = min(v1, v2), max(v1, v2)
            return {"min": mn, "max": mx}
        except (ValueError, TypeError):
            pass

    # Single-sided: "2020年之后", "大于100", ">= 50"
    # "之后"/"以上"/"大于"/">=" → min
    if any(w in raw for w in ('之后', '以上', '大于', '>=', '不小于', '高于',
                                '超过', '不低于')):
        if nums:
            return {"min": _to_number(nums[0], column)}

    # "之前"/"以下"/"小于"/"<=" → max
    if any(w in raw for w in ('之前', '以下', '小于', '<=', '不大于', '低于',
                                '不到', '不高于')):
        if nums:
            return {"max": _to_number(nums[0], column)}

    # Comparison: "> 100", "< 50", "== 0"
    cmp_map = {">": ">", "<": "<", ">=": ">=", "<=": "<=",
               "==": "==", "!=": "!="}
    for symbol, op_str in cmp_map.items():
        if symbol in raw and nums:
            return {"op": op_str, "value": _to_number(nums[0], column)}

    # Text match: "包含手机", "是华东"
    if any(w in raw for w in ('包含', '含有', '含', '是', '有')):
        # Extract text after match word
        for word in ('包含', '含有', '含', '是', '有'):
            if word in raw:
                val = raw.split(word, 1)[-1].strip().strip('"\'""').strip()
                if val:
                    return {"value": val}
        # If no specific text, use whole constraint as value
        return {"value": raw}

    return None


def _to_number(s: str, column: ColumnInfo) -> int | float:
    """Convert string to int or float based on column dtype."""
    try:
        if column.dtype_cn == "整数":
            return int(float(s))
        return float(s)
    except (ValueError, TypeError):
        return float(s)


# ── Action mappers ────────────────────────────────────────

def _map_filter(intent: StructuredIntent,
                columns: list[ColumnInfo]) -> Operation | None:
    col_name = _find_column(intent.raw_column, columns)
    if not col_name:
        return None

    col_info = next((c for c in columns if c.name == col_name), None)
    if not col_info:
        return None

    params = _parse_range_params(intent.raw_constraint, col_name, col_info)
    if params is None:
        return None

    # Determine filter_type
    if "value" in params and "op" not in params and "min" not in params and "max" not in params:
        filter_type = "value_match"
    elif "op" in params:
        filter_type = "expression"
    else:
        filter_type = "column_range"

    return FilterOp(
        filter_type=filter_type,
        column=col_name,
        params=params,
    )


def _map_sort(intent: StructuredIntent,
              columns: list[ColumnInfo]) -> SortOp | None:
    col_name = _find_column(intent.raw_column, columns)
    if not col_name:
        # Try fallback: sort by last chart's Y column or first numeric
        col_name = _find_numeric_column(columns)
    if not col_name:
        return None

    direction = _parse_sort_direction(intent.raw_direction)
    return SortOp(column=col_name, direction=direction)


def _map_limit(intent: StructuredIntent) -> LimitOp | None:
    n = _parse_int(intent.raw_n)
    if n is None and intent.raw_constraint:
        n = _parse_int(intent.raw_constraint)
    if n is None:
        n = 10  # safe default
    return LimitOp(n=max(1, min(n, 1000)))


def _map_chart(intent: StructuredIntent,
               columns: list[ColumnInfo]) -> ChartPatchOp | None:
    chart_type = _map_chart_type(intent.raw_chart_type)
    x_col = _find_column(intent.raw_x, columns)
    y_col = _find_column(intent.raw_y, columns)

    if not x_col:
        x_col = _find_text_column(columns)
    if not y_col:
        y_col = _find_numeric_column(columns)

    y_columns = (y_col,) if y_col else None

    return ChartPatchOp(
        chart_type=chart_type,
        x_column=x_col,
        y_columns=y_columns,
    )


def _map_chart_type(raw: str) -> str | None:
    """Map user words to chart type."""
    r = raw.strip().lower()
    type_map = {
        "bar": ("柱状图", "条形图", "bar", "柱", "直方图"),
        "line": ("折线图", "趋势图", "线图", "line", "折线", "趋势"),
        "pie": ("饼图", "pie", "饼", "扇形图", "占比图"),
        "scatter": ("散点图", "scatter", "散点", "点图"),
    }
    for chart_type, keywords in type_map.items():
        for kw in keywords:
            if kw in r:
                return chart_type
    return None  # will be resolved by ChartResolver
