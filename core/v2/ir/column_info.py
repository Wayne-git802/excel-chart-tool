"""ColumnInfo — column metadata extracted from base_df once per session.

Phase 1: simple dtype-based mapping.
Phase 2: integrate DataProfiler for richer semantic inference.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnInfo:
    """Column metadata. Immutable — base_df columns never change in Phase 1."""
    name: str
    dtype: str          # "int64", "float64", "object", "datetime64[ns]"
    dtype_cn: str       # "整数", "小数", "文本", "日期"


_DTYPE_CN_MAP = {
    "int": "整数",
    "float": "小数",
    "object": "文本",
    "datetime": "日期",
    "bool": "布尔",
}


def extract_columns(base_data, backend) -> list[ColumnInfo]:
    """Extract column metadata from base_data.

    Called once after file upload. Result is stable for the session lifetime
    (Phase 1 has no AggregateOp, so schema never changes).
    """
    result = []
    for name in backend.column_names(base_data):
        raw = backend.column_dtype(base_data, name)
        cn = "文本"
        for key, label in _DTYPE_CN_MAP.items():
            if key in raw.lower():
                cn = label
                break
        result.append(ColumnInfo(name=name, dtype=raw, dtype_cn=cn))
    return result
