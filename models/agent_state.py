"""AgentState — the agent's reasoning memory, not just data context.

Structured to support:
  - Hypothesis tracking (what we're exploring, what we've ruled out)
  - AnalysisGraph (non-linear branching investigation, not a pipeline)
  - Thinking Trace (L1/L2/L3 reasoning visibility)
  - User preferences (learned over time)
  - Chart memory (what we've created and why)
  - Confidence calibration (how sure we are about each finding)
  - Cross-session persistence via StateManager
"""
from __future__ import annotations
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Any
import time
import uuid


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class NodeStatus(str, Enum):
    PENDING = "pending"
    EXPLORING = "exploring"
    COMPLETED = "completed"
    REJECTED = "rejected"


class NodeType(str, Enum):
    OVERVIEW = "overview"        # 数据概览
    DRILL_DOWN = "drill_down"    # 深入分析
    COMPARE = "compare"          # 对比分析
    CORRELATE = "correlate"      # 相关性分析
    FORECAST = "forecast"        # 预测
    CONCLUSION = "conclusion"    # 结论摘要
    FORK = "fork"                # 分叉点


class ConfidenceLevel(str, Enum):
    HIGH = "high"      # 🟢 r>0.8, n>20
    MEDIUM = "medium"  # 🟡 r>0.5, n>10
    LOW = "low"        # 🔴 r<0.5, n<10


# ═══════════════════════════════════════════════════════════════
# Analysis Graph
# ═══════════════════════════════════════════════════════════════

