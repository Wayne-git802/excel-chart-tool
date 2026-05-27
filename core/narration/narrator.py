"""Narrator — LLM renders ChartFacts into natural language.

LLM only does ONE thing here: verbalize pre-computed facts.
It cannot recommend chart types, interpret data, or modify decisions.
"""

from __future__ import annotations
from typing import Callable, Awaitable

from core.ir.narration import ChartFacts


NARRATOR_PROMPT = """以下是已经计算好的数据分析事实。你的任务是把它们组织成简洁的自然语言叙述。

规则：
- 不要推荐图表类型（图表类型已确定）
- 不要质疑数据或分析方法
- 不要补充未提供的信息
- 用中文，2-4句话，简洁直接
- 如果趋势方向是 upward，可以说"呈上升趋势"
- 如果趋势方向是 downward，可以说"呈下降趋势"
- 如果是对比分析，直接说数值差异

事实：
{formatted_facts}

请输出叙述："""


class Narrator:
    """LLM-based narrator. Takes ChartFacts, produces natural language."""

    def __init__(self, llm_call: Callable[[str, str], Awaitable[str]]):
        self._llm_call = llm_call

    async def narrate(self, facts: ChartFacts) -> str:
        """ChartFacts → natural language narration."""
        lines = [
            f"图表类型: {facts.chart_type}",
            f"X轴: {facts.x_label}",
            f"Y轴: {', '.join(facts.y_labels)}",
            f"数据行数: {facts.row_count}",
            f"筛选条件: {facts.filter_description}",
        ]
        if facts.trend_direction:
            lines.append(f"趋势方向: {facts.trend_direction}")
        if facts.peak_point:
            lines.append(f"峰值: x={facts.peak_point[0]}, y={facts.peak_point[1]}")
        if facts.comparison:
            lines.append(f"对比: {facts.comparison}")
        if facts.stats:
            for col, s in facts.stats.items():
                lines.append(f"{col}统计: 均值={s.get('mean')}, 中位数={s.get('median')}, 范围={s.get('min')}~{s.get('max')}")

        formatted = "\n".join(lines)
        prompt = NARRATOR_PROMPT.format(formatted_facts=formatted)

        try:
            result = await self._llm_call(prompt, "请生成叙述")
            return result.strip()
        except Exception:
            return self._fallback_narrate(facts)

    def _fallback_narrate(self, facts: ChartFacts) -> str:
        """Deterministic fallback narration — no LLM needed."""
        parts = [f"已生成{facts.chart_type}图表"]
        if facts.filter_description != "(全部数据)":
            parts.append(f"（筛选条件: {facts.filter_description}）")
        if facts.trend_direction == "upward":
            parts.append("，数据呈上升趋势")
        elif facts.trend_direction == "downward":
            parts.append("，数据呈下降趋势")
        if facts.peak_point:
            parts.append(f"，最高点出现在{facts.peak_point[0]}（{facts.peak_point[1]}）")
        if facts.comparison:
            parts.append(f"，{facts.comparison}")
        return "".join(parts) + "。"
