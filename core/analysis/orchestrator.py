"""Analysis Orchestrator — plan → execute → trace → synthesize.

Orchestrates the full analysis pipeline: InputGate → Plan → Execute → Synthesize.
Yields SSEEvent objects for streaming consumption.
"""

from __future__ import annotations
import os
_DEBUG_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "debug.log")
from typing import AsyncGenerator
import json, os, re, time, traceback
import aiohttp
import pandas as pd

from models.agent_state import (
    AgentState, ThinkingTrace, ConfidenceLevel,
    AnalysisNode, NodeType, PlanStep
)
from core.tool_result import SSEEvent
from state.logger import SessionLogger
from core.routing.gate import InputGate
from core.planning.pruner import PlanPruner
from core.planning.budget import BudgetController
from core.contract.guard import ExecutionGuard
from core.chart.selector import select_chart_type_with_context, select_chart_type

API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"

MAX_STEPS = 8
TRACE_LIMIT = 200
MAX_NARRATIVE_CHARS = 800
NARRATIVE_SIMILARITY_THRESHOLD = 0.85


def _reorder(plan: list) -> list:
    """Pure function. chart_builder MUST run before annotation_engine.
    Returns NEW list, does NOT mutate input."""
    chart_steps = [s for s in plan if s.tool == "chart_builder"]
    anno_steps = [s for s in plan if s.tool == "annotation_engine"]
    other_steps = [s for s in plan if s.tool not in ("chart_builder", "annotation_engine")]
    return chart_steps + other_steps + anno_steps


VALID_CHART_TYPES = {"line", "bar", "scatter", "histogram", "pie", "boxplot"}
NODE_TOOLS = {
    "overview": ["data_query", "chart_builder"],
    "trend_analysis": ["chart_builder", "data_query"],
    "correlation_analysis": ["chart_builder"],
    "distribution_analysis": ["chart_builder", "data_query"],
    "anomaly_detection": ["chart_builder", "hypothesis_test"],
    "hypothesis_validation": ["hypothesis_test", "chart_builder"],
    "conclusion": ["annotation_engine"],
    "intent_response": ["data_query", "chart_builder"],
}


def _get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def validate_plan_graph(plan: list[PlanStep]) -> list[str]:
    errors = []
    step_ids = {s.id for s in plan}
    for s in plan:
        for dep in s.depends_on:
            if dep not in step_ids:
                errors.append(f"步骤 {s.id} 依赖不存在的步骤 {dep}")
        if s.tool and s.tool not in {
            "chart_builder", "data_query", "annotation_engine", "hypothesis_test"
        }:
            errors.append(f"步骤 {s.id} 使用了未知工具: {s.tool}")
    return errors


def summarize_old_traces(traces: list[dict], max_chars: int = 300) -> str:
    if not traces:
        return ""
    lines = []
    total = 0
    for t in reversed(traces):
        line = f"[{t.get('level1', '')}]: {t.get('level2', [''])[0][:80]}"
        total += len(line)
        if total > max_chars:
            lines.append("...(更早的步骤省略)")
            break
        lines.append(line)
    return "\n".join(reversed(lines))


import builtins as _bi2
try:
    with _bi2.open(_DEBUG_LOG,"a",encoding="utf-8") as f:
        f.write("[ORCH_IMPORT] analysis_orchestrator loaded v2\n")
except: pass
# DEBUG: force a deliberate side effect
_bi2.open(_DEBUG_LOG,"a",encoding="utf-8").write("[ORCH_MODULE] module loaded at top level\n")

