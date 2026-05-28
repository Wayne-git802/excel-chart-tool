"""ReplayPolicy — global determinism constraints.

Phase 1: minimal. Phase 2: groupby_sort, reset_index, fill_na.
"""


class ReplayPolicy:
    """Deterministic execution constraints."""
    FLOAT_PRECISION: int = 10

    # Phase 2:
    # GROUPBY_SORT: bool = False
    # RESET_INDEX: bool = True
    # FILL_NA: object = None
