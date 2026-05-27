"""ExecutionGuard — runtime safety fallback only.

NEVER makes policy decisions (budget, priority, cuts).
ONLY prevents: null steps, crashes, genuine duplicates.
"""

from __future__ import annotations
import hashlib


class ExecutionGuard:
    """Runtime safety barrier. Not a policy layer."""

    def check(self, step, completed_steps: list, chart_count: int) -> dict:
        """Check if step is safe to execute.

        Args:
            step: PlanStep or None
            completed_steps: list of already-executed PlanStep objects
            chart_count: current chart count (informational only, NOT used for decisions)

        Returns:
            {"allow": bool, "reason": str}
        """
        # Safety 1: null step
        if step is None:
            return {"allow": False, "reason": "null step"}

        # Safety 2: invalid tool
        tool = getattr(step, "tool", None)
        if not isinstance(tool, str) or not tool.strip():
            return {"allow": False, "reason": "invalid tool"}

        # Safety 3: already executed (same tool + chart_hint + goal)
        goal = getattr(step, "goal", "")
        hint = getattr(step, "chart_hint", "") or ""
        sig = self._signature(tool, hint, goal)

        for completed in completed_steps:
            c_tool = getattr(completed, "tool", "")
            c_hint = getattr(completed, "chart_hint", "") or ""
            c_goal = getattr(completed, "goal", "")
            if sig == self._signature(c_tool, c_hint, c_goal):
                return {"allow": False, "reason": "already executed"}

        return {"allow": True, "reason": ""}

    @staticmethod
    def _signature(tool: str, chart_hint: str, goal: str) -> str:
        """Stable signature: tool + chart_hint + goal."""
        raw = f"{tool}|{chart_hint}|{goal}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
