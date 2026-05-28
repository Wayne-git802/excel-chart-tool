"""PandasBackend — Phase 1 only backend implementation.

Executes FilterOp, SortOp, LimitOp against pandas DataFrames.
"""

from __future__ import annotations

import pandas as pd
from .base import Backend
from ..ir.operations import FilterOp, SortOp, LimitOp


class PandasBackend:
    """Pandas-based execution backend."""

    def copy(self, data: pd.DataFrame) -> pd.DataFrame:
        return data.copy()

    def column_names(self, data: pd.DataFrame) -> list[str]:
        return list(data.columns)

    def row_count(self, data: pd.DataFrame) -> int:
        return len(data)

    def column_dtype(self, data: pd.DataFrame, column: str) -> str:
        return str(data[column].dtype)

    # ── Filter ────────────────────────────────

    def filter(self, df: pd.DataFrame, op: FilterOp) -> pd.DataFrame:
        col = op.column
        if not col or col not in df.columns:
            return df

        if op.filter_type == "column_range":
            mn = op.params.get("min")
            mx = op.params.get("max")
            mask = pd.Series(True, index=df.index)
            if mn is not None:
                mask &= df[col] >= mn
            if mx is not None:
                mask &= df[col] <= mx
            return df[mask]

        if op.filter_type == "value_match":
            val = str(op.params.get("value", ""))
            if val:
                return df[df[col].astype(str).str.contains(val, na=False)]
            return df

        if op.filter_type == "expression":
            op_str = op.params.get("op")
            val = op.params.get("value")
            valid_ops = {">": "gt", "<": "lt", "==": "eq",
                         "!=": "ne", ">=": "ge", "<=": "le"}
            if op_str in valid_ops and val is not None:
                return df[getattr(df[col], valid_ops[op_str])(val)]

        return df

    # ── Sort ──────────────────────────────────

    def sort(self, df: pd.DataFrame, op: SortOp) -> pd.DataFrame:
        if op.column in df.columns:
            return df.sort_values(
                op.column,
                ascending=(op.direction == "asc"),
                na_position="last"
            )
        return df

    # ── Limit ─────────────────────────────────

    def limit(self, df: pd.DataFrame, op: LimitOp) -> pd.DataFrame:
        return df.head(op.n)
