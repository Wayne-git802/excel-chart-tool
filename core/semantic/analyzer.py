"""Semantic analyzer — generates feasible analysis candidates from DatasetProfile.

Pure function, zero LLM. Derives what analyses the data naturally supports.
"""

from __future__ import annotations

from core.ir.profile import DatasetProfile


def feasible_analyses(profile: DatasetProfile) -> list[dict]:
    """Generate ranked analysis candidates from profile.

    Returns list of {type, x, y, confidence}, sorted by confidence desc.
    """
    candidates: list[dict] = []

    # Trend: temporal + numeric
    for t in profile.temporal_cols:
        for n in profile.numeric_cols:
            candidates.append({"type": "trend", "x": t, "y": n, "confidence": 0.90})

    # Comparison: low/medium cardinality categorical + numeric
    for c in profile.categorical_cols:
        cp = profile.columns.get(c)
        if cp and cp.cardinality in ("low", "medium"):
            for n in profile.numeric_cols:
                candidates.append({"type": "comparison", "x": c, "y": n, "confidence": 0.85})

    # Correlation: ≥2 numeric columns
    numeric_names = list(profile.numeric_cols)
    if len(numeric_names) >= 2:
        candidates.append({
            "type": "correlation",
            "x": numeric_names[0],
            "y": ", ".join(numeric_names[1:3]),
            "confidence": 0.80,
        })

    # Distribution: single numeric column
    for n in profile.numeric_cols:
        candidates.append({"type": "distribution", "x": n, "y": n, "confidence": 0.75})

    # Sort by confidence descending
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates
