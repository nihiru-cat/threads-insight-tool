"""String-based similarity (difflib), always available, no API calls / cost.

Used as the default fallback when no embedding backend is configured, and
always computed alongside the semantic score so both are visible even when
they disagree (see app.services.generation_service).
"""

from __future__ import annotations

from difflib import SequenceMatcher

from app.services.similarity.base import SimilarityChecker


class StringSimilarityChecker(SimilarityChecker):
    backend_name = "string"

    def similarity(self, text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0
        return SequenceMatcher(None, text_a, text_b).ratio()
