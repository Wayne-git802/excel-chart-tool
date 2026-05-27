"""
ColumnRegistry — single source of truth for column type semantics.

Every module that needs to know whether a column is numeric/temporal/categorical
MUST query ColumnMeta from the registry. Direct access to dtype/dtype_cn is
forbidden outside this module.

Usage:
    from core.contract.registry import build_column_registry

    registry = build_column_registry(state.columns)
    if registry["sales"].is_numeric:
        ...
"""

from __future__ import annotations
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════════
# Dataclass
# ═══════════════════════════════════════════════════════════════


@dataclass
class ColumnMeta:
    """Immutable column type descriptor. Built once per request, never mutated."""

    name: str              # canonical: "身高(cm)" (fullwidth→halfwidth, stripped)
    original_name: str     # display:  "身高（cm）" (as in source file)
    is_numeric: bool
    is_temporal: bool
    is_categorical: bool


# ═══════════════════════════════════════════════════════════════
# Constants — single definition of type detection rules
# ═══════════════════════════════════════════════════════════════

_NUMERIC_DTYPES = {"float64", "int64", "int32", "float32"}
_NUMERIC_CN = {"数值", "整数"}
_TEMPORAL_NAME_PATTERNS = {"date", "time", "日期", "时间", "年", "月", "日"}
_CATEGORY_CN = {"分类", "二值", "整数分类"}

# Fullwidth → halfwidth mapping for canonical column names
_FULLWIDTH_MAP = str.maketrans(
    "（）　１２３４５６７８９０ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
    "() 1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)


def canonicalize_name(name: str) -> str:
    """Normalize column name: fullwidth→halfwidth, strip, lower."""
    return name.translate(_FULLWIDTH_MAP).strip().lower()


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════


def build_column_registry(columns: list[dict]) -> dict[str, ColumnMeta]:
    """
    Build a frozen registry from raw column metadata.

    Pure function. No cache, no global state. Every call produces a fresh registry.

    Type detection rules (sole authority — nowhere else defines these):
      is_numeric:     dtype in numeric set OR dtype_cn in numeric set
      is_temporal:    dtype == datetime64 OR column name matches time patterns
      is_categorical: dtype_cn in category set OR dtype == object

    Args:
        columns: list of dicts, each with keys: name, dtype, dtype_cn
                 (only 'name' is required; dtype/dtype_cn default to "")

    Returns:
        dict mapping column name → ColumnMeta
    """
    registry: dict[str, ColumnMeta] = {}

    for c in columns:
        name = c.get("name", "")
        if not name:
            continue

        canonical = canonicalize_name(name)
        dtype = c.get("dtype", "")
        dtype_cn = c.get("dtype_cn", "")
        name_lower = canonical  # already lowered

        is_numeric = dtype in _NUMERIC_DTYPES or dtype_cn in _NUMERIC_CN
        is_temporal = dtype == "datetime64" or any(
            p in name_lower for p in _TEMPORAL_NAME_PATTERNS
        )
        is_categorical = dtype_cn in _CATEGORY_CN or dtype == "object"

        registry[canonical] = ColumnMeta(
            name=canonical,
            original_name=name,
            is_numeric=is_numeric,
            is_temporal=is_temporal,
            is_categorical=is_categorical,
        )

    return registry
