"""StateTransformer — GlobalProfile → ContextualProfile.

Recomputes cardinality, distribution, and semantic_type from filtered dataframe.
"""

from __future__ import annotations

import pandas as pd

from core.ir.profile import DatasetProfile, ColumnProfile, ContextualProfile
from core.ir.contract import FilterSpec
from core.profiling.semantic_inference import infer_semantic_type
from core.profiling.cardinality import classify_cardinality
from core.profiling.distribution import detect_distribution


class StateTransformer:
    """Deterministic transformer: GlobalProfile + FilterSpec → ContextualProfile."""

    @staticmethod
    def transform(
        global_profile: DatasetProfile,
        filter_spec: FilterSpec | None,
        df_filtered: pd.DataFrame,
    ) -> ContextualProfile:
        """Create a per-filter profile from filtered data.

        Inherits immutable metadata (raw_dtype, version, hash).
        Recomputes: cardinality, distribution, semantic_type columns lists.
        """
        row_count = len(df_filtered)
        filter_applied = filter_spec is not None and not filter_spec.is_empty()

        columns: dict[str, ColumnProfile] = {}
        temporal_cols: list[str] = []
        categorical_cols: list[str] = []
        numeric_cols: list[str] = []

        for name, gp in global_profile.columns.items():
            if name not in df_filtered.columns:
                continue

            series = df_filtered[name].dropna()
            unique_count = series.nunique()

            # Recompute cardinality
            cardinality = classify_cardinality(unique_count, row_count)

            # Recompute distribution (numeric only)
            distribution = gp.distribution
            if gp.semantic_type == "numeric" and len(series) >= 4:
                try:
                    distribution = detect_distribution(series.tolist())
                except Exception:
                    pass

            # Re-evaluate semantic_type with filtered data context
            semantic_type = gp.semantic_type

            # Cardinality collapse: if categorical dropped to 1 unique → demote
            if semantic_type == "categorical" and unique_count <= 1:
                semantic_type = "text"

            # Temporal collapse: if only 1 date → demote
            if semantic_type == "temporal" and unique_count <= 1:
                semantic_type = "text"

            # Numeric collapse: if all same value → demote
            if semantic_type == "numeric" and unique_count <= 1:
                semantic_type = "text"

            cp = ColumnProfile(
                name=name,
                semantic_type=semantic_type,
                raw_dtype=gp.raw_dtype,
                null_rate=gp.null_rate,
                unique_count=unique_count,
                cardinality=cardinality,
                distribution=distribution,
                min=float(series.min()) if semantic_type == "numeric" and len(series) > 0 else gp.min,
                max=float(series.max()) if semantic_type == "numeric" and len(series) > 0 else gp.max,
                mean=round(float(series.mean()), 2) if semantic_type == "numeric" and len(series) > 0 else gp.mean,
                median=round(float(series.median()), 2) if semantic_type == "numeric" and len(series) > 0 else gp.median,
            )
            columns[name] = cp

            if semantic_type == "temporal":
                temporal_cols.append(name)
            elif semantic_type == "categorical":
                categorical_cols.append(name)
            elif semantic_type == "numeric":
                numeric_cols.append(name)

        return ContextualProfile(
            version=global_profile.version,
            global_hash=global_profile.hash,
            filter_applied=filter_applied,
            filter_spec=filter_spec,
            row_count=row_count,
            column_count=len(columns),
            columns=columns,
            temporal_cols=temporal_cols,
            categorical_cols=categorical_cols,
            numeric_cols=numeric_cols,
        )
