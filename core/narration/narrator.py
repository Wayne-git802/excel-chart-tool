"""Narrator — renders ChartFacts into natural language.

Dual-layer architecture:
  Mode 1 (Template, DEFAULT): deterministic blocks → no LLM, no hallucination risk.
  Mode 2 (LLM Expansion): LLM expands individual blocks in symbol space.
                           LLM never sees raw labels — only [[entity:e_XXX]] tokens.

post_render() is separate and deterministic: [[entity:e_XXX]] → real label.
LLM NEVER touches entity labels.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Awaitable

from core.ir.narration import ChartFacts, ComparisonFact, NarrationContext


# ═══════════════════════════════════════════════════════════════
# Block types
# ═══════════════════════════════════════════════════════════════

@dataclass
class SummaryBlock:
    chart_type_cn: str
    row_count: int
    filter_description: str


@dataclass
class PeakBlock:
    entity_id: str
    value: float


@dataclass
class TrendBlock:
    direction: str   # "upward" | "downward" | "unclear"


@dataclass
class ComparisonBlock:
    left_entity_id: str
    right_entity_id: str
    metric: str
    ratio: float
    direction: str


# ═══════════════════════════════════════════════════════════════
# LLM Expansion prompts (symbol-only)
# ═══════════════════════════════════════════════════════════════

CHART_TYPE_CN = {
    "line": "趋势图", "bar": "柱状图", "pie": "饼图",
    "scatter": "散点图", "boxplot": "箱线图", "histogram": "直方图",
}

LLM_EXPAND_PEAK_PROMPT = """你是一个数据叙述助手。你只负责将一个已确定的事实块展开为一句中文自然语言。

规则（严格遵守）：
- 使用 [[entity:e_XXX]] 引用实体，这是唯一合法的实体引用格式
- 不创造、不翻译、不解释任何实体名
- 不添加数据中不存在的信息
- 不评价、不推测因果关系
- 只输出一句话

事实: 实体 [[entity:{entity_id}]] 在数值上达到峰值 {value}。
请输出一句自然语言叙述："""

LLM_EXPAND_TREND_PROMPT = """你是一个数据叙述助手。你只负责将一个已确定的事实块展开为一句中文自然语言。

规则（严格遵守）：
- 使用 [[entity:e_XXX]] 引用实体（如有），这是唯一合法的实体引用格式
- 不创造、不翻译、不解释任何实体名
- 不添加数据中不存在的信息
- 不评价、不推测因果关系
- 只输出一句话

趋势方向: {direction_cn}
请输出一句简洁的趋势描述："""

LLM_EXPAND_COMPARISON_PROMPT = """你是一个数据叙述助手。你只负责将一个已确定的事实块展开为一句中文自然语言。

规则（严格遵守）：
- 使用 [[entity:e_XXX]] 引用实体，这是唯一合法的实体引用格式
- 不创造、不翻译、不解释任何实体名
- 不添加数据中不存在的信息
- 不评价、不推测因果关系
- 只输出一句话

