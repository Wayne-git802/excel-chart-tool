"""FilterSpecBuilder — LLM-driven filter specification extraction."""

from __future__ import annotations
from typing import Callable, Awaitable

from core.ir.contract import FilterSpec, FilterCondition
from core.ir.profile import DatasetProfile


FILTER_SYSTEM_PROMPT = """你是一个数据过滤条件解析器。根据用户查询和可用的列信息，输出 JSON 格式的过滤条件。

可用列: {columns_info}

规则：
- conditions: 过滤条件列表（AND 逻辑）。无过滤需求时为空列表 []
- persist: 是否跨轮继承。用户说"只看"/"筛选" → true；"对比一下"/"显示" → false
- 每个 condition:
  - column: 列名（使用可用列中的准确名称）
  - operator: "in" | "eq" | "neq" | "gt" | "lt" | "gte" | "lte" | "between"
  - value: 标量（eq/gt）或列表（in）或元组（between）

示例：
- "只看张三和李四" + 列=[姓名] → {{"conditions":[{{"column":"姓名","operator":"in","value":["张三","李四"]}}],"persist":true}}
- "销售额大于10000" + 列=[销售额] → {{"conditions":[{{"column":"销售额","operator":"gt","value":10000}}],"persist":false}}
- "画柱状图" → {{"conditions":[],"persist":false}}

只输出 JSON，不要任何其他文字。"""


class FilterSpecBuilder:
    """Build FilterSpec from user query via LLM."""

    def __init__(self, llm_call: Callable[[str, str], Awaitable[str]]):
        self._llm_call = llm_call

    async def build(self, query: str, profile: DatasetProfile) -> FilterSpec:
        """Query + profile → FilterSpec."""
        import json

        columns_info = ", ".join(
            f"{name}({cp.semantic_type})" for name, cp in profile.columns.items()
        )
        system_prompt = FILTER_SYSTEM_PROMPT.format(columns_info=columns_info)

        try:
            raw = await self._llm_call(system_prompt, query)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            conditions = [
                FilterCondition(
                    column=c["column"],
                    operator=c["operator"],
                    value=c["value"],
                )
                for c in data.get("conditions", [])
            ]
            return FilterSpec(conditions=conditions, persist=data.get("persist", False))
        except Exception:
            return FilterSpec()
