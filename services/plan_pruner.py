"""PlanPruner — structural normalization of LLM-generated plans.

Normalizes plan order, deduplicates, and applies hard cap.
Does NOT make policy decisions — that's BudgetController's job.
"""

from __future__ import annotations
from collections import deque


class PlanPruner:
    """Structural plan normalization: sort, dedup, cap."""

    PRIORITY = {
        "annotation_engine": 3,
        "chart_builder": 2,
        "data_query": 1,
    }

    def prune(self, plan: list) -> list:
        """Normalize and prune plan.

        Args:
            plan: list of PlanStep objects (id, goal, tool, depends_on, chart_hint, ...)

        Returns:
            Normalized plan, max 3 steps.
        """
        if not plan:
            return []

        # Step 1: topological sort (depends_on ordering)
        sorted_plan = self._topo_sort(plan)

        # Step 2: priority sort within same topological level
        sorted_plan = self._priority_sort(sorted_plan)

        # Step 3: dedup by (tool, chart_hint)
        deduped = self._dedup(sorted_plan)

        # Step 4: hard cap 3
        return deduped[:3]

    # ── helpers ─────────────────────────────────────────────

    def _topo_sort(self, plan: list) -> list:
        """Topological sort: if s3 depends_on s1, s1 comes before s3."""
        id_to_step = {s.id: s for s in plan}
        in_degree: dict[str, int] = {s.id: 0 for s in plan}
        adj: dict[str, list[str]] = {s.id: [] for s in plan}

        for s in plan:
            for dep_id in (s.depends_on or []):
                if dep_id in adj:
                    adj[dep_id].append(s.id)
                    in_degree[s.id] = in_degree.get(s.id, 0) + 1

        # Kahn's algorithm
        queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
        result: list[str] = []

        while queue:
            sid = queue.popleft()
            result.append(sid)
            for neighbor in adj.get(sid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Any remaining nodes (cycles) — append at end
        for sid in id_to_step:
            if sid not in result:
                result.append(sid)

        return [id_to_step[sid] for sid in result if sid in id_to_step]

    def _priority_sort(self, plan: list) -> list:
        """Sort by priority, preserving dependency order."""
        return sorted(
            plan,
            key=lambda s: self.PRIORITY.get(getattr(s, "tool", ""), 0),
            reverse=True,
        )

    def _dedup(self, plan: list) -> list:
        """Dedup by (tool, chart_hint) signature."""
        seen: set[tuple] = set()
        kept_ids: set[str] = set()
        result: list = []

        for s in plan:
            tool = getattr(s, "tool", "")
            hint = getattr(s, "chart_hint", None)
            sig = (tool, hint)

            if sig in seen:
                continue
            seen.add(sig)

            result.append(s)
            kept_ids.add(s.id)

        return result
