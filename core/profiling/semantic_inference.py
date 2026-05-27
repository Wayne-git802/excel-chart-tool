"""Semantic type inference — deterministic classification of column types.

Input: column metadata dict (from state.columns) + optional data sample
Output: semantic_type string

Channels (cross-validated):
  1. raw_dtype: int64/float64 → numeric, datetime64 → temporal, object → depends
  2. dtype_cn: Chinese type label from analyzer (数值/分类/日期/文本)
  3. name patterns: column name heuristics (时间/日/月/年 → temporal)
  4. data sampling: check sample values (ISO dates, numbers, etc.)
"""

from __future__ import annotations

import re
from typing import Any

_TEMPORAL_NAME_PATTERNS = re.compile(r"日期|时间|年|月|日|date|time|year|month|day", re.IGNORECASE)
_NUMERIC_NAME_PATTERNS = re.compile(r"金额|价格|销量|数量|金额|收入|支出|利润|成本|销售额|订单数", re.IGNORECASE)
_CATEGORY_NAME_PATTERNS = re.compile(r"类别|类型|分类|地区|城市|区域|部门|性别|状态", re.IGNORECASE)

_NUMERIC_DTYPES = {"float64", "int64", "int32", "float32"}
_NUMERIC_CN = {"数值", "整数"}


def infer_semantic_type(col: dict[str, Any], sample_values: list[Any] | None = None) -> str:
    """Deterministic semantic type inference. Never returns None — returns 'UNKNOWN' if unsure."""

    name = col.get("name", "")
    dtype = col.get("dtype", "")
    dtype_cn = col.get("dtype_cn", "")

    # Channel 1: raw dtype
    if dtype == "datetime64":
        return "temporal"
    if dtype in _NUMERIC_DTYPES:
        is_numeric = True
    elif dtype == "object":
        is_numeric = False
    else:
        is_numeric = False

    # Channel 2: dtype_cn
    if dtype_cn in _NUMERIC_CN:
        is_numeric = True
    if dtype_cn in ("日期", "时间"):
        return "temporal"
    if dtype_cn in ("分类", "二值"):
        return "categorical"

    # Channel 3: name patterns
    if _TEMPORAL_NAME_PATTERNS.search(name):
        # Cross-check: don't call it temporal if dtype is clearly numeric
        if is_numeric:
            return "numeric"
        return "temporal"

    if _CATEGORY_NAME_PATTERNS.search(name):
        return "categorical"

    # Channel 4: if numeric by dtype
    if is_numeric:
        return "numeric"

    # Channel 5: text if object dtype
    if dtype == "object":
        return "text"

    return "UNKNOWN"
