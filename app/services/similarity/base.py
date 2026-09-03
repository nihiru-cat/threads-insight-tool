"""Provider-agnostic text-similarity interface.

`generation_service` only depends on this interface, never on a specific
backend — see app.services.similarity.factory.get_similarity_checker. Two
backends exist: a string-based one (always available, no API calls) and an
OpenAI-embedding-based one (used when configured/available). Both return a
score in [0, 1] where 1.0 means identical.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SimilarityChecker(ABC):
    #: Short identifier stored alongside a similarity score so it's clear
    #: later which method produced it (e.g. "string" vs "openai_embedding").
    backend_name: str

    @abstractmethod
    def similarity(self, text_a: str, text_b: str) -> float:
        """Return a similarity score in [0, 1] between two texts."""

    def close(self) -> None:  # pragma: no cover - overridden where needed
        pass

    def __enter__(self) -> "SimilarityChecker":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
