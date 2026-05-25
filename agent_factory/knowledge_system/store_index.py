from __future__ import annotations

from agent_factory.knowledge_system.schema import KnowledgeContractConfig
from agent_factory.models import get_embedding_model, get_embedding_model_settings


def build_knowledge_store_index(config: KnowledgeContractConfig):
    embeddings = get_embedding_model()
    settings = get_embedding_model_settings()
    if embeddings is None or settings.dims is None:
        return None
    from langgraph.store.base import IndexConfig

    return IndexConfig(
        embed=embeddings,
        dims=settings.dims,
        fields=list(config.rag_store.index_fields or ["content"]),
    )
