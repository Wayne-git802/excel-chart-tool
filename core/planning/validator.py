"""Plan validation — catch LLM mistakes before execution."""

def validate_plan(plan: list, columns: list[dict], valid_chart_types: set, node_tools: dict) -> list[str]:
    """
    Validate a plan against available data.
    Returns list of error messages (empty = valid).
    """
    errors = []
    col_names = {c.get("name", "") for c in columns}

    for step in plan:
        step_id = step.get("id", "?") if isinstance(step, dict) else step.id

        # Check node_type is valid
        nt = step.get("node_type", "") if isinstance(step, dict) else step.node_type
        if nt and nt not in node_tools:
            errors.append(f"Step {step_id}: unknown node_type '{nt}'")

        # Check columns exist
        params = step.get("params", {}) if isinstance(step, dict) else step.params
        for col in params.get("columns", []):
            if col and col not in col_names:
                errors.append(f"Step {step_id}: column '{col}' not in data ({sorted(col_names)[:5]}...)")

        # Check chart_type if specified
        ct = params.get("chart_type", "")
        if ct and ct not in valid_chart_types:
            errors.append(f"Step {step_id}: invalid chart_type '{ct}', valid: {sorted(valid_chart_types)}")

    return errors


def validate_plan_graph(steps: list) -> list[str]:
    """Validate execution graph: duplicate id, missing dep, cycle, too many, invalid tool.

    Args:
        steps: list of PlanStep or dict (兼容 dict with 'id'/'depends_on' keys)

    Returns:
        list of error strings (empty = valid)
    """
    errors = []
    if not steps:
        errors.append("Plan is empty")
        return errors

    MAX_STEPS = 6
    ALLOWED_TOOLS = {"chart_builder", "data_query", "annotation_engine", "hypothesis_test"}
    if len(steps) > MAX_STEPS:
        errors.append(f"Too many steps: {len(steps)} > {MAX_STEPS}")

    # Tool whitelist (structure-only, no policy)
    for s in steps:
        sid = s.id if hasattr(s, 'id') else s.get('id', '')
        tool = s.tool if hasattr(s, 'tool') else s.get('tool', '')
        if tool and tool not in ALLOWED_TOOLS:
            errors.append(f"Step '{sid}': unknown tool '{tool}'")

    # Collect ids
    seen_ids = set()
    step_ids = set()
    for s in steps:
        sid = s.id if hasattr(s, 'id') else s.get('id', '')
        if not sid:
            errors.append("Step missing id")
            continue
        if sid in seen_ids:
            errors.append(f"Duplicate step id: {sid}")
        seen_ids.add(sid)
        step_ids.add(sid)

    # Validate deps
    for s in steps:
        sid = s.id if hasattr(s, 'id') else s.get('id', '')
        deps = s.depends_on if hasattr(s, 'depends_on') else s.get('depends_on', [])
        if not deps:
            continue
        for dep in deps:
            if dep not in step_ids:
                errors.append(f"Step '{sid}' depends on unknown step '{dep}'")
            if dep == sid:
                errors.append(f"Step '{sid}' depends on itself")

    # Cycle detection (topological sort)
    if step_ids and not errors:
        adj = {sid: [] for sid in step_ids}
        in_degree = {sid: 0 for sid in step_ids}
        for s in steps:
            sid = s.id if hasattr(s, 'id') else s.get('id', '')
            deps = s.depends_on if hasattr(s, 'depends_on') else s.get('depends_on', [])
            for dep in deps:
                if dep in adj:
                    adj[dep].append(sid)
                    in_degree[sid] = in_degree.get(sid, 0) + 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        sorted_count = 0
        while queue:
            node = queue.pop(0)
            sorted_count += 1
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if sorted_count != len(step_ids):
            errors.append(f"Cyclic dependency detected: {len(step_ids) - sorted_count} nodes unreachable")

    return errors
