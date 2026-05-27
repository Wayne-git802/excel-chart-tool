"""Core IR — Profile types (immutable)."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnProfile:
    """Immutable descriptor for a single column."""

    name: str  # canonical (fullwidth→halfwidth, stripped)
    semantic_type: str  # "temporal" | "numeric" | "categorical" | "text" | "UNKNOWN"
    raw_dtype: str  # "int64" | "float64" | "object" | "datetime64" ...
    null_rate: float  # 0.0 ~ 1.0
    unique_count: int
    cardinality: str  # "low"(≤20) | "medium"(21-100) | "high"(>100)
    distribution: str | None = None  # "normal" | "right_skewed" | "left_skewed" | "uniform" | None
    min: Any = None
    max: Any = None
    mean: float | None = None
    median: float | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "semantic_type": self.semantic_type,
            "raw_dtype": self.raw_dtype,
            "null_rate": self.null_rate,
            "unique_count": self.unique_count,
            "cardinality": self.cardinality,
            "distribution": self.distribution,
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "median": self.median,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ColumnProfile":
        return cls(
            name=d["name"],
            semantic_type=d["semantic_type"],
            raw_dtype=d["raw_dtype"],
            null_rate=d["null_rate"],
            unique_count=d["unique_count"],
            cardinality=d["cardinality"],
            distribution=d.get("distribution"),
            min=d.get("min"),
            max=d.get("max"),
            mean=d.get("mean"),
            median=d.get("median"),
        )


@dataclass(frozen=True)
class DatasetProfile:
    """Immutable global dataset profile. Generated once at upload, read-only thereafter."""

    version: str  # "1.0"
    hash: str  # sha256(repr(columns))
    row_count: int
    column_count: int
    columns: dict[str, ColumnProfile] = field(default_factory=dict)
    temporal_cols: list[str] = field(default_factory=list)
    categorical_cols: list[str] = field(default_factory=list)
    numeric_cols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "hash": self.hash,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": {k: v.to_dict() for k, v in self.columns.items()},
            "temporal_cols": self.temporal_cols,
            "categorical_cols": self.categorical_cols,
            "numeric_cols": self.numeric_cols,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetProfile":
        return cls(
            version=d["version"],
            hash=d["hash"],
            row_count=d["row_count"],
            column_count=d["column_count"],
            columns={k: ColumnProfile.from_dict(v) for k, v in d.get("columns", {}).items()},
            temporal_cols=d.get("temporal_cols", []),
            categorical_cols=d.get("categorical_cols", []),
            numeric_cols=d.get("numeric_cols", []),
        )


@dataclass(frozen=True)
class ContextualProfile:
    """Per-filter profile. Recomputes cardinality/distribution/semantic_type from df_filtered."""

    version: str
    global_hash: str
    filter_applied: bool
    filter_spec: Any | None = None  # FilterSpec (avoid circular import)
    row_count: int = 0
    column_count: int = 0
    columns: dict[str, ColumnProfile] = field(default_factory=dict)
    temporal_cols: list[str] = field(default_factory=list)
    categorical_cols: list[str] = field(default_factory=list)
    numeric_cols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "global_hash": self.global_hash,
            "filter_applied": self.filter_applied,
            "filter_spec": self.filter_spec.to_dict() if self.filter_spec else None,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": {k: v.to_dict() for k, v in self.columns.items()},
            "temporal_cols": self.temporal_cols,
            "categorical_cols": self.categorical_cols,
            "numeric_cols": self.numeric_cols,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContextualProfile":
        return cls(
            version=d["version"],
            global_hash=d["global_hash"],
            filter_applied=d["filter_applied"],
            filter_spec=None,  # caller must hydrate
            row_count=d["row_count"],
            column_count=d["column_count"],
            columns={k: ColumnProfile.from_dict(v) for k, v in d.get("columns", {}).items()},
            temporal_cols=d.get("temporal_cols", []),
            categorical_cols=d.get("categorical_cols", []),
            numeric_cols=d.get("numeric_cols", []),
        )
