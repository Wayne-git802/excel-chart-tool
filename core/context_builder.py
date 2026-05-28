"""ConversationContext — READ-ONLY prompt context projection layer.

IRON LAW: ConversationContext is NEVER a source of truth. AgentState is authoritative.
These dataclasses are pure projections — they read from state/df for prompt injection
only. Never store a ConversationContext, never use it as decision input.

Fixes the "agent has no memory of previous turns" problem by injecting structured
conversation state (filters, dataset stats, analysis history) into LLM prompts.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FilterContextView:
    """READ-ONLY projection of current filter state."""

    active_desc: str | None  # "人物 eq 小红"
    is_filtered: bool
    conditions: list[dict]  # [{"column":..., "operator":..., "value":...}]

    @staticmethod
    def _operator_label(op: str) -> str:
        _map = {
            "eq": "=", "neq": "≠", "gt": ">", "lt": "<",
            "gte": "≥", "lte": "≤", "in": "in", "between": "between",
        }
        return _map.get(op, op)

    @classmethod
    def from_state(cls, state: Any) -> "FilterContextView":
        """Build FilterContextView from AgentState's filter_context."""
        fctx = getattr(state, "filter_context", None)
        if fctx is None:
            return cls(active_desc=None, is_filtered=False, conditions=[])

        active = fctx.active_filter() if hasattr(fctx, "active_filter") else None
        if active is None or (hasattr(active, "is_empty") and active.is_empty()):
            return cls(active_desc=None, is_filtered=False, conditions=[])

        conditions: list[dict] = []
        desc_parts: list[str] = []
        for cond in getattr(active, "conditions", []):
            cdict = {
                "column": getattr(cond, "column", "?"),
                "operator": getattr(cond, "operator", "?"),
                "value": getattr(cond, "value", None),
            }
            conditions.append(cdict)
            op_label = cls._operator_label(cdict["operator"])
            desc_parts.append(f"{cdict['column']} {op_label} {cdict['value']}")

        active_desc = ", ".join(desc_parts) if desc_parts else None
        return cls(
            active_desc=active_desc,
            is_filtered=True,
            conditions=conditions,
        )


@dataclass(frozen=True)
class DatasetContextView:
    """READ-ONLY projection of dataset shape and columns."""

    filtered_rows: int
    total_rows: int
    column_summary: str  # "人物(categorical), 身高(numeric), 体重(numeric)"

    @staticmethod
    def _dtype_label(col: dict) -> str:
        """Map column dtype to a short label."""
        dtype_cn = col.get("dtype_cn", col.get("dtype", "?"))
        dt = dtype_cn.lower()
        # Chinese dtype → English short label
        if any(kw in dt for kw in ["数值", "float", "int", "number", "numeric", "整数"]):
            return "numeric"
        if any(kw in dt for kw in ["分类", "category", "categorical", "string", "object", "文本", "字符"]):
            return "categorical"
        if any(kw in dt for kw in ["日期", "datetime", "date", "时间"]):
            return "temporal"
        return dtype_cn

    @classmethod
    def from_state(cls, state: Any, df: Any, original_row_count: int) -> "DatasetContextView":
        """Build DatasetContextView from state columns + current (filtered) df."""
        filtered_rows = len(df) if df is not None else 0
        col_parts: list[str] = []
        for c in getattr(state, "columns", []):
            name = c.get("name", "?")
            label = cls._dtype_label(c)
            col_parts.append(f"{name}({label})")
        column_summary = ", ".join(col_parts) if col_parts else "(无列信息)"

        return cls(
            filtered_rows=filtered_rows,
            total_rows=original_row_count,
            column_summary=column_summary,
        )


@dataclass(frozen=True)
class AnalysisContextView:
    """READ-ONLY projection of last analysis turn's decisions."""

    last_intent: str | None  # "comparison" / "trend" / etc
    analysis_goal: str | None  # AnalysisIntent.type from last turn
    last_chart_type: str | None
    last_x_column: str | None
    last_y_columns: list[str]
    last_user_message: str | None  # only one message, keep minimal
    is_continuation: bool

    @classmethod
    def from_state(cls, state: Any, prev_user_message: str | None = None) -> "AnalysisContextView":
        """Build AnalysisContextView from AgentState's execution artifacts and traces."""
        # Extract from last execution artifact (if any)
        artifacts = getattr(state, "execution_artifacts", []) or []
        last_chart_type: str | None = None
        last_x_column: str | None = None
        last_y_columns: list[str] = []
        analysis_goal: str | None = None

        if artifacts:
            last = artifacts[-1]
            if hasattr(last, "chart_type"):
                last_chart_type = last.chart_type
            if hasattr(last, "x_column"):
                last_x_column = last.x_column
            if hasattr(last, "y_columns"):
                last_y_columns = list(last.y_columns) if last.y_columns else []

        # Try to extract intent from analysis_trace
        traces = getattr(state, "analysis_trace", []) or []
        last_intent: str | None = None
        if traces:
            last_trace = traces[-1]
            # TraceEntry has 'goal' which might contain intent hints
            goal = getattr(last_trace, "goal", "") or ""
            for kw, intent in [
                ("对比", "comparison"), ("趋势", "trend"), ("分布", "distribution"),
                ("相关", "correlation"), ("概览", "overview"), ("异常", "anomaly"),
            ]:
                if kw in goal:
                    last_intent = intent
                    break

        # analysis_goal mirrors last_intent
        analysis_goal = last_intent

        is_continuation = bool(artifacts or traces)

        return cls(
            last_intent=last_intent,
            analysis_goal=analysis_goal,
            last_chart_type=last_chart_type,
            last_x_column=last_x_column,
            last_y_columns=last_y_columns,
            last_user_message=prev_user_message,
            is_continuation=is_continuation,
        )


