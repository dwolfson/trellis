"""Intent classifier — routes queries to the correct agent or RAG pipeline."""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import yaml


class QueryIntent(str, Enum):
    STATISTICAL = "statistical"
    COMPARISON = "comparison"
    INTEGRATION = "integration"
    DEPENDENCY = "dependency"
    HEALTH = "health"
    CODE_INVENTORY = "code_inventory"
    EXAMPLES = "examples"
    CODE_SEARCH = "code_search"
    CONCEPTUAL = "conceptual"
    SURVEY_META = "survey_meta"
    GENERAL = "general"


class QueryProcessor:
    """
    Classifies a query string into a QueryIntent.

    Loads patterns from config/routing.yaml. First match (by priority) wins.
    Falls back to GENERAL for unmatched queries.
    """

    _DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "routing.yaml"

    def __init__(self, routing_config_path: str | Path | None = None) -> None:
        path = Path(routing_config_path) if routing_config_path else self._DEFAULT_CONFIG
        with open(path) as f:
            self._rules = yaml.safe_load(f)["intent_patterns"]

    def classify(self, query: str) -> QueryIntent:
        q = query.lower()
        priority_order = ["survey_meta", "dependency", "integration", "comparison", "statistical", "code_inventory", "health", "examples", "code_search", "conceptual"]
        for intent_name in priority_order:
            rule = self._rules.get(intent_name, {})
            for pattern in rule.get("patterns", []):
                if re.search(pattern, q, re.IGNORECASE):
                    return QueryIntent(intent_name)
        return QueryIntent.GENERAL
