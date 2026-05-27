"""Unified Tool Result & SSE Event contracts."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
import json
import time

MAX_TOOL_PAYLOAD_KB = 32

@dataclass
class ToolResult:
    success: bool
    tool: str
    narrative: str
    data: dict | None = None
    chart_spec: dict | None = None
    observations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    error: str | None = None

    def __post_init__(self):
        if self.chart_spec and not self.narrative:
            raise ValueError("ToolResult: chart_spec requires narrative")
        if self.data is not None:
            self._enforce_size_limit()

    def _enforce_size_limit(self):
        size_kb = len(json.dumps(self.data, default=str)) / 1024
        if size_kb > MAX_TOOL_PAYLOAD_KB:
            self.data = {"_truncated": True, "summary": f"payload {size_kb:.0f}KB exceeded {MAX_TOOL_PAYLOAD_KB}KB limit"}


def normalize_tool_result(raw: dict | ToolResult, tool: str) -> ToolResult:
    """兼容层：旧 dict → 新 ToolResult。过渡期关键。"""
    if isinstance(raw, ToolResult):
        return raw
    ok = raw.get("ok", False)
    err = raw.get("error") or raw.get("result", {}).get("error") if isinstance(raw.get("result"), dict) else None
    result_data = raw.get("result", {})
    if not isinstance(result_data, dict):
        result_data = {}
    return ToolResult(
        success=ok,
        tool=tool,
        narrative=raw.get("narrative") or raw.get("observation", "") or result_data.get("title", "") or "",
        data=result_data if result_data else None,
        chart_spec=result_data.get("chart_spec") if isinstance(result_data, dict) else None,
        observations=[raw.get("observation", "")] if raw.get("observation") else [],
        confidence=float(raw.get("confidence", 0.7 if ok else 0.0)),
        error=str(err) if err else None,
    )


@dataclass
class SSEEvent:
    type: Literal["narrative", "reasoning", "action", "error", "done"]
    step_id: str | None = None
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