# ═══════════════════════════════════════════════════════════════
# ConversationContext — top-level composite
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ConversationContext:
    """READ-ONLY projection layer.

    IRON LAW: never a source of truth. AgentState is authoritative.
    This exists solely for prompt injection. Do NOT store it, do NOT use it
    for decision logic.
    """

    filter: FilterContextView
    dataset: DatasetContextView
    analysis: AnalysisContextView

    @staticmethod
    def build(
        state: Any,
        df: Any,
        original_row_count: int,
        prev_user_message: str | None = None,
    ) -> "ConversationContext":
        """Build a full ConversationContext from AgentState + DataFrame.

        Args:
            state: AgentState (authoritative source)
            df: Current DataFrame (may be filtered)
            original_row_count: Row count BEFORE any filtering was applied
            prev_user_message: The user message from the previous turn (None = first turn)
        """
        return ConversationContext(
            filter=FilterContextView.from_state(state),
            dataset=DatasetContextView.from_state(state, df, original_row_count),
            analysis=AnalysisContextView.from_state(state, prev_user_message),
        )

    # ── Canonical layer names ──
    LAYER_NAMES = {"filter", "dataset", "analysis"}

    # ── Layer: filter ──
    def _filter_section(self) -> str | None:
        if not self.filter.is_filtered:
            return None
        lines = ["[当前数据筛选]"]
        for i, cond in enumerate(self.filter.conditions):
            lines.append(f"  条件{i+1}: {cond['column']} {cond['operator']} {cond['value']}")
        lines.append(f"  描述: {self.filter.active_desc}")
        return "\n".join(lines)

    # ── Layer: dataset ──
    def _dataset_section(self) -> str:
        lines = ["[数据集状态]"]
        if self.dataset.filtered_rows != self.dataset.total_rows:
            lines.append(f"  当前行数: {self.dataset.filtered_rows} (筛选后，原始共 {self.dataset.total_rows} 行)")
        else:
            lines.append(f"  总行数: {self.dataset.total_rows}")
        lines.append(f"  列: {self.dataset.column_summary}")
        return "\n".join(lines)

    # ── Layer: analysis ──
    def _analysis_section(self) -> str | None:
        if not self.analysis.is_continuation:
            return None
        lines = ["[上一轮分析上下文]"]
        if self.analysis.last_intent:
            lines.append(f"  分析意图: {self.analysis.last_intent}")
        if self.analysis.last_chart_type:
            lines.append(f"  图表类型: {self.analysis.last_chart_type}")
        if self.analysis.last_x_column:
            lines.append(f"  X 轴: {self.analysis.last_x_column}")
        if self.analysis.last_y_columns:
            lines.append(f"  Y 轴: {', '.join(self.analysis.last_y_columns)}")
        if self.analysis.last_user_message:
            msg = self.analysis.last_user_message[:200]
            lines.append(f"  用户上一轮问题: {msg}")
        return "\n".join(lines)

    # ── Public API ──

    def to_prompt_sections(self, layers: str = "full") -> list[str]:
        """Return prompt sections as list[str]. Caller joins with newline.

        Args:
            layers: "full" = all layers, "filter" = only filter,
                    "dataset" = only dataset, "analysis" = only analysis.
                    Also accepts space/comma-separated combinations like "filter dataset".

        Returns:
            List of section strings (may be empty). Never returns a raw joined string.
            None-valued sections (e.g., no filter active) are silently skipped.
        """
        requested: set[str]
        if layers == "full":
            requested = self.LAYER_NAMES
        else:
            requested = set(layers.replace(",", " ").split())

        sections: list[str] = []
        for name in ("filter", "dataset", "analysis"):
            if name not in requested:
                continue
            if name == "filter":
                s = self._filter_section()
            elif name == "dataset":
                s = self._dataset_section()
            else:  # analysis
                s = self._analysis_section()
            if s is not None:
                sections.append(s)
        return sections
