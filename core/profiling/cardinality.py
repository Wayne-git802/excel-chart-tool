"""Cardinality classification — deterministic."""


def classify_cardinality(unique_count: int, row_count: int) -> str:
    """Classify cardinality: low(≤20) | medium(21-100) | high(>100).

    Adjusts for small datasets: if row_count is small, threshold scales down.
    """
    if row_count < 20:
        # Small dataset — use ratio
        ratio = unique_count / max(row_count, 1)
        if ratio < 0.3:
            return "low"
        elif ratio < 0.7:
            return "medium"
        else:
            return "high"

    if unique_count <= 20:
        return "low"
    elif unique_count <= 100:
        return "medium"
    else:
        return "high"
