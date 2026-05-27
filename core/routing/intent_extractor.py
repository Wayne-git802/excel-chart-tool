"""IntentExtractor — LLM-driven analysis intent classification.

Converts natural language query → AnalysisIntent (typed, structured).
"""

from __future__ import annotations
from typing import Callable, Awaitable

from core.ir.contract import AnalysisIntent


INTENT_SYSTEM_PROMPT = """你是一个数据分析意图识别器。根据用户查询，输出 JSON 格式的分析意图。

规则：
- type: "trend" | "comparison" | "distribution" | "correlation" | "overview"
- explicit_chart: 如果用户明确指定了图表类型（折线图/柱状图/散点图/饼图/箱线图/直方图），
  填写对应的英文名: "line"|"bar"|"scatter"|"pie"|"boxplot"|"histogram"
  否则为 null
- entities: 提取用户提到的实体，如 metrics（指标名）、filter_hint（过滤提示）

示例：
- "销售额变化趋势" → {"type":"trend","explicit_chart":null,"entities":{"metrics":["销售额"]}}
- "哪个城市利润最高" → {"type":"comparison","explicit_chart":null,"entities":{"metrics":["利润"]}}
- "用折线图展示销量" → {"type":"trend","explicit_chart":"line","entities":{"metrics":["销量"]}}
- "看看数据" → {"type":"overview","explicit_chart":null,"entities":{}}

只输出 JSON，不要任何其他文字。"""


class IntentExtractor:
    """Extract AnalysisIntent from user query via LLM."""

    def __init__(self, llm_call: Callable[[str, str], Awaitable[str]]):
        self._llm_call = llm_call

    async def extract(self, query: str) -> AnalysisIntent:
        """Query → AnalysisIntent."""
        import json

        try:
            raw = await self._llm_call(INTENT_SYSTEM_PROMPT, query)
            # Strip markdown code fences if present
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            return AnalysisIntent(
                type=data.get("type", "UNKNOWN"),
                confidence=0.85 if data.get("type") != "UNKNOWN" else 0.3,
                explicit_chart=data.get("explicit_chart"),
                entities=data.get("entities", {}),
            )
        except Exception:
            return AnalysisIntent(type="UNKNOWN", confidence=0.3)
