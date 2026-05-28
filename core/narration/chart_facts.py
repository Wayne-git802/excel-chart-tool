"""ChartFactsExtractor — deterministic fact extraction from chart result + profile.

Produces ChartFacts IR with symbolic entity references (entity IDs only).
Entity labels live in EntityRegistry — never leak into ChartFacts.

LLM never touches this module.
"""

from __future__ import annotations

import pandas as pd

from core.ir.narration import ChartFacts, ComparisonFact
from core.ir.contract import ChartDecision
from core.ir.profile import ContextualProfile
from core.ir.entity import EntityRegistry
from core.narration.trend_rules import detect_trend
from core.narration.comparison_rules import find_peak, compare_groups


class ChartFactsExtractor:
    """Extract deterministic facts from chart execution result.

    All entity references in the output are symbolic (entity IDs).
    """

    @staticmethod
    def extract(
        decision: ChartDecision,
        profile: ContextualProfile,
        df: pd.DataFrame,
    ) -> ChartFacts:
        """ChartDecision + ContextualProfile + filtered df → ChartFacts (symbolic)."""

        # ── Entity Registry ──────────────────────────────────
        registry = EntityRegistry.build(df, decision.x_column) if decision.x_column in df.columns \
            else EntityRegistry(mapping={}, id_column=decision.x_column)
        label_to_id = {v: k for k, v in registry.mapping.items()}

        # ── Filter description ───────────────────────────────
        if profile.filter_applied and profile.filter_spec:
            fd_parts = []
            for c in profile.filter_spec.conditions:
                val_str = str(c.value)
                if len(val_str) > 30:
                    val_str = val_str[:30] + "..."
                fd_parts.append(f"{c.column}{c.operator}{val_str}")
            filter_description = ", ".join(fd_parts)
        else:
            filter_description = "(全部数据)"

        # ── Trend direction (for y_cols[0]) ──────────────────
        trend_direction = None
        if decision.y_columns and decision.x_column in df.columns:
            y_col = decision.y_columns[0]
            if y_col in df.columns:
                try:
                    y_vals = df[y_col].tolist()
                    trend_direction = detect_trend(y_vals)
                except Exception:
                    pass

        # ── Peak point (symbolic) ────────────────────────────
        peak_entity_id = None
        peak_value = None
        if decision.y_columns and decision.x_column in df.columns:
            y_col = decision.y_columns[0]
            if y_col in df.columns:
                try:
                    x_vals = df[decision.x_column].tolist()
                    y_vals = df[y_col].tolist()
                    peak_raw = find_peak(x_vals, y_vals)
                    if peak_raw:
                        raw_label, raw_y = peak_raw
                        peak_entity_id = label_to_id.get(str(raw_label))
                        peak_value = raw_y
                except Exception:
                    pass

        # ── Comparisons (symbolic) ───────────────────────────
        comparisons: list[ComparisonFact] = []
        if profile.filter_applied and profile.filter_spec:
            for c in profile.filter_spec.conditions:
                if c.operator == "in" and isinstance(c.value, list) and len(c.value) == 2:
                    if decision.y_columns and decision.x_column in df.columns:
                        try:
                            raw_comp = compare_groups(
                                df, c.column, decision.y_columns[0], c.value
                            )
                            if raw_comp:
                                left_id = label_to_id.get(raw_comp.a_label)
                                right_id = label_to_id.get(raw_comp.b_label)
                                if left_id and right_id:
                                    comparisons.append(ComparisonFact(
                                        left_entity_id=left_id,
                                        right_entity_id=right_id,
                                        metric=decision.y_columns[0],
                                        ratio=raw_comp.ratio,
                                        direction=raw_comp.direction,
                                    ))
                        except Exception:
                            pass

        # ── Stats ────────────────────────────────────────────
        stats: dict[str, dict] = {}
        for yc in decision.y_columns:
            if yc in df.columns:
                try:
                    s = df[yc]
                    stats[yc] = {
                        "mean": round(float(s.mean()), 2),
                        "median": round(float(s.median()), 2),
                        "min": round(float(s.min()), 2),
                        "max": round(float(s.max()), 2),
                    }
                except Exception:
                    pass

        return ChartFacts(
            chart_type=decision.chart_type,
            x_label=decision.x_column,
            y_labels=decision.y_columns,
            row_count=profile.row_count,
            filter_description=filter_description,
            entity_ids_used=list(registry.mapping.keys()),
            trend_direction=trend_direction,
            peak_entity_id=peak_entity_id,
            peak_value=peak_value,
            comparisons=comparisons,
            stats=stats,
            decision_source=decision.decision_source,
        )
