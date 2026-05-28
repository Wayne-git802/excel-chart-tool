"""Core IR — all immutable system contracts."""

from core.ir.profile import DatasetProfile, ColumnProfile, ContextualProfile
from core.ir.contract import AnalysisIntent, FilterCondition, FilterSpec, CapabilityResult, ChartDecision
from core.ir.narration import ChartFacts, ComparisonFact, NarrationContext
from core.ir.entity import EntityRef, EntityRegistry
from core.ir.session import DecisionStep, DecisionLedger, FilterContext
from core.ir.failure import ExplicitFailure

__all__ = [
    "DatasetProfile", "ColumnProfile", "ContextualProfile",
    "AnalysisIntent", "FilterCondition", "FilterSpec", "CapabilityResult", "ChartDecision",
    "ChartFacts", "ComparisonFact", "NarrationContext",
    "EntityRef", "EntityRegistry",
    "DecisionStep", "DecisionLedger", "FilterContext",
    "ExplicitFailure",
]