class AnalysisOrchestrator:
    """Plan → Execute → Trace → Synthesize. Yields SSEEvent objects."""

    def __init__(self, dispatcher, api_key: str = "", model: str = DEFAULT_MODEL):
        self.dispatcher = dispatcher
        self.api_key = api_key or _get_api_key()
        self.model = model

    # ── Public API ────────────────────────────────────────────

    async def run(
        self,
        message: str,
        session_id: str,
        state: AgentState,
        df: pd.DataFrame | None = None,
        theme: str = "business",
        chart_theme: str = "light",
        style_template: str = "clean",
    ) -> AsyncGenerator[SSEEvent, None]:
        _dl2 = _bi2
        try:
            with _dl2.open(_DEBUG_LOG,"a",encoding="utf-8") as f:
                f.write(f"[ORCH_RUN] message={message[:50]}\n")
        except: pass
        logger = SessionLogger(session_id)
        t_start = time.time()

        if df is None or df.empty:
            yield SSEEvent(type="narrative", payload={"content": "请先上传数据文件。"})
            yield SSEEvent(type="done", payload={"latency_ms": 0, "steps": 0})
            return

        gate = InputGate()
        gate_result = gate.validate(message, df, state.columns)
        if not gate_result["pass"]:
            yield SSEEvent(type="narrative", payload={"content": gate_result["reason"]})
            yield SSEEvent(type="done", payload={"latency_ms": 0, "steps": 0})
            return

        state.analysis_trace = []
        state.set_plan([])

        plan = await self._generate_plan(message, df, state, logger)
        if not plan:
            yield SSEEvent(type="error", payload={"message": "无法生成分析计划"})
            yield SSEEvent(type="done", payload={"latency_ms": 0, "steps": 0})
            return

        # Invariant: all plans (LLM/fallback/direct) must pass reorder
        plan = _reorder(plan)

        errors = validate_plan_graph(plan)
        if errors:
            yield SSEEvent(type="narrative", payload={
                "content": f"计划调整中: {'; '.join(errors[:2])}"
            })
            for s in plan:
                s.depends_on = []

        pruner = PlanPruner()
        plan = pruner.prune(plan)

        budget_ctrl = BudgetController()
        chart_budget = budget_ctrl.get_budget(df, state.columns)

        state.set_plan([{
            "id": p.id, "goal": p.goal, "tool": p.tool,
            "depends_on": p.depends_on,
            "chart_hint": p.chart_hint, "narrative_hint": p.narrative_hint,
            "status": "pending"
        } for p in plan])

        tools_used: list[str] = []
        total_steps = 0
        chart_count = 0
        guard = ExecutionGuard()
        completed_steps: list = []
        prev_narrative = ""

        for step_idx, step in enumerate(plan):
            total_steps += 1
            if total_steps > MAX_STEPS:
                break

            guard_result = guard.check(step, completed_steps, chart_count)
            if not guard_result["allow"]:
                step.status = "skipped"
                continue

            step.status = "running"

            # ── chart_builder: deterministic path (v10 contract) ──
            if step.tool == "chart_builder" and df is not None:
                from core.contract.v10_contract import resolve
                from core.ir.contract import AnalysisIntent
                from core.profiling.profiler import DataProfiler
                from core.profiling.transformer import StateTransformer

                # Build profile + context
                profile = DataProfiler.enhance(state.columns, df)
                ctx = StateTransformer.transform(profile, None, df)
                intent = AnalysisIntent(
                    type="overview",
                    confidence=0.7,
                    explicit_chart=step.chart_hint if step.chart_hint else None,
                )
                decision, ledger = resolve(ctx, intent)

                # Save ledger to state
                state.ledger = ledger
                try:
                    from state.manager import StateManager
                except Exception:
                    pass

                ce_result = {
                    "chart_type": decision.chart_type,
                    "x": decision.x_column,
                    "y": decision.y_columns,
                    "title": decision.title,
                    "status": "approved" if not decision.is_none() else "rejected",
                    "trace_id": profile.hash,
                    "narratives": [],
                    "explanation": [f"v10 rule: {ledger.steps[-1].rule_applied if ledger.steps else 'n/a'}"],
                    "_locked": True,
                }
                tools_used.append("chart_builder")
                _dl(f"[V10] contract status={ce_result['status']} type={ce_result['chart_type']} because={ledger.steps[-1].rule_applied if ledger.steps else 'n/a'}")

                # Record structured artifact (PENDING until execution confirms)
                from models.agent_state import ChartArtifact, ArtifactStatus
                artifact = ChartArtifact(
                    step_id=step.id,
                    chart_type=ce_result["chart_type"],
                    x_column=ce_result["x"],
                    y_columns=ce_result["y"],
                    title=ce_result["title"],
                    resolved_by="v10_contract",
                    source_step="chart_builder",
                    status=ArtifactStatus.PENDING,
                )
                state.add_artifact(artifact)

                args = {
                    "type": ce_result["chart_type"],
                    "x": ce_result["x"],
                    "y": ce_result["y"],
                    "title": ce_result["title"],
                }

                for n in ce_result["narratives"]:
                    if not _is_narrative_dup(n, prev_narrative):
                        yield SSEEvent(type="narrative", payload={"content": n})
                        prev_narrative = n

                if ce_result["status"] == "rejected":
                    reason = ledger.steps[-1].rule_applied if ledger.steps else "无法确定图表类型"
                    advice = "数据中缺少数值列或分类列。请上传包含数值/日期/分类字段的数据。"
                    yield SSEEvent(type="error", payload={"message": f"{reason}。{advice}"})
                    step.status = "failed"
                    continue

                _dl(f"[DIAG] final args to execute_one: type={args.get('type')}, x={args.get('x')}, y={args.get('y')}")
                exe_result = self.dispatcher.execute_one(
                    tool="chart_builder", args=args, df=df, state=state,
                    theme=theme, chart_theme=chart_theme, style_template=style_template,
                    message=message,
                )

                if exe_result.get("ok"):
                    artifact.status = ArtifactStatus.APPROVED if ce_result["status"] == "approved" else ArtifactStatus.DEGRADED
                    rd = exe_result.get("result", {})
                    if isinstance(rd, dict) and rd.get("chart_spec"):
                        chart_count += 1
                        yield SSEEvent(type="action", payload={
                            "chart_spec": rd["chart_spec"],
                            "chart_type": rd.get("chart_type", ""),
                            "chart_id": rd.get("chart_id", ""),
                            "title": rd.get("title", ""),
                            "x_column": rd.get("x", ""),
                            "y_columns": rd.get("y", []),
                            "columns": state.columns,
                            "row_count": state.row_count,
                        })

                    # LLM narrative — describe data, NOT chart type
                    narrative = await self._narrate(ce_result, df, state, message, logger)
                    if narrative and not _is_narrative_dup(narrative, prev_narrative):
                        yield SSEEvent(type="narrative", payload={"content": narrative})
                        prev_narrative = narrative
                else:
                    artifact.status = ArtifactStatus.FAILED
                    yield SSEEvent(type="error", payload={"message": "图表生成失败"})

                step.status = "done"
                completed_steps.append(step)
                continue

            # ── non-chart_builder: LLM-driven path ──

            # For annotation_engine: strip prev_narrative to avoid chart-type contamination
            clean_prev = prev_narrative if step.tool != "annotation_engine" else ""
            system_prompt = self._build_step_prompt(state, step, step_idx, plan, clean_prev)

            try:
                llm_raw, tokens_in, tokens_out, latency_ms = await self._call_llm(
                    system_prompt, message, logger
                )
            except Exception as e:
                yield SSEEvent(type="error", payload={"message": f"LLM 调用失败: {e}"})
                step.status = "failed"
                continue

            parsed = self._parse_llm_response(llm_raw, logger)
            if parsed is None:
                yield SSEEvent(type="narrative", payload={"content": llm_raw[:300]})
                step.status = "failed"
                continue

            reply = parsed.get("reply", "") or parsed.get("narrative", "")
            action = parsed.get("action")
            import builtins as _bi
            def _dl(msg):
                try:
                    with _bi.open(_DEBUG_LOG,"a",encoding="utf-8") as f:
                        f.write(msg+"\n")
                except: pass

            # For non-chart_builder steps: yield narrative immediately
            is_chart_step = action and action.get("tool") == "chart_builder"
            if not is_chart_step and reply and not _is_narrative_dup(reply, prev_narrative):
                yield SSEEvent(type="narrative", payload={"content": reply})
                prev_narrative = reply

            if action and action.get("tool") and df is not None:
                tool = action["tool"]
                args = action.get("args", {})
                tools_used.append(tool)

                if reply and not _is_narrative_dup(reply, prev_narrative):
                    yield SSEEvent(type="narrative", payload={"content": reply})
                    prev_narrative = reply

                _dl(f"[DIAG] final args to execute_one: type={args.get('type')}, x={args.get('x')}, y={args.get('y')}")
                result = self.dispatcher.execute_one(
                    tool=tool, args=args, df=df, state=state,
                    theme=theme, chart_theme=chart_theme, style_template=style_template,
                    message=message,
                )

                if result.get("ok") and tool == "chart_builder":
                    rd = result.get("result", {})
                    if isinstance(rd, dict) and rd.get("chart_spec"):
                        chart_count += 1
                        yield SSEEvent(type="action", payload={
                            "chart_spec": rd["chart_spec"],
                            "chart_type": rd.get("chart_type", ""),
                            "chart_id": rd.get("chart_id", ""),
                            "title": rd.get("title", ""),
                            "x_column": rd.get("x", ""),
                            "y_columns": rd.get("y", []),
                            "columns": state.columns,
                            "row_count": state.row_count,
                        })
                elif not result.get("ok"):
                    yield SSEEvent(type="error", payload={
                        "message": f"工具 {tool} 执行失败"
                    })

                step.status = "done" if result.get("ok") else "failed"
                completed_steps.append(step)
            else:
                step.status = "done"
                completed_steps.append(step)

        total_latency = (time.time() - t_start) * 1000
        yield SSEEvent(type="done", payload={
            "latency_ms": round(total_latency, 1),
            "steps": len(tools_used)
        })

    # ── Plan Generation ───────────────────────────────────────

    async def _generate_plan(
        self, message: str, df: pd.DataFrame, state: AgentState, logger: SessionLogger
    ) -> list[PlanStep]:
        col_info = []
        for c in state.columns:
            name = c.get("name", "?")
            dtype_cn = c.get("dtype_cn", c.get("dtype", "?"))
            col_info.append(f"  - {name} [{dtype_cn}]")
        columns_str = "\n".join(col_info) if col_info else "  (无信息)"

        trace_summary = self._get_trace_summary(state)

        chart_ctx = select_chart_type_with_context(state.columns, message)
        selected_chart = chart_ctx["chart_type"]

        # chart_hint is system-generated — LLM must NOT output or discuss it
        system_prompt = (
            "你是数据分析计划生成器。根据用户问题和数据列信息，生成 1-3 步分析计划。\n\n"
            f"**数据列**:\n{columns_str}\n"
            f"**行数**: {len(df) if df is not None else 0}\n"
            f"{trace_summary}\n"
            "**可用工具**: chart_builder (图表), data_query (统计查询), annotation_engine (综合结论)\n\n"
            "输出严格的 JSON，包含 steps 数组：\n"
            "{\n"
            '  "steps": [\n'
            '    {"id": "s1", "goal": "数据分析", "tool": "chart_builder"},\n'
            '    {"id": "s2", "goal": "综合结论", "tool": "annotation_engine", "depends_on": ["s1"]}\n'
            "  ]\n"
            "}\n\n"
            "规则：\n"
            "- id 用 s1,s2,...；depends_on 引用前面的步骤\n"
            "- goal 根据数据特征和用户问题填写（如：整体趋势、分类对比、分布分析）\n"
            "- 每个分析计划必须包含至少 1 个 chart_builder 步骤用于可视化。多维度时可规划 2 个 chart\n"
            "- 最后一步放 annotation_engine 做综合结论\n"
            "- 不要推荐或讨论图表类型，图表类型由系统自动确定\n"
            "- 不要在输出中包含 chart_hint 字段\n"
        )

        try:
            raw, _, _, _ = await self._call_llm(system_prompt, message, logger)
        except Exception:
            return [
                PlanStep(id="s1", goal="数据概览", tool="data_query"),
                PlanStep(id="s2", goal="生成图表", tool="chart_builder", chart_hint="bar"),
            ]

        parsed = self._parse_llm_response(raw, logger)
        if not parsed:
            return [
                PlanStep(id="s1", goal="数据分析", tool="chart_builder", chart_hint="bar"),
            ]

        steps_raw = parsed.get("steps", [parsed] if isinstance(parsed, dict) else [])
        plan: list[PlanStep] = []
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                continue
            plan.append(PlanStep(
                id=s.get("id", f"s{i+1}"),
                goal=s.get("goal", f"步骤{i+1}"),
                tool=s.get("tool", "data_query"),
                depends_on=s.get("depends_on", []),
                chart_hint=selected_chart if s.get("tool") == "chart_builder" else "",
                narrative_hint=s.get("narrative_hint", ""),
            ))
        return plan

    # ── Step Prompt Builder ───────────────────────────────────

    def _build_step_prompt(
        self, state: AgentState, step: PlanStep, step_idx: int,
        plan: list[PlanStep], prev_narrative: str = ""
    ) -> str:
        col_info = []
        for c in state.columns:
            name = c.get("name", "?")
            dtype_cn = c.get("dtype_cn", c.get("dtype", "?"))
            col_info.append(f"  - {name} [{dtype_cn}]")
        columns_str = "\n".join(col_info) if col_info else "  (无信息)"

        trace_lines = []
        for t in state.analysis_trace[-3:]:
            trace_lines.append(f"[{t.level1}]: {t.level2[0] if t.level2 else ''}")
        trace_context = "\n".join(trace_lines) if trace_lines else "（首次分析）"

        prompt = (
            f"你是数据分析执行引擎。当前执行第 {step_idx + 1}/{len(plan)} 步。\n\n"
            f"**任务**: {step.goal}\n"
            f"**工具**: {step.tool}\n"
            f"**数据列**:\n{columns_str}\n"
            f"**行数**: {state.row_count}\n"
            f"**之前的分析**:\n{trace_context}\n"
        )

        if prev_narrative:
            prompt += f"\n**上一步的回复（避免重复）**: {prev_narrative[:200]}\n"

        if step.chart_hint:
            prompt += f"\n**SYSTEM DECISION（不可质疑）**：图表类型已确定为 {step.chart_hint}。\n"
            prompt += "你必须在 action.args.type 中写入此图表类型。\n"

        # For annotation_engine: inject contract's final chart decision from artifact
        if step.tool == "annotation_engine" and state.execution_artifacts:
            last = state.execution_artifacts[-1]
            if hasattr(last, 'to_prompt_context'):
                ctx = last.to_prompt_context()
                prompt += (
                    f"\n**EXECUTION RESULT**: {json.dumps(ctx, ensure_ascii=False)}\n"
                    "你的职责：基于以上图表描述数据发现。不要推荐或讨论图表类型。\n"
                )

        prompt += (
            "\n请输出 JSON：\n"
            '{"reply": "一句话说明你在做什么", '
            f'"action": {{"tool": "{step.tool}", "args": {{...}}}}, '
            '"confidence": {{"score": 0.8}}'
            "}\n\n"
            "规则：\n"
            "- 图表类型已由系统确定，不要推荐或讨论图表类型。你的职责是分析数据含义和描述发现。\n"
            "- reply 只描述数据发现（如'身高与体重存在正相关'），不提及图表类型。\n"
            "- action.args 必须包含 type（使用系统确定的图表类型）、x（列名）、y（列名列表）。\n"
        )
        return prompt

    # ── Trace ─────────────────────────────────────────────────

    def _write_trace(self, state: AgentState, step: PlanStep, reply: str, tool: str):
        trace = ThinkingTrace(
            level1=f"[步骤] {step.goal}",
            level2=[reply] if reply else [],
            confidence=ConfidenceLevel.MEDIUM,
            confidence_score=0.8,
        )
        state.add_thinking_trace(trace)

        if len(state.analysis_trace) > 20:
            state.analysis_trace = state.analysis_trace[-15:]

    def _get_trace_summary(self, state: AgentState) -> str:
        if not state.analysis_trace:
            return ""
        traces = [
            {"level1": t.level1, "level2": t.level2}
            for t in state.analysis_trace
        ]
        summary = summarize_old_traces(traces)
        return f"**之前的分析概览**:\n{summary}\n" if summary else ""

    # ── Narrative ─────────────────────────────────────────────

    async def _narrate(
        self, ce_result: dict, df, state, message: str, logger
    ) -> str:
        """Generate narrative from contract output. Contract is the sole authority.

        Accepts the raw contract_entry dict directly — no intermediate mapping.
        Handles approved, degraded, and rejected statuses.
        LLM only describes data insights; never discusses chart type.
        """
        status = ce_result["status"]
        chart_type = ce_result["chart_type"]
        x_col = ce_result["x"]
        y_cols = ce_result["y"]
        explanation = ce_result.get("explanation", [])

        if status == "degraded":
            return f"（已调整——数据降级）原因: {'; '.join(explanation[:2])}"

        if status == "rejected":
            return ""

        # Approved
        col_desc = ", ".join(y_cols) if y_cols else "无"
        prompt = (
            f"图表类型已由系统确定为 {chart_type}。"
            f"X 轴: {x_col}。Y 轴: {col_desc}。"
            f"选择原因: {'; '.join(explanation[:2])}。"
            f"数据共 {state.row_count} 行。\n\n"
            "你的职责：描述数据中可能存在的规律或发现，1-2 句话。\n\n"
            "规则：\n"
            "- 不要推荐或讨论图表类型（已确定）\n"
            "- 不要比较图表类型\n"
            "- 不要质疑系统决策\n"
            "- 不要泄露决策过程（如'系统选择了'、'基于规则'）\n"
            "- 只描述数据含义\n"
            f"- 用户原始问题: {message[:100]}\n"
        )
        try:
            content, _, _, _ = await self._call_llm(prompt, "叙事", logger)
            result = content.strip()[:300]
            # Strip chart-type keywords to prevent contaminating prev_narrative
            for kw in ["散点", "折线", "柱状", "饼图", "直方", "箱线", "趋势图", "scatter", "line chart", "bar chart"]:
                result = result.replace(kw, "")
            return result
        except Exception:
            return ""

    # ── Synthesis ─────────────────────────────────────────────

    async def _synthesize(
        self, state: AgentState, message: str, tools_used: list[str], logger: SessionLogger
    ) -> str:
        if not tools_used:
            return "分析完成。"
        prompt = (
            "根据已执行的分析步骤，用1-2句话总结关键发现。直接给出结论，不要客套话。\n\n"
            f"用户问题: {message}\n"
            f"使用工具: {', '.join(tools_used)}\n"
            "规则：不要推荐或讨论图表类型。只描述数据发现。\n"
        )
        try:
            content, _, _, _ = await self._call_llm(prompt, "总结发现", logger)
            return content[:MAX_NARRATIVE_CHARS]
        except Exception:
            return "分析完成，请查看图表结果。"

    # ── LLM ───────────────────────────────────────────────────

    async def _call_llm(
        self, system_prompt: str, user_message: str, logger: SessionLogger
    ) -> tuple[str, int, int, float]:
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
                return content, tokens_in, tokens_out, latency_ms

    # ── Parse ─────────────────────────────────────────────────

    def _parse_llm_response(self, raw: str, logger: SessionLogger) -> dict | None:
        raw = raw.strip()
        # Try direct JSON
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Try extracting JSON block
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None


# ── Narrative dedup filter (module-level util) ──────────────────

def _is_narrative_dup(current: str, previous: str) -> bool:
    """Return True if current is too similar to previous narrative."""
    if not previous or not current:
        return False
    prefix = min(len(current), len(previous), 8)
    if prefix > 0 and current[:prefix] == previous[:prefix]:
        return True
    common = len(set(current) & set(previous))
    total = len(set(current) | set(previous))
    if total > 0 and common / total > NARRATIVE_SIMILARITY_THRESHOLD:
        return True
    return False
