"""DataProfiler — deterministic data profiling engine.

Converts state.columns + df → DatasetProfile.
Reuses existing analyzer output (dtype, dtype_cn, unique_count, null_pct, min, max, mean)
and adds: semantic_type, cardinality, distribution, median.
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from core.ir.profile import DatasetProfile, ColumnProfile
from core.profiling.semantic_inference import infer_semantic_type
from core.profiling.cardinality import classify_cardinality
from core.profiling.distribution import detect_distribution


class DataProfiler:
    """Stateless profiler. Every call produces a fresh DatasetProfile."""

    @staticmethod
    def enhance(columns: list[dict], df: pd.DataFrame) -> DatasetProfile:
        """Enhance analyzer output with semantic metadata.

        Args:
            columns: state.columns — list of {name, dtype, dtype_cn, unique_count, null_pct, min, max, mean}
            df: raw dataframe (for sampling and median calculation)

        Returns:
            Immutable DatasetProfile
        """
        row_count = len(df)
        col_profiles: dict[str, ColumnProfile] = {}
        temporal_cols: list[str] = []
        categorical_cols: list[str] = []
        numeric_cols: list[str] = []

        for col in columns:
            name = col.get("name", "")
            if not name:
                continue

            dtype = col.get("dtype", "")
            dtype_cn = col.get("dtype_cn", "")
            unique_count = col.get("unique_count", 0)
            null_rate = col.get("null_pct", 0.0) / 100.0 if col.get("null_pct") else 0.0

            # Sample values from df for inference
            sample_values: list = []
            median = None
            distribution = None
            min_val = col.get("min")
            max_val = col.get("max")
            mean_val = col.get("mean")

            if name in df.columns:
                series = df[name].dropna()
                # Sample first 10 for semantic inference
                try:
                    sample_values = series.head(10).tolist()
                except Exception:
                    pass

                # Median for numeric
                if dtype in ("float64", "int64", "int32", "float32"):
                    try:
                        median = float(series.median())
                    except Exception:
                        pass

                # Distribution
                if dtype in ("float64", "int64", "int32", "float32") and len(series) >= 4:
                    try:
                        distribution = detect_distribution(series.tolist())
                    except Exception:
                        pass

            # Semantic type
            semantic_type = infer_semantic_type(col, sample_values)

            # Cardinality
            cardinality = classify_cardinality(unique_count, row_count)

            cp = ColumnProfile(
                name=name,
                semantic_type=semantic_type,
                raw_dtype=dtype,
                null_rate=round(null_rate, 4),
                unique_count=unique_count,
                cardinality=cardinality,
                distribution=distribution,
                min=min_val,
                max=max_val,
                mean=round(mean_val, 2) if mean_val is not None else None,
                median=round(median, 2) if median is not None else None,
            )
            col_profiles[name] = cp

            if semantic_type == "temporal":
                temporal_cols.append(name)
            elif semantic_type == "categorical":
                categorical_cols.append(name)
            elif semantic_type == "numeric":
                numeric_cols.append(name)

        # Build hash
        hash_input = json.dumps(
            {k: {"semantic_type": v.semantic_type, "raw_dtype": v.raw_dtype}
             for k, v in sorted(col_profiles.items())},
            sort_keys=True,
        )
        profile_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]

        return DatasetProfile(
            version="1.0",
            hash=profile_hash,
            row_count=row_count,
            column_count=len(col_profiles),
            columns=col_profiles,
            temporal_cols=temporal_cols,
            categorical_cols=categorical_cols,
            numeric_cols=numeric_cols,
        )
