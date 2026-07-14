from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings

from agent_factory.local_inference.config import LocalInferenceEndpoint


@dataclass(slots=True)
class LocalEmbeddingModel(Embeddings):
    profile_id: str
    endpoint: LocalInferenceEndpoint
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed([text])
        if len(vectors) != 1:
            raise ValueError("local embedding service returned an invalid query result")
        return vectors[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=self.endpoint.timeout_seconds) as client:
            response = client.post(
                self.endpoint.endpoint("/embed"),
                json={"profile_id": self.profile_id, "texts": texts},
            )
            response.raise_for_status()
            body = response.json()
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError("local embedding service returned an invalid batch")
        result = [_vector(item) for item in vectors]
        if any(len(vector) != self.dimensions for vector in result):
            raise ValueError("local embedding dimensions do not match the registered profile")
        return result


def _vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        raise ValueError("local embedding vector must be an array")
    return [float(item) for item in value]
