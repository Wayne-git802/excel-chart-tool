"""IntentClassifier — LLM converts natural language to StructuredIntent.

LLM understands WHAT the user wants. The mapper (intent_mapper.py)
determines HOW to execute it. LLM never fabricates column names.
"""

from __future__ import annotations

import json
import os
import aiohttp

from ..ir.view_spec import ViewSpec
from ..ir.column_info import ColumnInfo
from ..renderers.summary_renderer import render_summary
from .intent_models import StructuredIntent

API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


def _get_api_key() -> str:
    """Get DeepSeek API key from env or .env files."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key

    # Check project .env
    for base in [
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes"),
    ]:
        env_path = os.path.join(base, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("DEEPSEEK_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass

    return ""


SYSTEM_PROMPT = """You are an intent classifier for a data analysis assistant.

Your job: analyze what the user wants and output a JSON intent object.

RULES:
1. Only extract what the user EXPLICITLY said — never guess or fill in missing values.
2. raw_column: the column name the user mentioned (if any). Leave "" if not mentioned.
3. raw_constraint: EXACT constraint text from user. If user said "只看前三个人的数据", raw_constraint="前三个人的数据".
4. raw_n: extract the number. "前三个" → raw_n="3". Leave "" if no number mentioned.
5. raw_direction: "从高到低"/"从大到小" → "desc". "升序"/"从小到大" → "asc". Leave "" otherwise.
6. raw_chart_type/raw_x/raw_y: only fill if user asks to change the chart.
7. action: choose from "filter", "sort", "limit", "chart", "unknown".
   - "只看前三个" → action="limit", raw_n="3"
   - "按年龄从大到小排序" → action="sort", raw_column="年龄", raw_direction="desc"
   - "只看2020年之后的" → action="filter", raw_column="年份", raw_constraint="2020年之后"
   - "换成饼图" → action="chart", raw_chart_type="饼图"
   - "帮我分析趋势" → action="unknown"

IMPORTANT: raw_column must be EXACTLY what the user said — never substitute.
The system will fuzzy-match raw_column against actual column names.

Output ONLY valid JSON, no explanation, no markdown fences.
"""

USER_PROMPT_TEMPLATE = """Current data: {columns_summary}
Total rows: {total_rows}
Current view: {view_summary}

User message: "{message}"

Output JSON:"""


async def classify(
    message: str,
    columns: list[ColumnInfo],
    total_rows: int,
    view_spec: ViewSpec,
    api_key: str = "",
) -> StructuredIntent:
    """
    Classify user message into StructuredIntent via LLM.

    Returns StructuredIntent. On failure, returns action="unknown".
    """
    key = api_key or _get_api_key()
    if not key:
        return StructuredIntent(action="unknown")

    columns_summary = ", ".join(
        f"{c.name}({c.dtype_cn})" for c in columns
    )
    view_summary = render_summary(view_spec)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        columns_summary=columns_summary,
        total_rows=total_rows,
        view_summary=view_summary,
        message=message,
    )

    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return StructuredIntent(action="unknown")
                data = await resp.json()

        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        return StructuredIntent(
            action=parsed.get("action", "unknown"),
            raw_constraint=str(parsed.get("raw_constraint", "")),
            raw_column=str(parsed.get("raw_column", "")),
            raw_direction=str(parsed.get("raw_direction", "")),
            raw_n=str(parsed.get("raw_n", "")),
            raw_chart_type=str(parsed.get("raw_chart_type", "")),
            raw_x=str(parsed.get("raw_x", "")),
            raw_y=str(parsed.get("raw_y", "")),
            refers_to=str(parsed.get("refers_to", "")),
            confidence=float(parsed.get("confidence", 0.5)),
        )

    except Exception:
        return StructuredIntent(action="unknown")
