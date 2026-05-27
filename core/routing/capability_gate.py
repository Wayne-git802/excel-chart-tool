"""CapabilityGate — deterministic pre-check before LLM involvement.

Layer A: rule-based keyword matching → reject unsupported queries BEFORE LLM sees them.
Layer B: intent semantic validation → reject unsupported intents AFTER LLM extraction.
"""

from __future__ import annotations

from core.ir.contract import AnalysisIntent, CapabilityResult
from core.ir.failure import ExplicitFailure

# Supported analysis types
SUPPORTED_INTENTS = {"trend", "comparison", "distribution", "correlation", "overview"}

# Layer A: keyword patterns that indicate unsupported capabilities
_UNSUPPORTED_PATTERNS = [
    (["预测", "forecast", "预计", "将来", "未来"], "unsupported_capability", "当前系统暂不支持预测类分析"),
    (["聚类", "cluster", "分组分析", "自动分组"], "unsupported_capability", "当前系统暂不支持聚类分析"),
    (["回归", "regression", "模型", "训练", "机器学习"], "unsupported_capability", "当前系统暂不支持建模类分析"),
    (["因果", "causal", "原因分析", "根因"], "unsupported_capability", "当前系统暂不支持因果推断"),
]


def layer_a_check(query: str) -> CapabilityResult:
    """Rule-based pre-check. Runs before any LLM call."""
    query_lower = query.lower()
    for patterns, code, message in _UNSUPPORTED_PATTERNS:
        for p in patterns:
            if p in query_lower:
                return CapabilityResult(allowed=False, reason=message)
    return CapabilityResult(allowed=True)


def layer_b_check(intent: AnalysisIntent) -> CapabilityResult:
    """Validate intent type against supported capabilities."""
    if intent.type == "UNKNOWN":
        # Not a rejection — downgrade to overview
        return CapabilityResult(allowed=True)
    if intent.type not in SUPPORTED_INTENTS:
        return CapabilityResult(
            allowed=False,
            reason=f"当前系统暂不支持 {intent.type} 类分析",
        )
    return CapabilityResult(allowed=True)


def capability_reject(code: str, message: str) -> ExplicitFailure:
    return ExplicitFailure(
        code=code,
        message=message,
        recoverable=False,
        stage="capability_gate",
    )
