"""
对话驱动的 AI 画图助手核心模块 (v2 — Bounded ReAct Agent).

ChatService — 接收自然语言消息，通过 Bounded ReAct Loop 进行迭代推理:
每步执行单个工具调用，观察结果，再决定下一步。最大 3 步，置信度 ≥0.85 时自动停止。
支持 Fake LLM 模式用于离线演示；每步操作通过 ToolTraceRecorder 记录。

架构 (v2):
    User Message → ChatService.chat()
        → System Prompt (列信息 + Decision Memory + ReAct 观察历史)
        → [ReAct Loop] DeepSeek API / Fake LLM
            → Step 1: think → single action → observe
            → Step 2: think (with observation) → single action → observe
            → Step 3: think (with observation) → stop / continue
        → SSE 事件流 (insight / text / thinking / action / error / done)

依赖:
    models.agent_state     — AgentState, ThinkingTrace, ConfidenceLevel
    services.logger        — SessionLogger (JSONL observability)
    services.chart_builder — ChartBuilder.build() → ECharts HTML
    services.state_manager — StateManager (SQLite persistence)
"""

from __future__ import annotations

import json
import os
import re
import time
import traceback
from typing import AsyncGenerator

import aiohttp
import pandas as pd

from models.agent_state import AgentState, ThinkingTrace, ConfidenceLevel, AnalysisNode, NodeType, PlanStep
from services.logger import SessionLogger
from services.chart_builder import ChartBuilder
from services.state_manager import StateManager
from services.router import ConversationRouter
from services.router.mini_chart_planner import plan_chart

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"

VALID_CHART_TYPES = {
    "bar", "line", "pie", "scatter", "stacked_bar", "grouped_bar",
    "boxplot", "histogram", "heatmap", "scatter_matrix", "bubble",
    "funnel", "treemap", "area", "radar", "gauge",
}

USE_FAKE_LLM = os.environ.get("FAKE_LLM", "0") == "1"


