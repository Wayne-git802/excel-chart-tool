"""v10 Contract Engine — DSL-based, deterministic chart decision from profile + intent.

Replaces the old contract_entry. All decisions are traceable via DecisionLedger.
"""

from __future__ import annotations

from core.ir.profile import ContextualProfile
from core.ir.contract import AnalysisIntent, ChartDecision, FilterSpec
from core.ir.session import DecisionStep, DecisionLedger


# ═══════════════════════════════════════════════════════════════
# DSL Rules — priority-sorted, first match wins
# ═══════════════════════════════════════════════════════════════

def _resolve_chart_type(
    profile: ContextualProfile,
    intent: AnalysisIntent,
) -> tuple[str, str]:
    """Determine chart_type and reason (because)."""
    
    # Rule 1: explicit user chart type
    if intent.explicit_chart:
        return intent.explicit_chart, "用户指定图表类型"

    # Rule 2: trend → line (needs temporal + numeric)
    if intent.type == "trend" and profile.temporal_cols and profile.numeric_cols:
        return "line", "时序列+数值列适合趋势分析"

    # Rule 3: comparison → bar (needs categorical)
    if intent.type == "comparison" and profile.categorical_cols:
        return "bar", "分类维度+数值对比适合柱状图"

    # Rule 4: correlation → scatter (needs ≥2 numeric)
    if intent.type == "correlation" and len(profile.numeric_cols) >= 2:
        return "scatter", "双数值列适合相关性分析"

    # Rule 5: distribution → histogram (needs ≥1 numeric)
    if intent.type == "distribution" and profile.numeric_cols:
        return "histogram", "单数值列适合分布分析"

    # Rule 6: overview → bar
    if intent.type == "overview":
        return "bar", "概览默认柱状图"

    # Rule 7: fallback
    return "bar", "fallback"


def _select_columns(profile: ContextualProfile, chart_type: str = "bar") -> tuple[str, list[str]]:
    """Select x and y columns from profile. Deterministic, no LLM.
    
    Priority for x:
      - scatter/bubble → numeric first (needs numeric axes)
      - line/area → temporal > categorical > numeric
      - bar/pie/boxplot/histogram → categorical > temporal > numeric
    """
    x_col = ""
    
    if chart_type in ("scatter", "bubble"):
        # Scatter needs numeric x-axis
        if len(profile.numeric_cols) >= 2:
            x_col = profile.numeric_cols[0]
        elif profile.temporal_cols:
            x_col = profile.temporal_cols[0]
        elif profile.categorical_cols:
            x_col = profile.categorical_cols[0]
    else:
        # Default: temporal > categorical > numeric
        if profile.temporal_cols:
            x_col = profile.temporal_cols[0]
        elif profile.categorical_cols:
            x_col = profile.categorical_cols[0]
        elif profile.numeric_cols:
            x_col = profile.numeric_cols[0]
    
    # y: all numeric columns (exclude x if x is numeric)
    y_cols = [c for c in profile.numeric_cols if c != x_col]
    if not y_cols and not x_col:
        all_cols = list(profile.columns.keys())
        if all_cols:
            x_col = all_cols[0]
            y_cols = all_cols[1:2] if len(all_cols) > 1 else []
    
    return x_col, y_cols


def resolve(
    profile: ContextualProfile,
    intent: AnalysisIntent,
) -> tuple[ChartDecision, DecisionLedger]:
    """Main entry: ContextualProfile + AnalysisIntent → ChartDecision + Ledger."""
    
    ledger = DecisionLedger(
        profile_hash=profile.global_hash,
        contextual_hash="",  # TODO: hash contextual profile
    )

    # Step 1: Chart type (determine first so column selection can adapt)
    chart_type, because = _resolve_chart_type(profile, intent)
    decision_source = "explicit_user" if intent.explicit_chart else "profile_rule"
    if chart_type == "bar" and because == "fallback":
        decision_source = "fallback"

    ledger.steps.append(DecisionStep(
        stage="chart_type",
        rule_applied=because,
        input_summary={
            "intent": intent.type,
            "explicit_chart": intent.explicit_chart,
            "temporal_cols": profile.temporal_cols,
            "categorical_cols": profile.categorical_cols,
            "numeric_cols_count": len(profile.numeric_cols),
        },
        output=chart_type,
    ))

    # Step 2: Column selection (chart_type-aware)
    x_col, y_cols = _select_columns(profile, chart_type)
    ledger.steps.append(DecisionStep(
        stage="column_select",
        rule_applied=f"scatter_numeric_first" if chart_type in ("scatter","bubble") else "temporal>categorical>numeric",
        input_summary={
            "temporal_cols": profile.temporal_cols,
            "categorical_cols": profile.categorical_cols,
            "numeric_cols": profile.numeric_cols,
            "chart_type": chart_type,
        },
        output={"x": x_col, "y": y_cols},
    ))

    if not x_col or not y_cols:
        return ChartDecision.none(), ledger

    title = f"{chart_type} 图表"
    if intent.explicit_chart:
        title = f"{intent.explicit_chart} 图表"

    decision = ChartDecision(
        chart_type=chart_type,
        x_column=x_col,
        y_columns=y_cols,
        title=title,
        decision_source=decision_source,
    )

    return decision, ledger
