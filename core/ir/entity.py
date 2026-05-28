"""Core IR — Entity Reference System.

EntityRef: identity only (no label). Like a database foreign key.
EntityRegistry: naming authority. Like a lookup table.
"""

from __future__ import annotations
from dataclasses import dataclass
import re

import pandas as pd

ENTITY_TOKEN_PATTERN = re.compile(r"\[\[entity:(e_\d+)\]\]")


@dataclass(frozen=True)
class EntityRef:
    """Opaque entity identity. Carries no label — naming is the Registry's job."""

    entity_id: str  # "e_001", "e_002", ...

    def __str__(self) -> str:
        return f"[[entity:{self.entity_id}]]"

    def to_dict(self) -> dict:
        return {"entity_id": self.entity_id}

    @classmethod
    def from_dict(cls, d: dict) -> "EntityRef":
        return cls(entity_id=d["entity_id"])


@dataclass(frozen=True)
class EntityRegistry:
    """Session-scoped naming authority. e_001 → "人物1", etc."""

    mapping: dict[str, str]  # entity_id → label
    id_column: str  # source column name (e.g. "姓名")

    @staticmethod
    def build(df: pd.DataFrame, x_column: str) -> "EntityRegistry":
        """Build registry from DataFrame's x-axis column values.

        Each unique value gets an entity_id: e_001, e_002, ...
        """
        unique_vals = df[x_column].dropna().unique()
        mapping = {}
        for i, val in enumerate(unique_vals):
            entity_id = f"e_{i + 1:03d}"
            mapping[entity_id] = str(val)
        return EntityRegistry(mapping=mapping, id_column=x_column)

    def resolve(self, entity_id: str) -> str:
        """entity_id → label. Returns entity_id unchanged if not found."""
        return self.mapping.get(entity_id, entity_id)

    def resolve_pattern(self, text: str) -> str:
        """Replace all [[entity:e_XXX]] tokens with their labels."""
        return ENTITY_TOKEN_PATTERN.sub(lambda m: self.resolve(m.group(1)), text)

    def get_ref(self, entity_id: str) -> EntityRef:
        """Convenience: wrap an entity_id in an EntityRef."""
        return EntityRef(entity_id=entity_id)

    def entity_ids(self) -> list[str]:
        """All registered entity IDs."""
        return list(self.mapping.keys())

    def to_dict(self) -> dict:
        return {"mapping": self.mapping, "id_column": self.id_column}

    @classmethod
    def from_dict(cls, d: dict) -> "EntityRegistry":
        return cls(mapping=d["mapping"], id_column=d["id_column"])
