"""Unit tests for EntityRef + EntityRegistry symbolic reference system."""

import pandas as pd
import pytest

from core.ir.entity import EntityRef, EntityRegistry


class TestEntityRef:
    def test_identity_only_no_label(self):
        """EntityRef is identity — no label field. Naming is the Registry's job."""
        ref = EntityRef(entity_id="e_001")
        assert ref.entity_id == "e_001"
        # No label attribute
        assert not hasattr(ref, "label")

    def test_str_emits_token(self):
        ref = EntityRef(entity_id="e_005")
        assert str(ref) == "[[entity:e_005]]"

    def test_roundtrip(self):
        ref = EntityRef(entity_id="e_042")
        d = ref.to_dict()
        assert d == {"entity_id": "e_042"}
        ref2 = EntityRef.from_dict(d)
        assert ref2.entity_id == "e_042"

    def test_equality(self):
        a = EntityRef("e_001")
        b = EntityRef("e_001")
        c = EntityRef("e_002")
        assert a == b
        assert a != c


class TestEntityRegistry:
    def test_build_from_dataframe(self):
        df = pd.DataFrame({"城市": ["北京", "上海", "广州"]})
        reg = EntityRegistry.build(df, "城市")
        assert reg.mapping == {"e_001": "北京", "e_002": "上海", "e_003": "广州"}
        assert reg.id_column == "城市"

    def test_build_with_gaps(self):
        """NaN values are skipped."""
        df = pd.DataFrame({"name": ["A", None, "B", None]})
        reg = EntityRegistry.build(df, "name")
        assert len(reg.mapping) == 2
        assert reg.mapping["e_001"] == "A"
        assert reg.mapping["e_002"] == "B"

    def test_resolve_known(self):
        reg = EntityRegistry(mapping={"e_001": "张三", "e_002": "李四"}, id_column="姓名")
        assert reg.resolve("e_001") == "张三"
        assert reg.resolve("e_002") == "李四"

    def test_resolve_unknown(self):
        """Unknown IDs pass through unchanged."""
        reg = EntityRegistry(mapping={}, id_column="x")
        assert reg.resolve("e_999") == "e_999"

    def test_resolve_pattern(self):
        reg = EntityRegistry(mapping={"e_001": "A", "e_002": "B"}, id_column="x")
        text = "[[entity:e_001]] beats [[entity:e_002]]"
        result = reg.resolve_pattern(text)
        assert result == "A beats B"

    def test_resolve_pattern_no_tokens(self):
        reg = EntityRegistry(mapping={"e_001": "A"}, id_column="x")
        assert reg.resolve_pattern("no tokens here") == "no tokens here"

    def test_resolve_pattern_partial_token_not_replaced(self):
        """metric_e_001_growth should NOT be matched by the pattern."""
        reg = EntityRegistry(mapping={"e_001": "张三"}, id_column="x")
        text = "metric_e_001_growth"
        result = reg.resolve_pattern(text)
        assert result == "metric_e_001_growth"  # unchanged — safe

    def test_entity_ids(self):
        reg = EntityRegistry(mapping={"e_001": "A", "e_002": "B"}, id_column="x")
        assert set(reg.entity_ids()) == {"e_001", "e_002"}

    def test_get_ref(self):
        reg = EntityRegistry(mapping={"e_001": "A"}, id_column="x")
        ref = reg.get_ref("e_001")
        assert isinstance(ref, EntityRef)
        assert ref.entity_id == "e_001"

    def test_roundtrip(self):
        reg = EntityRegistry(mapping={"e_001": "北京", "e_002": "上海"}, id_column="城市")
        d = reg.to_dict()
        reg2 = EntityRegistry.from_dict(d)
        assert reg2.mapping == reg.mapping
        assert reg2.id_column == reg.id_column
        assert reg2.resolve("e_001") == "北京"