事实: [[entity:{left}]] 的 {metric} 比 [[entity:{right}]]
{direction_cn} {ratio} 倍。
请输出一句自然语言叙述："""


# ═══════════════════════════════════════════════════════════════
# Main Narrator
# ═══════════════════════════════════════════════════════════════

class Narrator:
    """Narrator with dual-layer architecture.

    Use ``narrate()`` for template mode (default, zero LLM).
    Use ``narrate_llm()`` for LLM expansion (symbol space only).
    Then call ``post_render()`` to resolve [[entity:e_XXX]] → labels.
    """

    def __init__(self, llm_call: Callable[[str, str], Awaitable[str]] | None = None):
        self._llm_call = llm_call

    # ── Mode 1: Template (default) ────────────────────────────

    def narrate(self, ctx: NarrationContext) -> str:
        """Deterministic template narration. Zero LLM, zero hallucination.

        Output uses [[entity:e_XXX]] tokens — resolve with post_render().
        """
        facts = ctx.facts
        parts: list[str] = []

        # Summary
        ct_cn = CHART_TYPE_CN.get(facts.chart_type, facts.chart_type)
        parts.append(f"已生成{ct_cn}图表")
        if facts.row_count > 0:
            parts.append(f"，共 {facts.row_count} 条数据")
        if facts.filter_description != "(全部数据)":
            parts.append(f"（筛选条件: {facts.filter_description}）")

        # Peak
        if facts.peak_entity_id and facts.peak_value is not None:
            parts.append(f"，[[entity:{facts.peak_entity_id}]] 达到峰值 {self._fmt(facts.peak_value)}")

        # Trend
        if facts.trend_direction == "upward":
            parts.append("，整体呈上升趋势")
        elif facts.trend_direction == "downward":
            parts.append("，整体呈下降趋势")
        elif facts.trend_direction == "unclear":
            parts.append("，趋势不明显")

        # Comparisons
        for comp in facts.comparisons:
            parts.append(self._template_comparison(comp))

        return "".join(parts) + "。"

    # ── Mode 2: LLM Expansion ─────────────────────────────────

    async def narrate_llm(self, ctx: NarrationContext) -> str:
        """LLM expands individual blocks. LLM only sees symbols, never labels.

        Falls back to template mode if LLM call fails.
        """
        if self._llm_call is None:
            return self.narrate(ctx)

        facts = ctx.facts
        parts: list[str] = []

        # Summary is always template
        ct_cn = CHART_TYPE_CN.get(facts.chart_type, facts.chart_type)
        parts.append(f"已生成{ct_cn}图表")
        if facts.row_count > 0:
            parts.append(f"，共 {facts.row_count} 条数据")
        if facts.filter_description != "(全部数据)":
            parts.append(f"（筛选条件: {facts.filter_description}）")

        # Expand each block via LLM
        try:
            # Peak
            if facts.peak_entity_id and facts.peak_value is not None:
                peak_text = await self._expand_peak(facts.peak_entity_id, facts.peak_value)
                if peak_text:
                    parts.append("。" + peak_text)

            # Trend
            if facts.trend_direction:
                trend_text = await self._expand_trend(facts.trend_direction)
                if trend_text:
                    parts.append("。" + trend_text)

            # Comparisons
            for comp in facts.comparisons:
                comp_text = await self._expand_comparison(comp)
                if comp_text:
                    parts.append("。" + comp_text)

            result = "".join(parts)
            if not result.endswith("。"):
                result += "。"
            return result
        except Exception:
            return self.narrate(ctx)

    # ── Internal helpers ──────────────────────────────────────

    async def _expand_peak(self, entity_id: str, value: float) -> str:
        prompt = LLM_EXPAND_PEAK_PROMPT.format(
            entity_id=entity_id, value=self._fmt(value))
        result = await self._llm_call(prompt, "dummy")
        return result.strip()

    async def _expand_trend(self, direction: str) -> str:
        direction_cn = {"upward": "上升", "downward": "下降", "unclear": "不明确"}.get(direction, direction)
        prompt = LLM_EXPAND_TREND_PROMPT.format(direction_cn=direction_cn)
        result = await self._llm_call(prompt, "dummy")
        return result.strip()

    async def _expand_comparison(self, comp: ComparisonFact) -> str:
        direction_cn = "高" if comp.direction == "higher" else "低"
        prompt = LLM_EXPAND_COMPARISON_PROMPT.format(
            left=comp.left_entity_id,
            right=comp.right_entity_id,
            metric=comp.metric,
            direction_cn=direction_cn,
            ratio=round(comp.ratio, 1),
        )
        result = await self._llm_call(prompt, "dummy")
        return result.strip()

    @staticmethod
    def _template_comparison(comp: ComparisonFact) -> str:
        direction_word = "高" if comp.direction == "higher" else "低"
        ratio_str = f"{comp.ratio:.1f}"
        return f"，[[entity:{comp.left_entity_id}]] 的 {comp.metric} 比 [[entity:{comp.right_entity_id}]] {direction_word} {ratio_str} 倍"

    @staticmethod
    def _fmt(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")


# ═══════════════════════════════════════════════════════════════
# post_render — deterministic [[entity:e_XXX]] → label
# ═══════════════════════════════════════════════════════════════

def post_render(text: str, ctx: NarrationContext) -> str:
    """Replace [[entity:e_XXX]] tokens with labels from registry.

    Deterministic. No LLM. Uses regex for exact token matching.
    """
    return ctx.registry.resolve_pattern(text)
