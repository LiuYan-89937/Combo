from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import sqlite3

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    DeltaChannelHistory,
)
from langgraph.checkpoint.sqlite import SqliteSaver


class LatestSqliteSaver(SqliteSaver):
    """Full-snapshot recovery with one persisted checkpoint per thread/namespace.

    SQLite retention triggers are installed by prepare_checkpoint_storage before
    publication. Serialization, pending writes, and reads use the upstream saver.
    Historical replay and delta channels that need ancestor data are unsupported.
    """

    @contextmanager
    def cursor(self, transaction: bool = True) -> Iterator[sqlite3.Cursor]:
        with self.lock:
            self.setup()
            cursor = self.conn.cursor()
            try:
                yield cursor
                if transaction:
                    self.conn.commit()
            except BaseException:
                if transaction:
                    self.conn.rollback()
                raise
            finally:
                cursor.close()

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        if metadata.get("counters_since_delta_snapshot"):
            raise ValueError("Latest checkpoint storage requires full channel snapshots")
        return super().put(config, checkpoint, metadata, new_versions)

    def get_delta_channel_history(
        self, *, config: RunnableConfig, channels: Sequence[str],
    ) -> Mapping[str, DeltaChannelHistory]:
        if channels:
            raise ValueError("Latest checkpoint storage does not retain delta channel history")
        return {}
