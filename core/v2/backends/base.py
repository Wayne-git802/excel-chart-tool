"""Backend Protocol — execution backend abstraction.

Replay engine does NOT import pandas directly.
All data ops go through this Protocol.
Future: DuckDBBackend, PolarsBackend implement the same interface.
"""

from __future__ import annotations

from typing import Protocol, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..ir.operations import FilterOp, SortOp, LimitOp


class Backend(Protocol):
    """
    Data execution backend interface.
    Concrete types: PandasBackend → DataFrame, DuckDBBackend → Relation.
    """

    def copy(self, data: Any) -> Any:
        """Deep copy — guarantees no mutation of original data."""
        ...

    def filter(self, data: Any, op: FilterOp) -> Any:
        """Execute FilterOp."""
        ...

    def sort(self, data: Any, op: SortOp) -> Any:
        """Execute SortOp."""
        ...

    def limit(self, data: Any, op: LimitOp) -> Any:
        """Execute LimitOp."""
        ...

    def column_names(self, data: Any) -> list[str]:
        """Column name list for validator."""
        ...

    def row_count(self, data: Any) -> int:
        """Row count. Avoids dependency on len() for DuckDB etc."""
        ...

    def column_dtype(self, data: Any, column: str) -> str:
        """
        Column dtype string.
        PandasBackend → "int64", "float64", "object", "datetime64[ns]"
        """
        ...