import builtins
def _dlog(msg):
    try:
        with builtins.open("C:/Users/admin/Desktop/excel-chart-tool/logs/debug.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
            f.flush()
    except Exception as e:
        try:
            with builtins.open("C:/Users/admin/Desktop/excel-chart-tool/logs/debug_err.log", "a", encoding="utf-8") as f:
                f.write(f"DL_FAIL: {e}\n")
        except:
            pass

class ContractViolationError(Exception):
    """Raised when _handle_chart_builder receives invalid parameters."""
    pass


def _serialize_insights(clustered_list: list) -> list[dict]:
    """Serialize ClusteredInsight objects to JSON-safe dicts for SSE."""
    result = []
    for ci in clustered_list:
        r = ci.representative
        result.append({
            "type": r.type,
            "title": r.title,
            "description": r.description or "",
            "score": round(getattr(r, "score", 0), 3),
            "effect_size": round(getattr(r, "effect_size", 0) or 0, 3),
            "confidence": round(ci.confidence_aggregated, 3),
            "source_count": ci.source_count,
            "sources": ci.sources or [],
            "columns": getattr(r, "columns", []) or [],
            "chart_hint": getattr(r, "chart_spec_hint", {}) or {},
            "payload": getattr(r, "payload", {}) or {},
        })
    return result


# ═══════════════════════════════════════════════════════════════
# API Key helper (reuses recommender.py pattern)
# ═══════════════════════════════════════════════════════════════

def _get_api_key() -> str:
    """Read DeepSeek API key from env var or ~/.hermes/.env file."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        for path in [
            os.path.expanduser("~/.hermes/.env"),
            os.path.join(os.path.dirname(__file__), "..", ".env"),
        ]:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("DEEPSEEK_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
        if key:
            # Cache for subsequent calls
            os.environ["DEEPSEEK_API_KEY"] = key
    return key


# ═══════════════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════════════
# Node Type → Allowed Tools (Plan-then-Execute constraint)
# ═══════════════════════════════════════════════════════════════

NODE_TOOLS = {
    "overview": ["data_query"],
    "drill_down": ["data_query", "chart_builder", "hypothesis_test"],
    "trend_analysis": ["data_query", "chart_builder"],
    "correlation_analysis": ["data_query", "chart_builder", "hypothesis_test"],
    "anomaly_detection": ["data_query", "chart_builder", "hypothesis_test"],
    "distribution_analysis": ["data_query", "chart_builder"],
    "hypothesis_validation": ["hypothesis_test", "data_query"],
    "conclusion": ["chart_builder", "annotation_engine", "story_graph"],
    "intent_response": ["data_query", "chart_builder", "hypothesis_test", "annotation_engine", "story_graph"],
    "chart_generation": ["chart_builder", "data_query"],
}

NODE_TOOL_CN = {
    "overview": "数据概览", "drill_down": "深入分析",
    "trend_analysis": "趋势分析",
    "correlation_analysis": "关联分析", "anomaly_detection": "异常检测",
    "distribution_analysis": "分布分析", "hypothesis_validation": "假设验证",
    "conclusion": "结论汇总", "intent_response": "自由探索",
    "chart_generation": "图表生成",
}

# ═══════════════════════════════════════════════════════════════
# System Prompt (v3 — Plan-then-Execute)
# ═══════════════════════════════════════════════════════════════

def _build_system_prompt(
    state: AgentState,
    step: int = 0,
    observations: list[str] | None = None,
    step_context: list[tuple[str, str]] | None = None,
    insight_context: str | None = None,
) -> str:
    """Construct the system prompt with Plan + Constraints + Reasoning Memory."""

    col_lines: list[str] = []
    for c in state.columns:
        name = c.get("name", "?")
        dtype_cn = c.get("dtype_cn", c.get("dtype", "?"))
        stats = c.get("stats", {})
        stat_str = ""
        if stats:
            parts = []
            for key, label in [("min", "min"), ("max", "max"), ("mean", "avg")]:
                if key in stats and stats[key] is not None:
                    parts.append(f"{label}={round(stats[key], 2)}")
            if parts:
                stat_str = " (" + ", ".join(parts) + ")"
        col_lines.append(f"  - {name} [{dtype_cn}]{stat_str}")

    columns_block = "\\n".join(col_lines) if col_lines else "  (无列信息)"

    # Insight context (from InsightEngine)
    insight_block = ""
    if insight_context:
        insight_block = f"\\n**数据洞察（来自自动分析）**：\\n{insight_context}\\n"

    # Plan Progress
    plan_block = ""
    if state.plan_generated and state.analysis_plan:
        plan_block = "**分析计划**:\n" + state.get_plan_summary() + "\n"
        current_node = None
        for s in state.analysis_plan:
            if s.get("status") == "active":
                current_node = s
                break
        if current_node:
            node_type = current_node.get("node_type", "intent_response")
            allowed = NODE_TOOLS.get(node_type, NODE_TOOLS["intent_response"])
            plan_block += (
                f"当前节点类型: **{NODE_TOOL_CN.get(node_type, '?')}** "
                f"→ 允许工具: {', '.join(allowed)}\n"
            )
    else:
        plan_block = "**分析计划**: 尚未制定 — 这是第一轮，请先制定分析计划。\n"

    # Decision Memory + Reasoning Summary
    decision_lines: list[str] = []

    expl = state.explored_questions
    if expl:
        decision_lines.append("**已验证的结论**:")
        for e in expl[-5:]:
            reason = e.get("reason", "")
            reason_str = f" — 理由: {reason}" if reason else ""
            decision_lines.append(
                f"  ✓ {e.get('question', '')} → {e.get('answer', '')}"
                f"(置信度: {e.get('confidence', 0):.0%}){reason_str}"
            )

    hyps = state.active_hypotheses
    if hyps:
        decision_lines.append("**正在探索**:")
        for h in hyps[-3:]:
            decision_lines.append(f"  ⟳ [{h.get('status', '?')}] {h.get('question', '')}")

    rejected = state.rejected_paths
    if rejected:
        decision_lines.append("**已排除的路径**:")
        for r in rejected[-3:]:
            decision_lines.append(f"  ✗ {r.get('path', '')} — {r.get('reason', '')}")

    if state.chart_memory:
        chart_ids = list(state.chart_memory.keys())[-5:]
        chart_labels = []
        for cid in chart_ids:
            cm = state.chart_memory[cid]
            chart_labels.append(f"{cm.get('type','?')}:{cm.get('title','?')}")
        decision_lines.append(f"**已生成图表**: {', '.join(chart_labels)}")

    # Plan step reasoning — the "why" behind decisions
    if state.analysis_plan:
        completed_with_reasoning = [
            s for s in state.analysis_plan
            if s.get("status") == "completed" and s.get("reasoning")
        ]
        if completed_with_reasoning:
            decision_lines.append("**决策理由**:")
            for s in completed_with_reasoning[-3:]:
                decision_lines.append(f"  「{s.get('label','?')}」→ {s.get('reasoning','')[:120]}")

    decision_block = "\n".join(decision_lines) if decision_lines else "  (无历史决策)"

    # story_graph
    cur_node = state.story_graph.get_current()
    graph_block = (
        f"当前: [{cur_node.type.value}] {cur_node.label or cur_node.question}"
        if cur_node else "(未初始化)"
    )

    # ReAct observation history
    obs_block = ""
    if step_context:
        ctx_lines = []
        for i, (rep, obs) in enumerate(step_context):
            ctx_lines.append(f"  Step {i + 1}: 说了「{rep[:100]}」→ 观察: {obs[:120]}")
        obs_block = "**执行历史**:\n" + "\n".join(ctx_lines) + "\n"

    # Mode-aware instruction
    if not state.plan_generated:
        mode_instruction = """
## 🎯 当前任务：制定分析计划 (Plan Generation)

请根据用户的问题和数据特征，输出一个 3-5 步的分析计划。

响应格式:
{
  "reply": "我会按以下计划分析你的数据...",
  "thinking_label": "制定分析计划",
  "confidence": {"level": "medium", "score": 0.7},
  "analysis_plan": [
    {"id": "overview", "node_type": "overview", "label": "数据概览", "tool": "data_query"},
    {"id": "trend", "node_type": "trend_analysis", "label": "趋势分析", "tool": "chart_builder"},
    {"id": "conclusion", "node_type": "conclusion", "label": "总结发现", "tool": "annotation_engine"}
  ],
  "action": null,
  "stop": false
}

规则:
- plan 3-5 步，每步 node_type 通常不同
- 第一步通常是 overview
- 最后一步通常是 conclusion
- 用户提到"趋势"/"变化" → 加 trend_analysis
- 用户提到"对比"/"关系" → 加 correlation_analysis
- 数据列 <5 列 → plan 精简到 3 步
"""
    else:
        mode_instruction = """
## ⚡ 当前任务：执行分析计划 (Plan Execution)

上面显示的分析计划是你之前制定的。请执行当前激活 (→) 的那一步。

**关键规则**:
1. 只看当前激活的那一步，使用该节点类型允许的工具
2. 执行后观察结果，决定:
   - 继续: 完成后进入下一步
   - 重写: 观察结果有新发现时，可以插入新步骤 (plan_rewrite)
   - 停止: 计划全部完成且置信度 >= 0.85

**Plan Rewrite** (可选):
如果观察结果揭示了原计划未覆盖的发现，在响应中加入:
"plan_rewrite": [
  {"id": "anomaly", "node_type": "anomaly_detection", "label": "异常深挖", "tool": "chart_builder"}
]

响应格式:
{
  "reply": "...",
  "thinking_label": "...",
  "reasoning": "为什么选择这个操作？基于什么观察？",
  "confidence": {"level": "high|medium|low", "score": 0.0-1.0},
  "action": {"tool": "...", "args": {...}},
  "plan_rewrite": null,
  "stop": false
}
"""

    return f"""你是「AI图表助手」，一个具备 Plan-then-Execute 能力的认知 Agent。

## 核心原则
- 先制定分析计划，再逐步执行
- 每一步只做一个操作，观察结果后再决定下一步
- 当计划全部完成且置信度 >= 0.85 时，设置 stop: true
- 不要猜测 — 先查数据再下结论

## 数据上下文

**文件**: {state.file_path} | **工作表**: {state.sheet_name} | **行数**: {state.row_count}

**列信息**:
{columns_block}

{insight_block}
{plan_block}
## 决策记忆
{decision_block}

**分析图**: {graph_block}
{obs_block}
{mode_instruction}

## 工具参考

1. **chart_builder** — 生成图表。args: {{"type": "{", ".join(sorted(VALID_CHART_TYPES))}" 之一, "x": "列名", "y": ["列1"], "title": "标题"}}

**图表类型选择规则（重要！）**:
- 用户说"趋势"/"变化"/"走势"/"增长" → type="line"
- 用户说"对比"/"比较"/"排名" → type="bar"
- 用户说"占比"/"比例"/"份额"/"分布" → type="pie"
- 用户说"关系"/"相关"/"关联" → type="scatter"
- 用户说"异常"/"离群" → type="boxplot"
- 默认: type="bar"

2. **data_query** — 统计查询。args: {{"query": "describe|corr|groupby|sum|mean|max|min|count|std", "column": "列名", "groupby": "可选"}}

3. **hypothesis_test** — 验证假设。args: {{"statement": "假设陈述", "columns": ["列1"]}}

4. **story_graph** — 记录分析路径。args: {{"action": "advance|complete", "label": "标签", "question": "问题", "node_type": "overview|drill_down|conclusion"}}

5. **annotation_engine** — 图表标注。args: {{"text": "标注内容", "category": "insight|warning"}}

约束：
- 只能从以下 node_type 中选择：overview, trend_analysis, correlation_analysis, anomaly_detection, distribution_analysis, hypothesis_validation, conclusion, chart_generation, intent_response, drill_down
- 禁止创造新的 node_type
"""



# ═══════════════════════════════════════════════════════════════
# Fake LLM Mode — keyword-triggered preset responses (ReAct format)
# ═══════════════════════════════════════════════════════════════

FAKE_RESPONSES: dict[str, dict] = {
    # ── 趋势 / 折线 ──
    "趋势": {
        "reply": "根据数据的时间序列特征，我推荐使用折线图来展示趋势变化。可以看到整体呈现上升趋势，其中在中期有一个明显的增长加速阶段。",
        "thinking_label": "检测趋势模式",
        "reasoning": "用户提到趋势，数据中含日期/时间列，适合用折线图展示变化规律。选择 line 类型能清晰展示数据随时间的演变。",
        "confidence": {"level": "high", "score": 0.92},
        "action": {"tool": "chart_builder", "args": {"type": "line", "x": "", "y": [], "title": "趋势分析"}},
        "stop": False,
    },
    "折线": {
        "reply": "折线图是展示时序数据的最佳选择。我为你绘制了关键指标的变化曲线。",
        "thinking_label": "时序趋势分析",
        "reasoning": "用户请求折线图，line 类型适合展示数据随时间的变化规律。",
        "confidence": {"level": "high", "score": 0.90},
        "action": {"tool": "chart_builder", "args": {"type": "line", "x": "", "y": [], "title": "折线趋势图"}},
        "stop": False,
    },

    # ── 对比 / 柱状 ──
    "对比": {
        "reply": "对比分析最适合用柱状图来呈现。我选择了分组柱状图，可以直观比较各分类之间的数值差异。",
        "thinking_label": "多维对比分析",
        "reasoning": "用户想对比数据，分类列+数值列适合 grouped_bar。",
        "confidence": {"level": "high", "score": 0.88},
        "action": {"tool": "chart_builder", "args": {"type": "grouped_bar", "x": "", "y": [], "title": "对比分析"}},
        "stop": False,
    },
    "柱状": {
        "reply": "好的，我为你生成柱状图来对比各分类数据。",
        "thinking_label": "分类数值对比",
        "reasoning": "柱状图是分类对比的标准选择。",
        "confidence": {"level": "high", "score": 0.90},
        "action": {"tool": "chart_builder", "args": {"type": "bar", "x": "", "y": [], "title": "柱状对比图"}},
        "stop": False,
    },

    # ── 关联 / 散点 ──
    "关联": {
        "reply": "关联性分析使用散点图最合适。我先计算相关系数来量化关联强度。",
        "thinking_label": "探索变量关系",
        "reasoning": "用户想了解变量间关联，先查询相关性再生成散点图。",
        "confidence": {"level": "medium", "score": 0.75},
        "action": {"tool": "data_query", "args": {"query": "corr", "column": ""}},
        "stop": False,
    },
    "散点": {
        "reply": "散点图可以清晰展示两个变量之间的关系。",
        "thinking_label": "变量关系探索",
        "reasoning": "散点图用于两数值变量关系探索。",
        "confidence": {"level": "medium", "score": 0.78},
        "action": {"tool": "chart_builder", "args": {"type": "scatter", "x": "", "y": [], "title": "散点关系图"}},
        "stop": False,
    },

    # ── 异常 / 深挖 ──
    "异常": {
        "reply": "检测到数据中的异常点。我先用箱线图识别统计异常值。",
        "thinking_label": "异常值检测",
        "reasoning": "异常检测首选 boxplot 识别离群点。",
        "confidence": {"level": "medium", "score": 0.70},
        "action": {"tool": "chart_builder", "args": {"type": "boxplot", "x": "", "y": [], "title": "异常值检测"}},
        "stop": False,
    },
    "深挖": {
        "reply": "好的，我先做分组统计找出差异来源。",
        "thinking_label": "数据深挖分析",
        "reasoning": "深挖需要 data_query 分组找出差异。",
        "confidence": {"level": "medium", "score": 0.72},
        "action": {"tool": "data_query", "args": {"query": "groupby", "column": "", "groupby": ""}},
        "stop": False,
    },

    # ── 分布 ──
    "分布": {
        "reply": "数据分布分析使用直方图最直观。我展示了数值列的频率分布。",
        "thinking_label": "数据分布分析",
        "reasoning": "分布分析首选 histogram 展示数据集中趋势和离散程度。",
        "confidence": {"level": "high", "score": 0.85},
        "action": {"tool": "chart_builder", "args": {"type": "histogram", "x": "", "y": [], "title": "数据分布"}},
        "stop": False,
    },

    # ── 占比 ──
    "占比": {
        "reply": "占比分析用饼图最合适。我为你展示了各分类在整体中的比例。",
        "thinking_label": "数据占比分析",
        "reasoning": "占比分析用 pie 图展示比例关系。",
        "confidence": {"level": "high", "score": 0.90},
        "action": {"tool": "chart_builder", "args": {"type": "pie", "x": "", "y": [], "title": "占比分析"}},
        "stop": False,
    },
    "饼图": {
        "reply": "饼图是展示数据占比的经典选择。",
        "thinking_label": "构成比例展示",
        "reasoning": "用户请求饼图，pie 类型适合展示构成比例。",
        "confidence": {"level": "high", "score": 0.92},
        "action": {"tool": "chart_builder", "args": {"type": "pie", "x": "", "y": [], "title": "饼图分析"}},
        "stop": False,
    },

    # ── 综合 / 概览 ──
    "概览": {
        "reply": "我先看一下数据的整体统计情况。",
        "thinking_label": "数据概览分析",
        "reasoning": "概览从 describe 统计量开始，了解数据基本情况。",
        "confidence": {"level": "high", "score": 0.88},
        "action": {"tool": "data_query", "args": {"query": "describe", "column": ""}},
        "stop": False,
    },
}


def _match_fake_response(message: str) -> dict | None:
    """Keyword-based matching for Fake LLM mode. Returns preset response or None."""
    for keyword, response in FAKE_RESPONSES.items():
        if keyword in message:
            return response
    # Fallback: first word match or default
    for keyword, response in FAKE_RESPONSES.items():
        if len(keyword) >= 2 and keyword in message:
            return response
    # Default fallback
    return {
        "reply": "我理解你的需求，让我来帮你分析数据。我可以生成各种图表（折线图、柱状图、饼图、散点图等），也可以进行统计查询和深入分析。请告诉我你想看什么？",
        "thinking_label": "需求引导",
        "reasoning": "用户消息未匹配预设关键词，给出通用引导回复。",
        "confidence": {"level": "medium", "score": 0.60},
        "action": None,
        "stop": True,
    }


# ═══════════════════════════════════════════════════════════════
# ActionDispatcher — single-action executor (ReAct step)
# ═══════════════════════════════════════════════════════════════

class ActionDispatcher:
    """Execute a single tool call per ReAct step. Supports 5 tools."""

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager

    def execute_one(
        self,
        tool: str,
        args: dict,
        df: pd.DataFrame,
        state: AgentState,
        theme: str,
        chart_theme: str = "light",
        style_template: str = "clean",
        message: str = "",
    ) -> dict:
        """Execute a single tool call. Returns {"tool": ..., "ok": bool, "result": ..., "observation": str}."""
        entry: dict = {"tool": tool, "args": args, "ok": False, "result": None, "observation": ""}

        try:
            if tool == "chart_builder":
                # Plan is the sole authority on chart type.
                # Only fall back to "bar" if type is somehow still empty.
                if not args.get("type"):
                    args["type"] = "bar"
                entry["result"] = self._handle_chart_builder(
                    df, state, args, theme, chart_theme, style_template
                )
                entry["ok"] = True
                entry["observation"] = f"已生成图表: {args.get('type','?')} — {args.get('title','?')}"

            elif tool == "annotation_engine":
                entry["result"] = self._handle_annotation(state, args)
                entry["ok"] = True
                entry["observation"] = f"已添加标注: {args.get('text', '')[:50]}"

            elif tool == "story_graph":
                entry["result"] = self._handle_story_graph(state, args)
                entry["ok"] = True
                action = args.get("action", "?")
                entry["observation"] = f"分析图操作: {action} — {args.get('label', args.get('question', ''))[:50]}"

            elif tool == "data_query":
                entry["result"] = self._handle_data_query(df, args)
                entry["ok"] = True
                entry["observation"] = self._summarize_query_result(args, entry["result"])

            elif tool == "hypothesis_test":
                entry["result"] = self._handle_hypothesis_test(df, state, args)
                entry["ok"] = entry["result"].get("ok", False)
                entry["observation"] = entry["result"].get("observation", "假设验证完成")

            else:
                entry["result"] = f"未知工具: {tool}"
                entry["observation"] = f"未知工具: {tool}"

        except Exception as e:
            entry["ok"] = False
            entry["result"] = f"执行失败: {str(e)}"
            entry["error"] = str(e)
            entry["observation"] = f"{tool} 执行失败: {str(e)[:100]}"

        # Persist state after story_graph or hypothesis_test mutations
        if tool in ("story_graph", "hypothesis_test"):
            try:
                self.state_manager.save_state(state)
            except Exception:
                pass

        return entry

    def execute_one_typed(
        self,
        tool: str,
        args: dict,
        df: pd.DataFrame,
        state: AgentState,
        theme: str,
        chart_theme: str = "light",
        style_template: str = "clean",
        message: str = "",
    ):
        """Same as execute_one but returns ToolResult. Forward-compat for new code."""
        from services.tool_result import normalize_tool_result
        raw = self.execute_one(tool, args, df, state, theme, chart_theme, style_template, message)
        return normalize_tool_result(raw, tool)

    # ── hypothesis_test handler ──────────────────────────────

    def _handle_hypothesis_test(
        self,
        df: pd.DataFrame,
        state: AgentState,
        args: dict,
    ) -> dict:
        """Validate a hypothesis against data, then record in state."""
        statement = args.get("statement", "")
        columns = args.get("columns", [])

        if not statement:
            return {"ok": False, "observation": "假设陈述不能为空"}

        # Find matching columns and compute evidence
        evidence = {}
        matched_cols = []
        for col in df.columns:
            col_lower = col.lower()
            for ref in columns:
                if ref.lower() in col_lower or col_lower in ref.lower():
                    if col not in matched_cols:
                        matched_cols.append(col)

        for col in (matched_cols or df.select_dtypes(include=["number"]).columns[:3]):
            col_data = df[col].dropna()
            if len(col_data) > 0 and pd.api.types.is_numeric_dtype(col_data):
                evidence[col] = {
                    "mean": round(float(col_data.mean()), 2),
                    "std": round(float(col_data.std()), 2),
                    "min": round(float(col_data.min()), 2),
                    "max": round(float(col_data.max()), 2),
                    "n": len(col_data),
                }

        # Determine verdict based on evidence quality
        if len(evidence) >= 2:
            verdict = "confirmed"
            obs = f"假设已验证: '{statement[:60]}' — 找到 {len(evidence)} 个相关数据列: {list(evidence.keys())}"
            state.mark_explored(statement, f"数据验证通过，{len(evidence)}列相关", confidence=0.75)
        elif len(evidence) == 1:
            verdict = "partial"
            obs = f"假设部分验证: '{statement[:60]}' — 仅找到 1 个相关列 {list(evidence.keys())}，需更多数据"
            state.add_hypothesis(statement)
        else:
            verdict = "uncertain"
            obs = f"假设无法验证: '{statement[:60]}' — 当前数据中未找到明确相关列，建议换个角度"
            state.reject_path(statement, "当前数据无法验证")

        return {
            "ok": True,
            "verdict": verdict,
            "evidence": evidence,
            "observation": obs,
        }

    def _summarize_query_result(self, args: dict, result: dict) -> str:
        """Create a human-readable observation with interpretation hints."""
        query = args.get("query", "?")
        column = args.get("column", "")
        inner = result.get("result", {})

        if isinstance(result, dict) and "error" in result:
            return f"查询失败: {result['error']}"

        # ── describe → statistical overview + interpretation ──
        if query == "describe" and isinstance(inner, dict):
            parts = []
            interpretation = ""
            mean_val = None
            std_val = None
            count_val = None
            if "mean" in inner:
                mean_val = inner["mean"]
                parts.append(f"均值={mean_val:.2f}" if isinstance(mean_val, (int, float)) else f"均值={mean_val}")
            if "std" in inner:
                std_val = inner["std"]
                parts.append(f"标准差={std_val:.2f}" if isinstance(std_val, (int, float)) else "")
            if "count" in inner:
                count_val = inner["count"]
                parts.append(f"样本数={count_val}")
            if count_val is not None and count_val < 10:
                interpretation = " ⚡小样本(<10)，统计结论可信度有限"
            elif std_val is not None and mean_val is not None and isinstance(mean_val, (int, float)) and isinstance(std_val, (int, float)):
                cv = abs(std_val / mean_val) if mean_val != 0 else 0
                if cv > 0.5:
                    interpretation = f" ⚡变异系数={cv:.0%}，数据离散度高，可能有异常值"
                elif cv < 0.1:
                    interpretation = " 📌数据集中度高，差异不明显"
            return f"查询 describe {column}: {', '.join(parts)}{interpretation}"

        # ── corr → highlight strong correlations ──
        if query == "corr":
            if isinstance(inner, dict):
                # inner can be {col: {col: val}} (matrix) or {col: val} (single column)
                highlights = []
                for k, v in inner.items():
                    if isinstance(v, dict):
                        for k2, v2 in v.items():
                            if k != k2 and isinstance(v2, (int, float)) and abs(v2) > 0.5:
                                direction = "正" if v2 > 0 else "负"
                                highlights.append(f"{k}×{k2}: {direction}相关 r={v2:.2f}")
                    elif isinstance(v, (int, float)) and k != column and abs(v) > 0.3:
                        direction = "正" if v > 0 else "负"
                        highlights.append(f"{column}×{k}: {direction}相关 r={v:.2f}")
                if highlights:
                    return f"相关性: {'; '.join(highlights[:4])}"
                return f"相关性矩阵: 未发现强相关 (|r|>0.3)"
            return f"已计算相关性: {column or '全部数值列'}"

        # ── groupby → show top groups ──
        if query == "groupby":
            if isinstance(inner, dict) and "mean" in inner:
                means = inner["mean"]
                if isinstance(means, dict) and len(means) > 0:
                    sorted_items = sorted(means.items(), key=lambda x: -float(x[1]) if isinstance(x[1], (int, float)) else 0)
                    top_items = sorted_items[:3]
                    parts_str = ", ".join(f"{k}: avg={v}" if isinstance(v, (int, float)) else f"{k}={v}"
                                          for k, v in top_items)
                    return f"分组 {args.get('groupby', '?')} → {column}: Top3 {parts_str}" + (
                        f" (共{len(means)}组)" if len(means) > 3 else "")
            return f"分组统计完成: {args.get('groupby', '?')} → {column or '数值列'}"

        # ── simple aggregations ──
        if query in ("sum", "mean", "max", "min", "count", "std"):
            if isinstance(inner, dict):
                parts = [f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in list(inner.items())[:5]]
                return f"{query} {column}: {', '.join(parts)}"
            return f"{query} {column}: {inner}"

        return f"数据查询 {query} 完成: {column or ''}"

    # ── Tool handlers ─────────────────────────────────────────

    def _handle_chart_builder(
        self,
        df: pd.DataFrame,
        state: AgentState,
        args: dict,
        theme: str,
        chart_theme: str,
        style_template: str,
        _results: list | None = None,
    ) -> dict:
        """Build a chart via ChartBuilder."""
        chart_type = args.get("type", "bar")
        import builtins as _bi3
        try:
            with _bi3.open("C:/Users/admin/Desktop/excel-chart-tool/logs/debug.log","a",encoding="utf-8") as f:
                f.write(f"[DIAG] _handle_chart_builder ENTRY: type={chart_type}, x={args.get('x')}, y={args.get('y')}\n")
        except: pass
        x_column = args.get("x", "")
        y_columns = args.get("y", [])
        title = args.get("title", f"{chart_type} 图表")

        # Validate chart type
        if chart_type not in VALID_CHART_TYPES:
            raise ContractViolationError(
                f"Invalid chart_type '{chart_type}'. Valid types: {sorted(VALID_CHART_TYPES)}"
            )

        # Validate x_column
        if not x_column:
            available = [c.get("name", str(c)) for c in state.columns] if state.columns else list(df.columns)
            raise ContractViolationError(
                f"x_column is required but not specified. Available columns: {available}"
            )
        if x_column not in df.columns:
            available = list(df.columns)
            raise ContractViolationError(
                f"x_column '{x_column}' not found in DataFrame. Available columns: {available}"
            )

        # Validate y_columns
        if not y_columns:
            available = [c for c in df.columns if c != x_column]
            raise ContractViolationError(
                f"y_columns is required but empty. Available columns (excluding x_column): {available}"
            )
        invalid_y = [yc for yc in y_columns if yc not in df.columns]
        if invalid_y:
            available = list(df.columns)
            raise ContractViolationError(
                f"y_columns {invalid_y} not found in DataFrame. Available columns: {available}"
            )

        # Build chart
        builder = ChartBuilder()
        spec = builder.build_spec(
            df=df,
            chart_type=chart_type,
            x_column=str(x_column),
            y_columns=[str(yc) for yc in y_columns],
            title=title,
            theme=theme,
            chart_theme=chart_theme,
            style_template=style_template,
        )

        # Store in chart_memory
        import uuid
        chart_id = uuid.uuid4().hex[:12]
        state.chart_memory[chart_id] = {
            "spec": spec,
            "type": chart_type,
            "title": title,
            "x": x_column,
            "y": y_columns,
            "annotations": [],
            "created_at": time.time(),
        }

        # Update user preferences
        state.user_preferences.record_chart_use(chart_type)
        state.record_action("generate_chart", {"chart_type": chart_type, "x": x_column, "y": y_columns})

        return {
            "chart_id": chart_id,
            "chart_spec": spec,
            "chart_type": chart_type,
            "title": title,
        }

    def _handle_annotation(
        self,
        state: AgentState,
        args: dict,
        _results: list | None = None,
    ) -> dict:
        """Store annotation in chart_memory."""
        text = args.get("text", "")
        category = args.get("category", "insight")
        chart_id = args.get("chart_id", "")

        annotation = {
            "text": text,
            "category": category,
            "timestamp": time.time(),
        }

        # If chart_id specified, add to that chart's annotations
        if chart_id and chart_id in state.chart_memory:
            state.chart_memory[chart_id].setdefault("annotations", []).append(annotation)
        else:
            # Add to most recently created chart
            if state.chart_memory:
                latest_key = max(state.chart_memory.keys(),
                                 key=lambda k: state.chart_memory[k].get("created_at", 0))
                state.chart_memory[latest_key].setdefault("annotations", []).append(annotation)
            else:
                # Store as standalone
                state.chart_memory.setdefault("_annotations", []).append(annotation)

        state.record_action("annotate", {"text": text, "category": category})
        return {"annotation": annotation}

    def _handle_story_graph(
        self,
        state: AgentState,
        args: dict,
        _results: list | None = None,
    ) -> dict:
        """Advance / fork / backtrack the analysis story graph."""
        action = args.get("action", "advance")
        label = args.get("label", "")
        question = args.get("question", "")
        node_type_str = args.get("node_type", "overview")

        try:
            node_type = NodeType(node_type_str)
        except ValueError:
            node_type = NodeType.OVERVIEW

        graph = state.story_graph

        if action == "advance":
            node = AnalysisNode(
                type=node_type,
                label=label or question or "分析节点",
                question=question,
                parent_id=graph.current_id,
            )
            graph.add_node(node)
            graph.advance_to(node.id)

            # Track hypothesis
            if question:
                state.add_hypothesis(question, node.id)

            state.record_action("story_advance", {"label": label, "question": question, "node_id": node.id})
            return {"action": "advance", "node_id": node.id, "label": node.label}

        elif action == "fork":
            # Create fork branches from current node
            branches_args = args.get("branches", [])
            parent_id = graph.current_id or graph.root_id or ""
            branches = []
            for b in branches_args:
                bt = NodeType(b.get("node_type", "overview"))
                bn = AnalysisNode(
                    type=bt,
                    label=b.get("label", ""),
                    question=b.get("question", ""),
                )
                branches.append(bn)
            if branches and parent_id:
                graph.fork_from(parent_id, branches)
            state.record_action("story_fork", {"branches": len(branches)})
            return {"action": "fork", "branches": len(branches)}

        elif action == "backtrack":
            prev = graph.backtrack()
            if prev:
                state.record_action("story_backtrack", {"to_node": prev.id})
                return {"action": "backtrack", "node_id": prev.id}
            return {"action": "backtrack", "error": "无法回溯"}

        elif action == "complete":
            cur = graph.get_current()
            if cur:
                from models.agent_state import NodeStatus
                cur.status = NodeStatus.COMPLETED
                cur.completed_at = time.time()
                # Mark as explored
                if question:
                    state.mark_explored(question, label or "已完成分析", confidence=0.8)
                state.record_action("story_complete", {"node_id": cur.id})
                return {"action": "complete", "node_id": cur.id}
            return {"action": "complete", "error": "无当前节点"}

        else:
            return {"action": action, "error": f"未知 story_graph 操作: {action}"}

    def _handle_data_query(
        self,
        df: pd.DataFrame,
        args: dict,
        _results: list | None = None,
    ) -> dict:
        """Execute pandas statistical query on the dataframe."""
        query = args.get("query", "describe")
        column = args.get("column", "")
        groupby = args.get("groupby", "")

        try:
            if query == "describe":
                if column and column in df.columns:
                    result = df[column].describe().to_dict()
                else:
                    result = df.describe(include="all").to_dict()
                return {"query": query, "column": column, "result": result}

            elif query == "corr":
                numeric_df = df.select_dtypes(include=["number"])
                if len(numeric_df.columns) >= 2:
                    corr_matrix = numeric_df.corr().round(3)
                    if column and column in corr_matrix.columns:
                        result = corr_matrix[column].to_dict()
                    else:
                        result = corr_matrix.to_dict()
                else:
                    result = {"error": "需要至少2个数值列计算相关系数"}
                return {"query": query, "column": column, "result": result}

            elif query == "groupby":
                if groupby and groupby in df.columns:
                    if column and column in df.columns:
                        groupped = df.groupby(groupby)[column]
                        result = {
                            "mean": groupped.mean().round(2).to_dict(),
                            "sum": groupped.sum().round(2).to_dict(),
                            "count": groupped.count().to_dict(),
                            "std": groupped.std().round(2).to_dict(),
                            "max": groupped.max().round(2).to_dict(),
                            "min": groupped.min().round(2).to_dict(),
                        }
                    else:
                        result = {col: df.groupby(groupby)[col].mean().round(2).to_dict()
                                  for col in df.select_dtypes(include=["number"]).columns[:5]}
                else:
                    result = {"error": f"groupby 列 '{groupby}' 不存在或未指定"}
                return {"query": query, "groupby": groupby, "column": column, "result": result}

            elif query in ("sum", "mean", "max", "min", "count", "std"):
                if column and column in df.columns:
                    val = getattr(df[column], query)()
                    result = float(val) if pd.notna(val) else 0.0
                else:
                    numeric_df = df.select_dtypes(include=["number"])
                    result = {col: float(getattr(numeric_df[col], query)()) if pd.notna(getattr(numeric_df[col], query)()) else 0.0
                              for col in numeric_df.columns}
                return {"query": query, "column": column, "result": result}

            else:
                return {"query": query, "error": f"不支持的查询类型: {query}"}

        except Exception as e:
            return {"query": query, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# ToolTraceRecorder
# ═══════════════════════════════════════════════════════════════

class ToolTraceRecorder:
    """Records tool call execution traces via SessionLogger."""

    def __init__(self, logger: SessionLogger):
        self.logger = logger

    def record_step(self, tool: str, args: dict, result: dict, latency_ms: float):
        """Log a single ReAct step execution."""
        self.logger.log_action(
            action=f"react:{tool}",
            params=args,
            result="ok" if result.get("ok", False) else "error",
            extra={
                "tool": tool,
                "latency_ms": round(latency_ms, 1),
                "observation": str(result.get("observation", ""))[:300],
            },
        )

    def record_loop(self, step_count: int, total_latency_ms: float, tools_used: list[str]):
        """Log the entire ReAct loop completion."""
        self.logger.log_action(
            action="react_loop_complete",
            params={"steps": step_count, "tools": tools_used},
            result="ok",
            extra={"total_latency_ms": round(total_latency_ms, 1)},
        )


def _derive_thinking_label(action: dict | None, reasoning: str) -> str:
    """Derive a cognitive label for a single ReAct action."""
    if not action or not action.get("tool"):
        return "数据问题解答"

    tool = action.get("tool", "")
    args = action.get("args", {})

    if tool == "chart_builder":
        chart_type = args.get("type", "").replace("_", "")
        label_map = {
            "line": "时序趋势分析", "bar": "分类数值对比",
            "groupedbar": "多维对比分析", "stackedbar": "构成趋势分析",
            "scatter": "探索变量关系", "pie": "构成比例展示",
            "histogram": "数据分布分析", "boxplot": "异常值检测",
            "heatmap": "相关性热力图", "scattermatrix": "变量矩阵分析",
            "funnel": "漏斗转化分析", "treemap": "层级占比分析",
            "area": "面积趋势分析", "radar": "多维能力评估", "gauge": "指标达成展示",
        }
        return label_map.get(chart_type, "图表生成分析")

    if tool == "data_query":
        query = args.get("query", "")
        q_map = {"corr": "相关性检测", "describe": "数据统计概览", "groupby": "分组对比分析",
                 "sum": "汇总计算", "mean": "均值计算", "max": "最大值查询", "min": "最小值查询"}
        return q_map.get(query, "统计查询分析")

    if tool == "story_graph":
        action_type = args.get("action", "")
        sg_map = {"advance": "分析路径推进", "fork": "多路径探索",
                  "backtrack": "回溯重新分析", "complete": "分析结论归档"}
        return sg_map.get(action_type, "分析图操作")

    if tool == "annotation_engine":
        return "发现关键洞察"

    if tool == "hypothesis_test":
        return "验证分析假设"

    return "数据探索分析"


def _should_replan(step, observation: dict) -> bool:
    """Determine if current plan needs revision based on observation."""
    # Condition 1: action failed
    if not observation.get("ok", True):
        return True
    # Condition 2: high-confidence step produced low-confidence result
    step_conf = getattr(step, 'confidence', 0) if hasattr(step, 'confidence') else step.get('confidence', 0)
    obs_conf = observation.get('confidence', 0)
    if step_conf > 0.7 and obs_conf < 0.3:
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# ChatService
# ═══════════════════════════════════════════════════════════════

class ChatService:
    """Plan-then-Execute Agent (v3).

    Step 0: LLM generates an analysis plan (Plan Graph).
    Step 1+: Execute plan nodes, observe results, allow dynamic plan rewrite.
    Tool selection is constrained by node type (e.g. overview → data_query only).
    Reasoning decisions are recorded for future reference.
    """

    MAX_STEPS = 3
    STOP_CONFIDENCE = 0.85

    def __init__(
        self,
        state_manager: StateManager,
        chart_builder: ChartBuilder,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
    ):
        self.state_manager = state_manager
        self.chart_builder = chart_builder
        self.api_key = api_key or _get_api_key()
        self.model = model
        self.dispatcher = ActionDispatcher(state_manager)
        self.router = ConversationRouter()

    async def chat(
        self,
        message: str,
        session_id: str,
        state: AgentState,
        df: pd.DataFrame | None = None,
        theme: str = "business",
        chart_theme: str = "light",
        style_template: str = "clean",
        insights: list | None = None,
        insight_context: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Routed chat: ConversationRouter → execution_mode → handler."""
        logger = SessionLogger(session_id)
        t_start = time.time()

        # Route the query
        decision = self.router.route(message)
        _dlog(f"[ROUTE] '{message[:60]}' → {decision.route}/{decision.execution_mode}")

        # Dispatch by execution_mode
        if decision.execution_mode == "single_reply":
            async for event in self._handle_greeting(message, logger, t_start):
                yield event
        elif decision.execution_mode == "direct_tool":
            async for event in self._handle_direct_tool(
                message, df, state, decision, theme, chart_theme, style_template, logger, t_start
            ):
                yield event
        else:  # react (analysis) — delegated to AnalysisOrchestrator
            from services.analysis_orchestrator import AnalysisOrchestrator
            from services.tool_result import SSEEvent as Evt
            orchestrator = AnalysisOrchestrator(self.dispatcher, self.api_key, self.model)
            async for evt in orchestrator.run(
                message=message,
                session_id=session_id,
                state=state,
                df=df,
                theme=theme,
                chart_theme=chart_theme,
                style_template=style_template,
            ):
                if isinstance(evt, Evt):
                    yield {"event": evt.type, "data": evt.payload}
                else:
                    yield evt  # backward compat for old-style dict events

    # ── Handler: greeting ────────────────────────────────────

    async def _handle_greeting(self, message: str, logger: SessionLogger, t_start: float):
        """Single LLM reply for greeting queries. No ReAct, no tools."""
        system_prompt = "你是 AI 图表助手。用户只是在打招呼，请简短友好地回复，1-2句话即可。"
        user_prompt = f"用户说：「{message}」"

        content, _, _, _ = await self._call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            logger=logger,
        )
        yield {"event": "narrative", "data": {"content": content}}
        yield {"event": "done", "data": {"latency_ms": round((time.time() - t_start) * 1000, 1), "steps": 0}}

    # ── Handler: direct_tool ─────────────────────────────────

    async def _handle_direct_tool(self, message: str, df, state, decision: RouteDecision,
                                   theme: str, chart_theme: str, style_template: str,
                                   logger: SessionLogger, t_start: float):
        """Direct tool execution — no ReAct loop, single tool call."""

        # No data guard
        if df is None or df.empty:
            content = "请先上传一个 Excel 或 CSV 文件，我就能帮你分析了。"
            yield {"event": "narrative", "data": {"content": content}}
            yield {"event": "done", "data": {"latency_ms": round((time.time() - t_start) * 1000, 1), "steps": 0}}
            return

        route = decision.route
        tools_used = []

        if route == "direct_visualization":
            # Use MiniChartPlanner to infer args
            chart_args = plan_chart(message, state.columns)
            # Merge with entities from router
            if decision.entities.get("chart_type"):
                chart_args["chart_type"] = decision.entities["chart_type"]

            from services.execution_contract import contract_entry

            inp = {
                "args": {
                    "type": chart_args.get("chart_type", "bar"),
                    "x": chart_args.get("x_column", ""),
                    "y": chart_args.get("y_columns", []),
                    "title": chart_args.get("title", ""),
                },
                "df": df,
                "columns": state.columns,
                "message": message,
                "policy": "strict",
            }
            ce_result = contract_entry(inp)

            if ce_result["status"] == "rejected":
                yield {"event": "error", "data": {"message": "图表生成被拒绝"}}
                yield {"event": "done", "data": {"latency_ms": 0, "steps": 0}}
                return

            args = {
                "type": ce_result["chart_type"],
                "x": ce_result["x"],
                "y": ce_result["y"],
                "title": ce_result["title"],
            }

            result = self.dispatcher.execute_one(
                tool="chart_builder", args=args, df=df, state=state,
                theme=theme, chart_theme=chart_theme, style_template=style_template,
                message=message,
            )
            tools_used.append("chart_builder")

            if result.get("ok"):
                rd = result.get("result", {})
                if isinstance(rd, dict) and rd.get("chart_spec"):
                    # Yield narrative BEFORE chart (narrative-first)
                    chart_type_cn = {"line": "趋势图", "bar": "柱状图", "pie": "饼图", "scatter": "散点图"}.get(
                        chart_args["chart_type"], chart_args["chart_type"]
                    )
                    yield {
                        "event": "narrative",
                        "data": {"content": f"好的，我为你生成{chart_type_cn}来展示数据。"}
                    }
                    yield {
                        "event": "action",
                        "data": {
                            "chart_spec": rd["chart_spec"],
                            "chart_type": chart_args["chart_type"],
                            "chart_id": rd.get("chart_id", ""),
                            "title": rd.get("title", chart_args.get("title", "")),
                            "x_column": chart_args["x_column"],
                            "y_columns": chart_args["y_columns"],
                            "columns": state.columns,
                            "row_count": state.row_count,
                        },
                    }
                    # Unified analysis
                    state.add_finding("chart", rd.get("title", "") or f"{chart_args['chart_type']}图表",
                                      source="react", confidence=0.85, chart_type=chart_args["chart_type"])
            else:
                yield {"event": "error", "data": {"message": f"图表生成失败: {result.get('result', '未知错误')}"}}

        elif route == "data_quality":
            # Run data_query to check data quality
            result = self.dispatcher.execute_one(
                tool="data_query", args={"query": "describe"}, df=df, state=state,
                theme=theme, chart_theme=chart_theme, style_template=style_template,
            )
            tools_used.append("data_query")

            obs = result.get("observation", "")
            yield {"event": "narrative", "data": {"content": obs or "数据质量检查完成。"}}
            # NO chart fallback for data_quality

        yield {"event": "done", "data": {"latency_ms": round((time.time() - t_start) * 1000, 1), "steps": len(tools_used)}}

    # ── Handler: analysis (ReAct loop) ────────────────────────

    async def _handle_analysis(self, message, session_id, state, df, theme, chart_theme,
                                style_template, insights, insight_context, logger, t_start, decision):
        """Full ReAct loop for analysis queries."""
        recorder = ToolTraceRecorder(logger)
        observations = []
        step_context = []
        tools_used = []

        # ── Yield insight cards first (if provided) ──
        if insights:
            yield {"event": "synthesis", "data": {"insights": _serialize_insights(insights), "count": len(insights)}}

        # ── Auto InsightEngine ──
        auto_insight_context = ""
        exploration_keywords = ["分析", "看看", "有什么发现", "insight", "趋势", "探索", "发现"]
        should_run_engine = (df is not None and not df.empty and any(kw in message for kw in exploration_keywords))
        if should_run_engine:
            try:
                from services.insight_engine import InsightEngine
                engine = InsightEngine()
                result = engine.run(df, context={"source": "chat"})
                top = result.get("top_insights", [])
                if top:
                    lines = []
                    for i, ins in enumerate(top[:3]):
                        ins_type = ins.representative.type if hasattr(ins, 'representative') else ins.get('type', '')
                        ins_title = ins.representative.title if hasattr(ins, 'representative') else ins.get('title', '')
                        ins_desc = ins.representative.description if hasattr(ins, 'representative') else ins.get('description', '')
                        lines.append(f"{i+1}. [{ins_type}] {ins_title}: {ins_desc}")
                    if lines:
                        auto_insight_context = "\\n".join(lines)
                        auto_insight_context += "\\n\\n请基于以上洞察规划分析步骤。"
            except Exception:
                pass

        # ── No-data check ──
        if df is None or df.empty:
            content = "请先上传一个 Excel 或 CSV 数据文件，我就能帮你分析了！"
            yield {"event": "narrative", "data": {"content": content}}
            yield {"event": "done", "data": {"latency_ms": round((time.time() - t_start) * 1000, 1), "steps": 0}}
            return

        # ── Bounded ReAct Loop ──
        for step in range(self.MAX_STEPS):
            # Build prompt with current observations + decision memory + auto insights
            system_prompt = _build_system_prompt(
                state, step, observations, step_context,
                insight_context=auto_insight_context if step == 0 else None,
            )

            # Inject insight follow-up context
            if step == 0 and insight_context:
                ctx_title = insight_context.get("title", "")
                ctx_type = insight_context.get("type", "")
                ctx_cols = insight_context.get("columns", [])
                system_prompt += (
                    f"\\n【用户正在追问洞察】\\n"
                    f"洞察: {ctx_title}\\n类型: {ctx_type}\\n相关列: {ctx_cols}\\n"
                )

            # ── LLM Call ──
            if USE_FAKE_LLM:
                fake_resp = _match_fake_response(message)
                if not state.plan_generated and step == 0:
                    # Step 0: generate a plan
                    fake_resp["analysis_plan"] = [
                        {"id": "overview", "node_type": "overview", "label": "数据概览", "tool": "data_query", "status": "pending"},
                        {"id": "chart", "node_type": "trend_analysis", "label": "生成图表", "tool": "chart_builder", "status": "pending"},
                        {"id": "conclusion", "node_type": "conclusion", "label": "总结发现", "tool": "annotation_engine", "status": "pending"},
                    ]
                elif step > 0:
                    fake_resp = {
                        "reply": "基于分析结果，我认为已经充分回答了你的问题。",
                        "thinking_label": "分析完成",
                        "reasoning": "FakeLLM: 计划执行完毕。",
                        "confidence": {"level": "high", "score": 0.90},
                        "action": None,
                        "stop": True,
                    }
                llm_raw = json.dumps(fake_resp, ensure_ascii=False)
                llm_latency_ms = 1.0
                tokens_in = len(message)
                tokens_out = len(llm_raw)
            else:
                if not self.api_key:
                    yield {"event": "error", "data": {"message": "未配置 DEEPSEEK_API_KEY"}}
                    yield {"event": "done", "data": {}}
                    return

                try:
                    llm_raw, tokens_in, tokens_out, llm_latency_ms = await self._call_llm(
                        system_prompt, message, logger
                    )
                except Exception as e:
                    logger.log_error(action="llm_call", error=str(e),
                                     traceback=traceback.format_exc(),
                                     context={"message": message[:200], "step": step})
                    yield {"event": "error", "data": {"message": f"LLM 调用失败: {str(e)}"}}
                    yield {"event": "done", "data": {}}
                    return

            # ── Parse ──
            parsed = self._parse_llm_response(llm_raw, logger)
            if parsed is None:
                yield {"event": "narrative", "data": {"content": llm_raw[:500]}}
                continue

            reply = parsed.get("reply", "")
            reasoning = parsed.get("reasoning", "")
            action = parsed.get("action")
            stop = parsed.get("stop", False)
            thinking_label = parsed.get("thinking_label", "") or _derive_thinking_label(action, reasoning)
            confidence_data = parsed.get("confidence", {})
            conf_score = float(confidence_data.get("score", 0.5))

            # ── Plan Generation (Step 0 or plan not yet generated) ──
            analysis_plan = parsed.get("analysis_plan")
            if analysis_plan and isinstance(analysis_plan, list) and not state.plan_generated:
                state.set_plan(analysis_plan)
                if not thinking_label:
                    thinking_label = "制定分析计划"

                # ── Phase 3: Convert to PlanStep objects & validate ──
                try:
                    from services.plan_validator import validate_plan
                    plan_steps = []
                    for i, ps in enumerate(analysis_plan):
                        plan_steps.append(PlanStep(
                            id=ps.get("id", i) if isinstance(ps.get("id"), int) else i,
                            goal=ps.get("label", ps.get("goal", "")),
                            node_type=ps.get("node_type", "intent_response"),
                            params=ps.get("params", {}),
                            status="pending",
                            confidence=ps.get("confidence", 0.0),
                        ))
                    state.set_plan_steps(plan_steps)

                    # Validate plan
                    validation_errors = validate_plan(
                        plan_steps, state.columns, VALID_CHART_TYPES, NODE_TOOLS
                    )
                    if validation_errors:
                        yield {
                            "event": "error",
                            "data": {
                                "message": "计划验证发现问题: " + "; ".join(validation_errors[:3]),
                                "validation_errors": validation_errors,
                            },
                        }
                except Exception:
                    pass  # PlanStep/validation is enhancement, don't break flow

            # ── Plan Rewrite (dynamic adjustment) ──
            plan_rewrite = parsed.get("plan_rewrite")
            if plan_rewrite and isinstance(plan_rewrite, list) and state.plan_generated:
                state.rewrite_plan(plan_rewrite, insert_after_current=True)

            # Yield text reply
            if reply:
                yield {"event": "narrative", "data": {"content": reply}}

            # ── Build & yield thinking trace ──
            conf_level_str = confidence_data.get("level", "medium")
            try:
                conf_level = ConfidenceLevel(conf_level_str)
            except ValueError:
                conf_level = ConfidenceLevel.MEDIUM

            thinking_trace = ThinkingTrace(
                level1=f"[Step {step + 1}] {thinking_label}",
                level2=[reasoning] if reasoning else [],
                level3={
                    "model": self.model,
                    "step": step + 1,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "latency_ms": round(llm_latency_ms, 1),
                },
                confidence=conf_level,
                confidence_score=conf_score,
            )
            state.add_thinking_trace(thinking_trace)
            yield {"event": "reasoning", "data": thinking_trace.to_dict()}

            # ── Execute action ──
            if action and action.get("tool") and df is not None and not df.empty:
                tool = action.get("tool", "")
                args = action.get("args", {})
                # ── Normalize LLM output ──
                if "y" in args and isinstance(args["y"], str):
                    args["y"] = [args["y"]]
                if "type" in args and args["type"] is None:
                    args["type"] = "bar"

                # Tool policy enforcement
                if tool not in decision.tool_policy or not decision.tool_policy[tool].get("enabled", True):
                    logger.log_error(action="tool_policy_blocked", error=f"Tool '{tool}' blocked by policy", context={"route": decision.route})
                    continue

                tools_used.append(tool)

                result = self.dispatcher.execute_one(
                    tool=tool, args=args, df=df, state=state,
                    theme=theme, chart_theme=chart_theme, style_template=style_template,
                    message=message,
                )

                recorder.record_step(tool, args, result, llm_latency_ms)

                obs = result.get("observation", "")
                observations.append(obs)
                step_context.append((reply[:200], obs[:200]))

                # Advance plan if executing the current step
                if state.plan_generated:
                    state.advance_plan(reasoning)

                # ── Phase 3: PlanStep tracking & replan check ──
                current_step = state.get_current_step()
                if current_step is not None:
                    if result.get("ok"):
                        state.mark_step_done(current_step.id, result.get("result", {}))
                    else:
                        state.mark_step_failed(current_step.id, result.get("error", "执行失败"))

                    # Check if replan needed
                    if _should_replan(current_step, result):
                        yield {
                            "event": "narrative",
                            "data": {
                                "content": "计划需要调整，正在重新评估分析路径..."
                            },
                        }
                        # Mark remaining steps and regenerate plan
                        remaining = state.replan_steps()
                        if remaining:
                            for s in remaining:
                                state.mark_step_failed(s.id, "计划调整")
                        # Signal plan rewrite — next iteration will regenerate
                        state.plan_generated = False

                # Yield chart action event
                if tool == "chart_builder" and result.get("ok"):
                    rd = result.get("result", {})
                    if isinstance(rd, dict) and rd.get("chart_spec"):
                        yield {
                            "event": "action",
                            "data": {
                                "chart_spec": rd["chart_spec"],
                                "chart_type": rd.get("chart_type", ""),
                                "chart_id": rd.get("chart_id", ""),
                                "title": rd.get("title", ""),
                                "x_column": rd.get("x", ""),
                                "y_columns": rd.get("y", []),
                                "columns": state.columns,
                                "row_count": state.row_count,
                            },
                        }

                        # ── Unified Analysis: record chart finding ──
                        chart_type = rd.get("chart_type", "bar")
                        title = rd.get("title", "")
                        state.add_finding(
                            finding_type="chart",
                            content=title or f"{chart_type}图表",
                            source="react",
                            confidence=conf_score,
                            chart_type=chart_type,
                        )

                # Yield error if tool failed
                if not result.get("ok"):
                    yield {
                        "event": "error",
                        "data": {
                            "message": f"工具 {tool} 执行失败: {result.get('result', '未知错误')}",
                            "tool": tool,
                        },
                    }

            # ── Stop conditions ──
            if stop or conf_score >= self.STOP_CONFIDENCE:
                break

        # ── Fallback: if no chart was generated, auto-generate one ──
        # Skip for data-quality queries (missing values, data types, etc.)
        _quality_kw = ["残缺", "缺失", "空值", "null", "na ", "数据质量", "检查数据", "有几列", "数据类型"]
        _skip_fallback = any(kw in message for kw in _quality_kw)
        if "chart_builder" not in tools_used and df is not None and not df.empty and not _skip_fallback:
            result = self.dispatcher.execute_one(
                tool="chart_builder", args={}, df=df, state=state,
                theme=theme, chart_theme=chart_theme, style_template=style_template,
            )
            if result.get("ok"):
                rd = result.get("result", {})
                if isinstance(rd, dict) and rd.get("chart_spec"):
                    yield {
                        "event": "action",
                        "data": {
                            "chart_spec": rd["chart_spec"],
                            "chart_type": rd.get("chart_type", "bar"),
                            "chart_id": rd.get("chart_id", ""),
                            "title": rd.get("title", "数据概览"),
                            "x_column": rd.get("x", ""),
                            "y_columns": rd.get("y", []),
                            "columns": state.columns,
                            "row_count": state.row_count,
                        },
                    }
                    tools_used.append("chart_builder")

                    # ── Unified Analysis: record fallback chart finding ──
                    chart_type = rd.get("chart_type", "bar")
                    title = rd.get("title", "")
                    state.add_finding(
                        finding_type="chart",
                        content=title or f"{chart_type}图表",
                        source="react",
                        confidence=0.7,
                        chart_type=chart_type,
                    )
                    # Add a thinking trace for the fallback
                    state.add_thinking_trace(ThinkingTrace(
                        level1="[Auto] 自动生成图表",
                        level2=["基于数据探索结果自动生成可视化"],
                        level3={"model": self.model, "auto": True},
                        confidence=ConfidenceLevel.HIGH,
                        confidence_score=0.85,
                    ))

        # ── Persist & record ──
        recorder.record_loop(len(tools_used), (time.time() - t_start) * 1000, tools_used)
        try:
            self.state_manager.save_state(state)
        except Exception:
            pass

        total_latency = (time.time() - t_start) * 1000
        yield {"event": "done", "data": {"latency_ms": round(total_latency, 1), "steps": len(tools_used)}}

    # ── LLM Call ──────────────────────────────────────────────

    async def _call_llm(
        self,
        system_prompt: str,
        user_message: str,
        logger: SessionLogger,
    ) -> tuple[str, int, int, float]:
        """Call DeepSeek API and return (content, tokens_in, tokens_out, latency_ms)."""
        t0 = time.time()

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"API 返回 {resp.status}: {error_text[:300]}")

                data = await resp.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")

                usage = data.get("usage", {})
                tokens_in = usage.get("prompt_tokens", 0)
                tokens_out = usage.get("completion_tokens", 0)

        latency_ms = (time.time() - t0) * 1000

        logger.log_prompt(
            action="react_step",
            model=self.model,
            prompt=system_prompt[:1000] + "\n\n[USER]\n" + user_message[:500],
            response=content[:1000],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )

        return content, tokens_in, tokens_out, latency_ms

    # ── JSON Parsing ──────────────────────────────────────────

    def _parse_llm_response(self, raw: str, logger: SessionLogger) -> dict | None:
        """Try to parse LLM output as JSON. Returns None on failure."""
        raw = raw.strip()

        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.log_error(
            action="parse_llm_json",
            error="无法将 LLM 响应解析为 JSON",
            context={"raw_preview": raw[:500]},
        )
        return None
