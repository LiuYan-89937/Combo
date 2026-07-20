from __future__ import annotations

from pathlib import Path

from agent_factory.knowledge_system.catalog import KnowledgeCatalog
from agent_factory.knowledge_system.events import KnowledgeEventSink
from agent_factory.knowledge_system.runtime import KnowledgeRuntime
from agent_factory.knowledge_system.schema import KnowledgeContractConfig
from agent_factory.knowledge_system.store_index import build_knowledge_store_index
from agent_factory.runtime_kernel.persistence import LangGraphStoreConfig, LangGraphStoreFactory


def build_knowledge_runtime(
    *,
    config: KnowledgeContractConfig,
    owner_type: str,
    owner_id: str,
    event_sink: KnowledgeEventSink | None = None,
) -> KnowledgeRuntime:
    index = build_knowledge_store_index(config)
    store_handle = LangGraphStoreFactory().build(
        LangGraphStoreConfig(
            backend=config.rag_store.backend,
            path=(
                Path(config.rag_store.path)
                if config.rag_store.backend == "sqlite" and config.rag_store.path.strip()
                else None
            ),
            connection_uri=config.rag_store.connection_uri,
            database_name=config.rag_store.database_name,
            collection_name=config.rag_store.collection_name,
            setup=config.rag_store.setup,
            provider_options=config.rag_store.provider_options,
            index=index,
        )
    )
    return KnowledgeRuntime(
        config=config,
        owner_type=owner_type,
        owner_id=owner_id,
        catalog=KnowledgeCatalog(config.catalog_path),
        store=store_handle.store,
        semantic_index_enabled=store_handle.semantic_index_enabled,
        event_sink=event_sink,
    )