@dataclass
class AnalysisNode:
    """A single node in the branching analysis graph."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: NodeType = NodeType.OVERVIEW
    label: str = ""
    question: str = ""
    chart_result: dict | None = None
    insights: list[dict] = field(default_factory=list)
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def __post_init__(self):
        # Coerce strings to enums (from manual construction or JSON deserialization)
        if isinstance(self.type, str):
            self.type = NodeType(self.type)
        if isinstance(self.status, str):
            self.status = NodeStatus(self.status)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type.value, "label": self.label,
            "question": self.question, "chart_result": self.chart_result,
            "insights": self.insights, "parent_id": self.parent_id,
            "children": self.children, "status": self.status.value,
            "created_at": self.created_at, "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisNode":
        return cls(
            id=d.get("id", uuid.uuid4().hex[:12]),
            type=NodeType(d.get("type", "overview")),
            label=d.get("label", ""),
            question=d.get("question", ""),
            chart_result=d.get("chart_result"),
            insights=d.get("insights", []),
            parent_id=d.get("parent_id"),
            children=d.get("children", []),
            status=NodeStatus(d.get("status", "pending")),
            created_at=d.get("created_at", time.time()),
            completed_at=d.get("completed_at"),
        )


@dataclass
class AnalysisGraph:
    """A non-linear branching investigation graph.

    Single active branch for v1. Nodes can have multiple children (fork),
    but only one path is explored at a time. User can backtrack and switch.

    Example structure:
        [概览: 发现3月异常]
            ├── [深挖时间原因] ✓
            │   └── [排除春节] ✓
            │       └── [发现广告费相关] ← current
            └── [对比部门表现] (pending)
    """
    nodes: dict[str, AnalysisNode] = field(default_factory=dict)
    root_id: str | None = None
    current_id: str | None = None
    title: str = ""

    def add_node(self, node: AnalysisNode) -> str:
        self.nodes[node.id] = node
        if self.root_id is None:
            self.root_id = node.id
        return node.id

    def get_current(self) -> AnalysisNode | None:
        if self.current_id and self.current_id in self.nodes:
            return self.nodes[self.current_id]
        return None

    def advance_to(self, node_id: str):
        if node_id in self.nodes:
            self.current_id = node_id

    def backtrack(self) -> AnalysisNode | None:
        """Go back to parent of current node."""
        cur = self.get_current()
        if cur and cur.parent_id and cur.parent_id in self.nodes:
            self.current_id = cur.parent_id
            return self.nodes[cur.parent_id]
        if self.root_id:
            self.current_id = self.root_id
            return self.nodes[self.root_id]
        return None

    def fork_from(self, parent_id: str, branches: list[AnalysisNode]):
        """Create multiple child branches from a parent node."""
        if parent_id not in self.nodes:
            return
        parent = self.nodes[parent_id]
        parent.type = NodeType.FORK
        for child in branches:
            child.parent_id = parent_id
            self.add_node(child)
        parent.children = [c.id for c in branches]

    def to_dict(self) -> dict:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "root_id": self.root_id,
            "current_id": self.current_id,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisGraph":
        graph = cls(
            root_id=d.get("root_id"),
            current_id=d.get("current_id"),
            title=d.get("title", ""),
        )
        for k, v in d.get("nodes", {}).items():
            graph.nodes[k] = AnalysisNode.from_dict(v)
        return graph


# ═══════════════════════════════════════════════════════════════
# Thinking Trace (L1/L2/L3)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ThinkingTrace:
    """Three-level reasoning trace for every agent response.

    L1 (default visible): one-line conclusion + basis + recommendation
    L2 (expandable): step-by-step reasoning chain
    L3 (developer): raw prompt, tokens, latency
    """
    level1: str = ""
    level2: list[str] = field(default_factory=list)
    level3: dict = field(default_factory=dict)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    confidence_score: float = 0.5

    def __post_init__(self):
        if isinstance(self.confidence, str):
            self.confidence = ConfidenceLevel(self.confidence)

    def to_dict(self) -> dict:
        return {
            "level1": self.level1,
            "level2": self.level2,
            "level3": self.level3,
            "confidence": self.confidence.value,
            "confidence_score": self.confidence_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ThinkingTrace":
        return cls(
            level1=d.get("level1", ""),
            level2=d.get("level2", []),
            level3=d.get("level3", {}),
            confidence=ConfidenceLevel(d.get("confidence", "medium")),
            confidence_score=d.get("confidence_score", 0.5),
        )


# ═══════════════════════════════════════════════════════════════
# User Preferences
# ═══════════════════════════════════════════════════════════════

@dataclass
class UserPreferences:
    """Learned user preferences — accumulated across sessions."""
    theme: str = "light"                 # "light" | "dark"
    fav_chart_type: str = "bar"          # most-used chart
    fav_color_scheme: str = "business"   # preferred palette
    fav_style: str = "clean"             # preferred style template
    language: str = "zh"                 # "zh" | "en"
    chart_type_counts: dict = field(default_factory=dict)  # {chart_type: count}
    common_columns: list[str] = field(default_factory=list)  # columns often selected

    def record_chart_use(self, chart_type: str):
        self.chart_type_counts[chart_type] = self.chart_type_counts.get(chart_type, 0) + 1
        # Update favourite
        if self.chart_type_counts:
            self.fav_chart_type = max(self.chart_type_counts, key=lambda k: self.chart_type_counts[k])

    def to_dict(self) -> dict:
        return {
            "theme": self.theme, "fav_chart_type": self.fav_chart_type,
            "fav_color_scheme": self.fav_color_scheme, "fav_style": self.fav_style,
            "language": self.language, "chart_type_counts": self.chart_type_counts,
            "common_columns": self.common_columns,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserPreferences":
        return cls(
            theme=d.get("theme", "light"),
            fav_chart_type=d.get("fav_chart_type", "bar"),
            fav_color_scheme=d.get("fav_color_scheme", "business"),
            fav_style=d.get("fav_style", "clean"),
            language=d.get("language", "zh"),
            chart_type_counts=d.get("chart_type_counts", {}),
            common_columns=d.get("common_columns", []),
        )


# ═══════════════════════════════════════════════════════════════
# Execution Artifacts — structured execution facts (not narrative)
# ═══════════════════════════════════════════════════════════════

class ArtifactStatus(str, Enum):
    PENDING = "pending"      # contract validated, awaiting execution
    APPROVED = "approved"
    DEGRADED = "degraded"
    REPAIRED = "repaired"
    FAILED = "failed"


@dataclass
class ChartArtifact:
    """Structured, replayable chart execution fact. LLM reads but never writes."""
    step_id: str
    chart_type: str
    x_column: str
    y_columns: list[str]
    title: str
    resolved_by: str = "contract_entry"
    source_step: str = "chart_builder"
    status: ArtifactStatus = ArtifactStatus.APPROVED

    def to_prompt_context(self) -> dict:
        """Minimal context for LLM — only what it needs to describe the chart."""
        return {
            "chart_type": self.chart_type,
            "x_column": self.x_column,
            "y_columns": self.y_columns,
        }

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "chart_type": self.chart_type,
            "x_column": self.x_column,
            "y_column": self.y_columns,
            "title": self.title,
            "resolved_by": self.resolved_by,
            "source_step": self.source_step,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChartArtifact":
        return cls(
            step_id=d.get("step_id", ""),
            chart_type=d.get("chart_type", "bar"),
            x_column=d.get("x_column", ""),
            y_columns=d.get("y_columns", d.get("y_column", [])),
            title=d.get("title", ""),
            resolved_by=d.get("resolved_by", "contract_entry"),
            source_step=d.get("source_step", "chart_builder"),
            status=ArtifactStatus(d.get("status", "approved")),
        )


# ═══════════════════════════════════════════════════════════════
# AgentState — the top-level container
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentState:
    """The complete agent reasoning context — persisted across sessions.

    Design principle: remembers *the analysis process*, not just data.
    """
    # ── Identity ──
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    namespace: str = "default"          # future: user_id
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ── Data Profile ──
    file_path: str = ""
    sheet_name: str = ""
    columns: list[dict] = field(default_factory=list)   # [{name, dtype, dtype_cn, stats}]
    row_count: int = 0

    # ── Plan Progress (v3 Plan-then-Execute) ──
    analysis_plan: list[dict] = field(default_factory=list)
    # [{"id": "overview", "tool": "data_query", "node_type": "overview", "label": "数据概览",
    #   "status": "completed", "reasoning": "了解数据全貌后再决定分析路径"}]
    plan_generated: bool = False
    plan_current_idx: int = 0

    # ── Structured Plan Progress (Phase 3 PlanStep) ──
    plan_progress: list[PlanStep] = field(default_factory=list)

    # ── Analysis Trace (Orchestrator observation memory) ──
    analysis_trace: list[TraceEntry] = field(default_factory=list)

    # ── Exploration Paths (Phase 4 Deep Exploration) ──
    active_paths: list = field(default_factory=list)
    completed_paths: list = field(default_factory=list)
    path_budget: int = 3

    # ── Reasoning Memory (core) ──
    active_hypotheses: list[dict] = field(default_factory=list)
    # [{"question": "3月下降是否因为春节?", "status": "investigating", "node_id": "abc123"}]

    explored_questions: list[dict] = field(default_factory=list)
    # [{"question": "销售额整体趋势?", "answer": "月均增长12%", "confidence": 0.89}]

    rejected_paths: list[dict] = field(default_factory=list)
    # [{"path": "按部门拆分", "reason": "部门字段缺失", "at_node": "xyz"}]

    thinking_traces: list[ThinkingTrace] = field(default_factory=list)

    # ── Products ──
    chart_memory: dict[str, dict] = field(default_factory=dict)
    # {chart_id: {html, type, title, insights, annotations, created_at}}

    story_graph: AnalysisGraph = field(default_factory=AnalysisGraph)

    # ── Confidence ──
    confidence_scores: dict[str, float] = field(default_factory=dict)
    # {insight_id: score 0-1}

    # ── Unified Analysis (cross-mode cognitive state) — presentation only ──
    unified_analysis: list[dict] = field(default_factory=list)

    # ── Execution Artifacts (system truth — structured, replayable) ──
    execution_artifacts: list = field(default_factory=list)
    # LLM must only READ artifacts, never WRITE them.
    # Schema per entry:
    # {
    #     "type": "insight" | "chart" | "hypothesis" | "fact",
    #     "content": str,
    #     "confidence": float (0.0-1.0),
    #     "source": "react" | "explore",
    #     "chart_type": str | None,
    #     "ts": float
    # }

    # ── User Model ──
    user_preferences: UserPreferences = field(default_factory=UserPreferences)

    # ── Interaction ──
    action_history: list[dict] = field(default_factory=list)
    # [{"action": "generate_chart", "params": {...}, "result": "ok", "user_feedback": "accepted"}]

    def touch(self):
        self.updated_at = time.time()

    def add_finding(self, finding_type: str, content: str, source: str = "react",
                    confidence: float = 0.5, chart_type: str | None = None):
        """Append a finding to the unified analysis log. Thread-safe for both engines."""
        self.unified_analysis.append({
            "type": finding_type,
            "content": content,
            "confidence": min(1.0, max(0.0, confidence)),
            "source": source,
            "chart_type": chart_type,
            "ts": time.time(),
        })
        self.touch()

    def add_artifact(self, artifact) -> None:
        """Record a structured execution fact. LLM reads, never writes."""
        self.execution_artifacts.append(artifact)
        self.touch()

    # ── Plan helpers ──

    def set_plan(self, plan: list[dict]):
        """Set the analysis plan and reset progress."""
        self.analysis_plan = plan
        self.plan_generated = True
        self.plan_current_idx = 0
        self.touch()

    def advance_plan(self, decision_reasoning: str = ""):
        """Mark current step completed and advance to next pending step."""
        if 0 <= self.plan_current_idx < len(self.analysis_plan):
            self.analysis_plan[self.plan_current_idx]["status"] = "completed"
            if decision_reasoning:
                self.analysis_plan[self.plan_current_idx]["reasoning"] = decision_reasoning
        # Find next pending
        for i in range(self.plan_current_idx + 1, len(self.analysis_plan)):
            if self.analysis_plan[i].get("status", "pending") == "pending":
                self.plan_current_idx = i
                self.analysis_plan[i]["status"] = "active"
                self.touch()
                return self.analysis_plan[i]
        self.plan_current_idx = len(self.analysis_plan)
        self.touch()
        return None

    def rewrite_plan(self, new_steps: list[dict], insert_after_current: bool = True):
        """Insert or replace plan steps dynamically based on observation."""
        if insert_after_current:
            insert_at = self.plan_current_idx + 1
            for i, step in enumerate(new_steps):
                step["id"] = step.get("id", f"dyn_{i}")
                step["status"] = "pending"
                self.analysis_plan.insert(insert_at + i, step)
        else:
            # Replace all remaining steps
            remaining = self.analysis_plan[self.plan_current_idx + 1:]
            self.analysis_plan = self.analysis_plan[:self.plan_current_idx + 1]
            for i, step in enumerate(new_steps):
                step["id"] = step.get("id", f"dyn_{i}")
                step["status"] = "pending"
                self.analysis_plan.append(step)
        self.touch()

    def get_plan_summary(self) -> str:
        """One-line plan progress for system prompt."""
        if not self.analysis_plan:
            return "(无分析计划)"
        parts = []
        for i, s in enumerate(self.analysis_plan):
            status = s.get("status", "pending")
            icon = {"completed": "✓", "active": "→", "pending": "○", "skipped": "✗"}.get(status, "?")
            parts.append(f"{icon}{s.get('label', s.get('id', '?'))}")
        return " ".join(parts)

    # ── PlanStep (Phase 3) management ──

    def set_plan_steps(self, steps: list[PlanStep]):
        """Replace plan_progress with new PlanStep list."""
        self.plan_progress = steps
        self.touch()

    def get_current_step(self) -> PlanStep | None:
        """Return the first PlanStep with status='pending' or 'running'."""
        for s in self.plan_progress:
            if s.status in ("pending", "running"):
                return s
        return None

    def mark_step_done(self, step_id: int, result: dict):
        """Mark a PlanStep as done and store its result."""
        for s in self.plan_progress:
            if s.id == step_id:
                s.status = "done"
                s.result = result
                self.touch()
                return

    def mark_step_failed(self, step_id: int, error: str):
        """Mark a PlanStep as failed and store the error."""
        for s in self.plan_progress:
            if s.id == step_id:
                s.status = "failed"
                s.result = {"error": error}
                self.touch()
                return

    def replan_steps(self) -> list[PlanStep]:
        """Return remaining pending/running PlanSteps."""
        return [s for s in self.plan_progress if s.status in ("pending", "running")]

    def add_hypothesis(self, question: str, node_id: str = ""):
        self.active_hypotheses.append({
            "question": question, "status": "investigating", "node_id": node_id
        })
        self.touch()

    def mark_explored(self, question: str, answer: str, confidence: float = 0.5):
        self.explored_questions.append({
            "question": question, "answer": answer, "confidence": confidence
        })
        # Remove from active hypotheses
        self.active_hypotheses = [
            h for h in self.active_hypotheses if h["question"] != question
        ]
        self.touch()

    def reject_path(self, path: str, reason: str, node_id: str = ""):
        self.rejected_paths.append({"path": path, "reason": reason, "at_node": node_id})
        self.touch()

    def add_thinking_trace(self, trace: ThinkingTrace):
        self.thinking_traces.append(trace)
        self.touch()

    def record_action(self, action: str, params: dict | None = None,
                      result: str = "ok", feedback: str = ""):
        self.action_history.append({
            "action": action, "params": params or {},
            "result": result, "user_feedback": feedback,
            "ts": time.time(),
        })
        self.touch()

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "namespace": self.namespace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "file_path": self.file_path,
            "sheet_name": self.sheet_name,
            "columns": self.columns,
            "row_count": self.row_count,
            "analysis_plan": self.analysis_plan,
            "plan_generated": self.plan_generated,
            "plan_current_idx": self.plan_current_idx,
            "plan_progress": [dataclasses.asdict(s) for s in self.plan_progress],
            "analysis_trace": [t.to_dict() if hasattr(t, 'to_dict') else
                               {"step_id": t.step_id, "goal": t.goal, "tool": t.tool,
                                "observation_summary": t.observation_summary,
                                "chart_type": t.chart_type, "timestamp": t.timestamp}
                               for t in self.analysis_trace],
            "active_paths": [p.to_dict() if hasattr(p, 'to_dict') else p for p in self.active_paths],
            "completed_paths": [p.to_dict() if hasattr(p, 'to_dict') else p for p in self.completed_paths],
            "path_budget": self.path_budget,
            "active_hypotheses": self.active_hypotheses,
            "explored_questions": self.explored_questions,
            "rejected_paths": self.rejected_paths,
            "thinking_traces": [t.to_dict() for t in self.thinking_traces],
            "chart_memory": self.chart_memory,
            "story_graph": self.story_graph.to_dict(),
            "confidence_scores": self.confidence_scores,
            "unified_analysis": self.unified_analysis,
            "execution_artifacts": [a.to_dict() if hasattr(a, 'to_dict') else a for a in self.execution_artifacts],
            "user_preferences": self.user_preferences.to_dict(),
            "action_history": self.action_history,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentState":
        return cls(
            session_id=d.get("session_id", uuid.uuid4().hex[:16]),
            namespace=d.get("namespace", "default"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            file_path=d.get("file_path", ""),
            sheet_name=d.get("sheet_name", ""),
            columns=d.get("columns", []),
            row_count=d.get("row_count", 0),
            analysis_plan=d.get("analysis_plan", []),
            plan_generated=d.get("plan_generated", False),
            plan_current_idx=d.get("plan_current_idx", 0),
            plan_progress=[PlanStep(**s) if isinstance(s, dict) else s for s in d.get("plan_progress", [])],
            analysis_trace=[TraceEntry(**t) if isinstance(t, dict) else t
                            for t in d.get("analysis_trace", [])],
            active_paths=d.get("active_paths", []),
            completed_paths=d.get("completed_paths", []),
            path_budget=d.get("path_budget", 3),
            active_hypotheses=d.get("active_hypotheses", []),
            explored_questions=d.get("explored_questions", []),
            rejected_paths=d.get("rejected_paths", []),
            thinking_traces=[ThinkingTrace.from_dict(t) for t in d.get("thinking_traces", [])],
            chart_memory=d.get("chart_memory", {}),
            story_graph=AnalysisGraph.from_dict(d.get("story_graph", {})),
            confidence_scores=d.get("confidence_scores", {}),
            unified_analysis=d.get("unified_analysis", []),
            execution_artifacts=[ChartArtifact.from_dict(a) if isinstance(a, dict) else a
                                 for a in d.get("execution_artifacts", [])],
            user_preferences=UserPreferences.from_dict(d.get("user_preferences", {})),
            action_history=d.get("action_history", []),
        )


# ═══════════════════════════════════════════════════════════════
# PlanStep — structured execution planning (Phase 3)
# ═══════════════════════════════════════════════════════════════

# ── Plan Execution Graph ─────────────────────────────────────

MAX_TRACE_ENTRIES = 8


@dataclass
class PlanStep:
    """Execution graph node — kills dict soup."""
    id: str
    goal: str
    tool: str
    depends_on: list[str] = field(default_factory=list)
    chart_hint: str | None = None
    narrative_hint: str | None = None
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"


@dataclass
class TraceEntry:
    """Compressed observation memory — no raw df, no chart_spec."""
    step_id: str
    goal: str
    tool: str
    observation_summary: str
    chart_type: str | None = None
    timestamp: float = 0.0


def summarize_old_traces(trace: list[TraceEntry]) -> str:
    """超过 MAX_TRACE_ENTRIES 时合并最早条目为摘要文本。"""
    if len(trace) <= MAX_TRACE_ENTRIES:
        return ""
    old = trace[:len(trace) - MAX_TRACE_ENTRIES]
    remaining = trace[len(trace) - MAX_TRACE_ENTRIES:]
    summaries = []
    for t in old:
        summaries.append(f"- {t.goal}: {t.observation_summary[:60]}")
    # 修改原列表（副作用，调用方注意）
    trace.clear()
    trace.extend(remaining)
    return "早期分析摘要:\n" + "\n".join(summaries) + "\n"
