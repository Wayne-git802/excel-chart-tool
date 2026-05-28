"""StructuredIntent — LLM outputs this, NOT Operation.

LLM only describes WHAT the user wants. The mapper (intent_mapper.py)
determines HOW to execute it against the actual data schema.

Design principle:
  LLM sees natural language → extracts raw parameters.
  Mapper sees column profile → finds exact matches.
  LLM never fabricates column names, ranges, or operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class StructuredIntent:
    """LLM output — semantic intent, not execution plan.

    All raw_* fields are exactly what the user said, NOT what the system
    should do. The mapper resolves these against the data schema.
    """

    action: Literal["filter", "sort", "limit", "chart", "unknown"]

    # Raw parameters from user's natural language (untouched)
    raw_constraint: str = ""       # "2020年到2015年" / "大于100" / "包含手机"
    raw_column: str = ""           # "年份" / "销售额" — the column the user mentioned
    raw_direction: str = ""        # "从高到低" / "升序" / "大的在前"
    raw_n: str = ""                # "前三个" / "10条" / "top 5"
    raw_chart_type: str = ""       # "饼图" / "折线图" / "柱状图"
    raw_x: str = ""                # "按品类" / "用年份做横轴"
    raw_y: str = ""                # "看销售额"

    # Context / reference resolution
    refers_to: str = ""            # "same data filtered differently" etc.

    confidence: float = 0.5
