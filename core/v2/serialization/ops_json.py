"""Operation serialization — ops ↔ JSON round-trip.

Determinism requirement:
  replay(df, view_with_ops, backend) == replay(df, view_with_ops', backend)
  where ops' = deserialize(serialize(ops))
"""

from __future__ import annotations

import json
from ..ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp, Operation, OP_MAP

_OPS_BY_TYPE: dict[type, str] = {v: k for k, v in OP_MAP.items()}

_SKIP_FIELDS = {"op_id", "op_version", "op_class"}


def ops_to_json(ops: tuple[Operation, ...]) -> str:
    """Serialize operation sequence to JSON string."""
    items = []
    for op in ops:
        d = {"type": _OPS_BY_TYPE[type(op)]}
        for field_name in op.__dataclass_fields__:
            if field_name in _SKIP_FIELDS:
                continue
            val = getattr(op, field_name)
            if isinstance(val, tuple):
                val = list(val)
            d[field_name] = val
        items.append(d)
    return json.dumps(items, ensure_ascii=False, indent=2)


def json_to_ops(j: str) -> tuple[Operation, ...]:
    """Deserialize JSON string back to operation sequence."""
    items = json.loads(j)
    ops = []
    for item in items:
        cls = OP_MAP[item.pop("type")]
        if "y_columns" in item and isinstance(item["y_columns"], list):
            item["y_columns"] = tuple(item["y_columns"])
        ops.append(cls(**item))
    return tuple(ops)
