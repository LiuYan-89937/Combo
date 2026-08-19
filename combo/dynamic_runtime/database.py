from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from combo.sqlite_runtime import DEFAULT_SQLITE_BUSY_TIMEOUT_MS, connect_sqlite


DYNAMIC_RUNTIME_DATABASE_SCHEMA = "dynamic_runtime_database.v27"
DYNAMIC_RUNTIME_SCHEMA_EPOCH = 3


@dataclass(frozen=True, slots=True)
class DynamicRuntimeMigrationResult:
    reset_performed: bool
    initialization_required: bool


@dataclass(frozen=True, slots=True)
class MigrationStep:
    version: int
    name: str
    statements: tuple[str, ...]


class DynamicRuntimeMigrationRegistry:
    def __init__(self, steps: Sequence[MigrationStep] | None = None) -> None:
        configured = tuple(steps or _default_migrations())
        versions = [step.version for step in configured]
        if versions != sorted(versions) or len(versions) != len(set(versions)):
            raise ValueError("dynamic runtime migrations must have unique ascending versions")
        self._steps = configured

    @property
    def target_version(self) -> int:
        return self._steps[-1].version if self._steps else 0

    def prepare(self, database: "DynamicRuntimeDatabase") -> DynamicRuntimeMigrationResult:
        if not database.path.exists() or database.path.stat().st_size == 0:
            return DynamicRuntimeMigrationResult(
                reset_performed=False,
                initialization_required=True,
            )
        with database.connection(query_only=True) as conn:
            epoch_table = conn.execute(
                """
                select 1 from sqlite_master
                where type = 'table' and name = 'dynamic_runtime_schema_epoch'
                """
            ).fetchone()
            if epoch_table is None:
                current_epoch = None
            else:
                rows = conn.execute(
                    "select epoch from dynamic_runtime_schema_epoch"
                ).fetchall()
                if len(rows) != 1:
                    raise RuntimeError("dynamic runtime database has an invalid schema epoch ledger")
                current_epoch = int(rows[0]["epoch"])
        if current_epoch == DYNAMIC_RUNTIME_SCHEMA_EPOCH:
            return DynamicRuntimeMigrationResult(
                reset_performed=False,
                initialization_required=False,
            )
        if current_epoch is not None and current_epoch > DYNAMIC_RUNTIME_SCHEMA_EPOCH:
            raise RuntimeError(
                "dynamic runtime database was created by a newer incompatible application "
                f"(database epoch {current_epoch}, supported epoch {DYNAMIC_RUNTIME_SCHEMA_EPOCH})"
            )
        remove_sqlite_database_files(database.path)
        return DynamicRuntimeMigrationResult(
            reset_performed=True,
            initialization_required=True,
        )

    def migrate(self, database: "DynamicRuntimeDatabase") -> DynamicRuntimeMigrationResult:
        preparation = self.prepare(database)
        database.path.parent.mkdir(parents=True, exist_ok=True)
        with database.connection() as conn:
            conn.execute("begin immediate")
            try:
                conn.execute(
                    """
                    create table if not exists dynamic_runtime_schema_migrations (
                      version integer primary key,
                      name text not null,
                      applied_at text not null
                    )
                    """
                )
                applied = {
                    int(row["version"])
                    for row in conn.execute("select version from dynamic_runtime_schema_migrations")
                }
                unknown = applied - {step.version for step in self._steps}
                if unknown:
                    raise RuntimeError(
                        "dynamic runtime database contains unknown migration versions: "
                        + ", ".join(str(value) for value in sorted(unknown))
                    )
                for step in self._steps:
                    if step.version in applied:
                        continue
                    for statement in step.statements:
                        conn.execute(statement)
                    conn.execute(
                        """
                        insert into dynamic_runtime_schema_migrations(version, name, applied_at)
                        values (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        """,
                        (step.version, step.name),
                    )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return preparation

    def verify(self, database: "DynamicRuntimeDatabase") -> None:
        expected = _schema_allowlist()
        with database.connection(query_only=True) as conn:
            version_rows = conn.execute(
                "select version from dynamic_runtime_schema_migrations order by version"
            ).fetchall()
            versions = tuple(int(row["version"]) for row in version_rows)
            if versions != tuple(step.version for step in self._steps):
                raise RuntimeError("dynamic runtime migration ledger does not match registry")
            actual = {
                (str(row["type"]), str(row["name"]))
                for row in conn.execute(
                    """
                    select type, name from sqlite_master
                    where name not like 'sqlite_%' and name not like 'dynamic_runtime_schema_migrations_autoindex%'
                    """
                )
            }
            unexpected = actual - expected
            missing = expected - actual
            if unexpected or missing:
                details = []
                if missing:
                    details.append("missing=" + ",".join(f"{kind}:{name}" for kind, name in sorted(missing)))
                if unexpected:
                    details.append("unexpected=" + ",".join(f"{kind}:{name}" for kind, name in sorted(unexpected)))
                raise RuntimeError("dynamic runtime schema allowlist mismatch: " + "; ".join(details))


class DynamicRuntimeDatabase:
    def __init__(
        self,
        path: str | Path,
        *,
        timeout_ms: int = DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.timeout_ms = timeout_ms

    @contextmanager
    def connection(self, *, query_only: bool = False) -> Iterator[sqlite3.Connection]:
        conn = connect_sqlite(
            self.path,
            timeout_ms=self.timeout_ms,
            foreign_keys=True,
            query_only=query_only,
        )
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("begin immediate")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise


def _default_migrations() -> tuple[MigrationStep, ...]:
    return (
        MigrationStep(
            version=1,
            name="authoritative_runtime_stores",
            statements=(
                """
                create table principals (
                  principal_id text primary key,
                  created_at text not null
                )
                """,
                """
                create table workspaces (
                  workspace_id text primary key,
                  principal_id text not null references principals(principal_id),
                  kind text not null check (kind in ('managed', 'mounted')),
                  managed_path text,
                  mount_record_id text,
                  revision integer not null check (revision >= 1),
                  status text not null check (status in ('active', 'detached', 'deleted')),
                  created_at text not null,
                  updated_at text not null,
                  check ((kind = 'managed' and managed_path is not null and mount_record_id is null)
                    or (kind = 'mounted' and managed_path is null and mount_record_id is not null))
                )
                """,
                """
                create table conversations (
                  session_id text primary key,
                  principal_id text not null references principals(principal_id),
                  workspace_id text not null references workspaces(workspace_id),
                  title text not null,
                  revision integer not null check (revision >= 1),
                  status text not null check (status in ('active', 'archived', 'deleted')),
                  created_at text not null,
                  updated_at text not null
                )
                """,
                """
                create table conversation_turns (
                  turn_id text primary key,
                  session_id text not null references conversations(session_id),
                  user_message_id text not null,
                  task_revision integer not null check (task_revision >= 1),
                  status text not null,
                  active_runtime_instance_id text,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  terminal_at text
                )
                """,
                """
                create index idx_conversation_turns_session
                on conversation_turns(session_id, created_at)
                """,
                """
                create table conversation_messages (
                  message_id text primary key,
                  session_id text not null references conversations(session_id),
                  turn_id text not null references conversation_turns(turn_id),
                  role text not null check (role in ('user', 'assistant', 'tool')),
                  status text not null check (status in ('pending', 'committed', 'cancelled')),
                  payload_json text not null,
                  created_at text not null,
                  committed_at text
                )
                """,
                """
                create index idx_conversation_messages_turn
                on conversation_messages(turn_id, created_at)
                """,
                """
                create table capability_snapshots (
                  snapshot_id text primary key,
                  content_digest text not null unique,
                  payload_json text not null,
                  created_at text not null
                )
                """,
                """
                create table runtime_instances (
                  runtime_instance_id text primary key,
                  request_id text not null unique,
                  session_id text not null references conversations(session_id),
                  turn_id text not null references conversation_turns(turn_id),
                  parent_runtime_instance_id text references runtime_instances(runtime_instance_id),
                  capability_snapshot_id text not null references capability_snapshots(snapshot_id),
                  status text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  terminal_at text
                )
                """,
                """
                create index idx_runtime_instances_session
                on runtime_instances(session_id, created_at)
                """,
                """
                create table command_inbox (
                  command_id text primary key,
                  client_instance_id text not null,
                  principal_id text not null references principals(principal_id),
                  session_id text not null references conversations(session_id),
                  status text not null,
                  receipt_revision integer not null check (receipt_revision >= 1),
                  envelope_json text not null,
                  receipt_json text not null,
                  queue_sequence integer not null unique,
                  received_at text not null,
                  updated_at text not null,
                  terminal_at text
                )
                """,
                """
                create index idx_command_inbox_claim
                on command_inbox(status, queue_sequence)
                """,
                """
                create table tool_calls (
                  tool_call_id text primary key,
                  runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  request_id text not null,
                  turn_id text not null references conversation_turns(turn_id),
                  status text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """,
                """
                create index idx_tool_calls_runtime
                on tool_calls(runtime_instance_id, created_at)
                """,
                """
                create table runtime_outbox (
                  outbox_id text primary key,
                  aggregate_kind text not null,
                  aggregate_id text not null,
                  aggregate_revision integer not null check (aggregate_revision >= 1),
                  event_id text not null unique,
                  event_kind text not null,
                  status text not null,
                  payload_json text not null,
                  publish_attempts integer not null default 0 check (publish_attempts >= 0),
                  next_attempt_at text,
                  published_at text,
                  error_code text,
                  created_at text not null,
                  updated_at text not null
                )
                """,
                """
                create index idx_runtime_outbox_publish
                on runtime_outbox(status, next_attempt_at, created_at)
                """,
                """
                create table revocations (
                  revocation_id text primary key,
                  kind text not null,
                  subject_id text not null,
                  subject_revision integer not null check (subject_revision >= 1),
                  payload_json text not null,
                  revoked_at text not null,
                  unique(kind, subject_id, subject_revision)
                )
                """,
                """
                create table delivery_commits (
                  delivery_id text primary key,
                  runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  request_id text not null,
                  status text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  terminal_at text
                )
                """,
                """
                create table delete_plans (
                  delete_plan_id text primary key,
                  principal_id text not null references principals(principal_id),
                  root_kind text not null,
                  root_id text not null,
                  status text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  terminal_at text
                )
                """,
            ),
        ),
        MigrationStep(
            version=2,
            name="authoritative_runtime_events",
            statements=(
                "alter table runtime_instances add column attempt_id text",
                "alter table runtime_instances add column last_event_sequence integer not null default 0 check (last_event_sequence >= 0)",
                """
                create table runtime_events (
                  event_id text primary key,
                  stream_id text not null,
                  sequence integer not null check (sequence >= 1),
                  runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  request_id text not null,
                  session_id text not null references conversations(session_id),
                  turn_id text not null references conversation_turns(turn_id),
                  event_kind text not null,
                  payload_json text not null,
                  created_at text not null,
                  unique(stream_id, sequence)
                )
                """,
                """
                create index idx_runtime_events_session
                on runtime_events(session_id, created_at)
                """,
                """
                create index idx_runtime_events_instance
                on runtime_events(runtime_instance_id, sequence)
                """,
            ),
        ),
        MigrationStep(
            version=3,
            name="authoritative_user_runtime_policies",
            statements=(
                """
                create table user_runtime_policies (
                  policy_id text primary key,
                  principal_id text not null unique references principals(principal_id),
                  revision integer not null check (revision >= 1),
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """,
            ),
        ),
        MigrationStep(
            version=4,
            name="command_priority_and_runtime_cancellation",
            statements=(
                "alter table command_inbox add column command_kind text",
                "update command_inbox set command_kind = json_extract(envelope_json, '$.payload.kind')",
                "create index idx_command_inbox_kind on command_inbox(status, command_kind, queue_sequence)",
                "alter table runtime_instances add column cancel_requested_at text",
                "alter table runtime_instances add column cancel_command_id text",
            ),
        ),
        MigrationStep(
            version=5,
            name="authoritative_session_event_sequence",
            statements=(
                """
                create table runtime_events_v5 (
                  event_id text primary key,
                  stream_id text not null,
                  sequence integer not null check (sequence >= 1),
                  session_sequence integer not null check (session_sequence >= 1),
                  runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  request_id text not null,
                  session_id text not null references conversations(session_id),
                  turn_id text not null references conversation_turns(turn_id),
                  event_kind text not null,
                  payload_json text not null,
                  created_at text not null,
                  unique(stream_id, sequence)
                )
                """,
                """
                insert into runtime_events_v5(
                  event_id, stream_id, sequence, session_sequence,
                  runtime_instance_id, request_id, session_id, turn_id,
                  event_kind, payload_json, created_at
                )
                select
                  event_id, stream_id, sequence,
                  row_number() over (partition by session_id order by created_at, rowid),
                  runtime_instance_id, request_id, session_id, turn_id,
                  event_kind,
                  json_set(
                    payload_json,
                    '$.session_sequence',
                    row_number() over (partition by session_id order by created_at, rowid)
                  ),
                  created_at
                from runtime_events
                """,
                "drop table runtime_events",
                "alter table runtime_events_v5 rename to runtime_events",
                "create index idx_runtime_events_session on runtime_events(session_id, session_sequence)",
                "create index idx_runtime_events_instance on runtime_events(runtime_instance_id, sequence)",
                "create unique index idx_runtime_events_session_sequence on runtime_events(session_id, session_sequence)",
            ),
        ),
        MigrationStep(
            version=6,
            name="authoritative_capability_registry",
            statements=(
                """
                create table capability_drafts (
                  capability_id text primary key,
                  kind text not null check (kind in ('skill','tool','mcp_server','mcp_tool','dependency')),
                  draft_revision integer not null check (draft_revision >= 1),
                  namespace text not null,
                  content_digest text not null,
                  payload_json text not null,
                  updated_by_principal_id text not null references principals(principal_id),
                  created_at text not null,
                  updated_at text not null
                )
                """,
                "create unique index idx_capability_drafts_namespace on capability_drafts(kind, namespace)",
                """
                create table capability_validation_receipts (
                  receipt_id text primary key,
                  capability_id text not null,
                  kind text not null check (kind in ('skill','tool','mcp_server','mcp_tool','dependency')),
                  draft_revision integer not null check (draft_revision >= 1),
                  content_digest text not null,
                  status text not null check (status in ('passed','failed')),
                  payload_json text not null,
                  created_at text not null,
                  unique(capability_id, draft_revision, content_digest, receipt_id)
                )
                """,
                "create index idx_capability_validation_source on capability_validation_receipts(capability_id, draft_revision, content_digest)",
                """
                create table capability_revisions (
                  capability_id text not null,
                  kind text not null check (kind in ('skill','tool','mcp_server','mcp_tool','dependency')),
                  revision integer not null check (revision >= 1),
                  namespace text not null,
                  content_digest text not null,
                  validation_receipt_id text not null,
                  payload_json text not null,
                  published_by_principal_id text not null references principals(principal_id),
                  published_at text not null,
                  primary key(capability_id, revision),
                  unique(capability_id, content_digest)
                )
                """,
                "create index idx_capability_revisions_namespace on capability_revisions(kind, namespace, revision)",
                """
                create table capability_index_revisions (
                  index_revision_id text primary key,
                  capability_id text not null,
                  source_revision integer not null check (source_revision >= 1),
                  source_digest text not null,
                  index_digest text not null,
                  payload_json text not null,
                  created_at text not null,
                  foreign key(capability_id, source_revision)
                    references capability_revisions(capability_id, revision),
                  unique(capability_id, source_revision, index_digest)
                )
                """,
                "create index idx_capability_index_source on capability_index_revisions(capability_id, source_revision)",
                """
                create table capability_activations (
                  capability_id text primary key,
                  kind text not null check (kind in ('skill','tool','mcp_server','mcp_tool','dependency')),
                  namespace text not null,
                  activation_revision integer not null check (activation_revision >= 1),
                  status text not null check (status in ('active','inactive')),
                  revision integer,
                  content_digest text,
                  index_revision_id text references capability_index_revisions(index_revision_id),
                  payload_json text not null,
                  changed_by_principal_id text not null references principals(principal_id),
                  changed_at text not null,
                  foreign key(capability_id, revision)
                    references capability_revisions(capability_id, revision),
                  check (
                    (status = 'active' and revision is not null and content_digest is not null and index_revision_id is not null)
                    or (status = 'inactive' and revision is null and content_digest is null and index_revision_id is null)
                  )
                )
                """,
                "create unique index idx_capability_active_namespace on capability_activations(kind, namespace) where status = 'active'",
                """
                create table capability_tombstones (
                  capability_id text primary key,
                  kind text not null check (kind in ('skill','tool','mcp_server','mcp_tool','dependency')),
                  last_revision integer not null check (last_revision >= 1),
                  content_digest text not null,
                  payload_json text not null,
                  deleted_by_principal_id text not null references principals(principal_id),
                  reason text not null,
                  deleted_at text not null,
                  foreign key(capability_id, last_revision)
                    references capability_revisions(capability_id, revision)
                )
                """,
            ),
        ),
        MigrationStep(
            version=7,
            name="capability_resolution_receipts",
            statements=(
                """
                create table capability_health_receipts (
                  receipt_id text primary key,
                  capability_id text not null,
                  kind text not null check (kind in ('skill','tool','mcp_server','mcp_tool','dependency')),
                  revision integer not null check (revision >= 1),
                  content_digest text not null,
                  status text not null check (status in ('healthy','unhealthy')),
                  payload_json text not null,
                  checked_at text not null,
                  valid_until text,
                  foreign key(capability_id, revision)
                    references capability_revisions(capability_id, revision),
                  unique(capability_id, revision, content_digest, receipt_id)
                )
                """,
                "create index idx_capability_health_source on capability_health_receipts(capability_id, revision, content_digest, checked_at)",
                """
                create table dependency_environment_receipts (
                  receipt_id text primary key,
                  dependency_closure_digest text not null,
                  projection_digest text not null,
                  status text not null check (status in ('ready','invalid')),
                  environment_id text not null,
                  environment_revision integer not null check (environment_revision >= 1),
                  environment_content_digest text not null,
                  payload_json text not null,
                  created_at text not null,
                  unique(dependency_closure_digest, projection_digest, receipt_id)
                )
                """,
                "create index idx_dependency_environment_resolution on dependency_environment_receipts(dependency_closure_digest, projection_digest, created_at)",
            ),
        ),
        MigrationStep(
            version=8,
            name="capability_approval_grants",
            statements=(
                """
                create table capability_approval_grants (
                  grant_id text primary key,
                  principal_id text not null references principals(principal_id),
                  capability_id text not null,
                  capability_revision integer not null check (capability_revision >= 1),
                  capability_content_digest text not null,
                  model_alias text not null,
                  resource_scope_digest text not null,
                  policy_id text not null,
                  policy_revision integer not null check (policy_revision >= 1),
                  status text not null check (status in ('active','revoked','expired')),
                  payload_json text not null,
                  created_at text not null,
                  expires_at text,
                  revoked_at text,
                  foreign key(capability_id, capability_revision)
                    references capability_revisions(capability_id, revision)
                )
                """,
                """
                create unique index idx_capability_approval_active_scope
                on capability_approval_grants(
                  principal_id,
                  capability_id,
                  capability_revision,
                  capability_content_digest,
                  model_alias,
                  resource_scope_digest,
                  policy_id,
                  policy_revision
                ) where status = 'active'
                """,
                """
                create index idx_capability_approval_lookup
                on capability_approval_grants(
                  principal_id,
                  capability_id,
                  capability_revision,
                  model_alias,
                  status,
                  expires_at
                )
                """,
            ),
        ),
        MigrationStep(
            version=9,
            name="runtime_model_usage_ledger",
            statements=(
                """
                create table runtime_model_usage (
                  usage_id text primary key,
                  observation_event_id text not null unique,
                  principal_id text not null references principals(principal_id),
                  request_id text not null,
                  runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  attempt_id text not null,
                  session_id text not null references conversations(session_id),
                  turn_id text not null references conversation_turns(turn_id),
                  workspace_id text not null references workspaces(workspace_id),
                  task_revision integer not null check (task_revision >= 1),
                  runtime_role text not null check (runtime_role in ('main','temporary')),
                  strategy text not null check (strategy in ('react','plan_and_execute')),
                  node_id text not null,
                  model_operation text not null check (model_operation in ('main_turn','temporary_turn')),
                  model_profile_id text not null,
                  model_profile_revision integer not null check (model_profile_revision >= 1),
                  provider text not null,
                  model_name text not null,
                  input_tokens integer not null check (input_tokens >= 0),
                  output_tokens integer not null check (output_tokens >= 0),
                  total_tokens integer not null check (total_tokens >= 0),
                  reasoning_tokens integer not null check (reasoning_tokens >= 0),
                  cache_read_tokens integer not null check (cache_read_tokens >= 0),
                  cache_write_tokens integer not null check (cache_write_tokens >= 0),
                  payload_json text not null,
                  created_at text not null
                )
                """,
                "create index idx_runtime_model_usage_created on runtime_model_usage(created_at)",
                "create index idx_runtime_model_usage_profile on runtime_model_usage(model_profile_id, created_at)",
                "create index idx_runtime_model_usage_runtime on runtime_model_usage(runtime_instance_id, created_at)",
                "create index idx_runtime_model_usage_workspace on runtime_model_usage(workspace_id, created_at)",
            ),
        ),
        MigrationStep(
            version=10,
            name="scoped_memory_revisions",
            statements=(
                """
                create table memory_revisions (
                  memory_id text not null,
                  revision integer not null check (revision >= 1),
                  principal_id text not null references principals(principal_id),
                  scope text not null check (scope in ('user','workspace')),
                  workspace_id text references workspaces(workspace_id),
                  kind text not null check (kind in ('constraint','preference','decision','fact','artifact')),
                  status text not null check (status in ('active','deleted')),
                  content_digest text not null,
                  payload_json text not null,
                  source_session_id text not null references conversations(session_id),
                  source_turn_id text not null references conversation_turns(turn_id),
                  created_by_runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  created_at text not null,
                  primary key(memory_id, revision),
                  check ((scope = 'user' and workspace_id is null)
                    or (scope = 'workspace' and workspace_id is not null))
                )
                """,
                "create index idx_memory_revisions_owner on memory_revisions(principal_id, scope, workspace_id, created_at)",
                "create index idx_memory_revisions_digest on memory_revisions(principal_id, scope, workspace_id, content_digest)",
                """
                create table memory_heads (
                  memory_id text primary key,
                  revision integer not null check (revision >= 1),
                  principal_id text not null references principals(principal_id),
                  scope text not null check (scope in ('user','workspace')),
                  workspace_id text references workspaces(workspace_id),
                  status text not null check (status in ('active','deleted')),
                  content_digest text not null,
                  updated_at text not null,
                  foreign key(memory_id, revision) references memory_revisions(memory_id, revision),
                  check ((scope = 'user' and workspace_id is null)
                    or (scope = 'workspace' and workspace_id is not null))
                )
                """,
                "create index idx_memory_heads_owner on memory_heads(principal_id, scope, workspace_id, status, updated_at)",
            ),
        ),
        MigrationStep(
            version=11,
            name="delegated_runtime_authority",
            statements=(
                """
                create table delegation_grants (
                  grant_id text primary key,
                  principal_id text not null references principals(principal_id),
                  parent_runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  child_runtime_instance_id text not null unique references runtime_instances(runtime_instance_id),
                  task_id text not null,
                  task_revision integer not null check (task_revision >= 1),
                  parent_task_revision integer not null check (parent_task_revision >= 1),
                  parent_capability_snapshot_id text not null references capability_snapshots(snapshot_id),
                  child_capability_snapshot_id text not null references capability_snapshots(snapshot_id),
                  workspace_id text not null references workspaces(workspace_id),
                  status text not null check (status in ('active','revoked','expired')),
                  state_revision integer not null check (state_revision >= 1),
                  content_digest text not null unique,
                  payload_json text not null,
                  expires_at text not null,
                  created_at text not null,
                  updated_at text not null,
                  unique(task_id, task_revision)
                )
                """,
                "create index idx_delegation_grants_parent on delegation_grants(parent_runtime_instance_id, status, expires_at)",
                "create index idx_delegation_grants_principal on delegation_grants(principal_id, status, expires_at)",
                """
                create table delegated_task_revisions (
                  task_id text not null,
                  task_revision integer not null check (task_revision >= 1),
                  parent_task_revision integer not null check (parent_task_revision >= 1),
                  principal_id text not null references principals(principal_id),
                  parent_runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  child_runtime_instance_id text not null unique references runtime_instances(runtime_instance_id),
                  delegation_grant_id text not null unique references delegation_grants(grant_id),
                  capability_snapshot_id text not null references capability_snapshots(snapshot_id),
                  workspace_id text not null references workspaces(workspace_id),
                  status text not null check (status in ('queued','running','waiting','completed','failed','cancelled','superseded')),
                  claim_id text,
                  claim_expires_at text,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  terminal_at text,
                  primary key(task_id, task_revision),
                  check ((status in ('completed','failed','cancelled','superseded')) = (terminal_at is not null)),
                  check ((claim_id is null and claim_expires_at is null)
                    or (claim_id is not null and claim_expires_at is not null))
                )
                """,
                "create index idx_delegated_tasks_parent on delegated_task_revisions(parent_runtime_instance_id, status, created_at)",
                "create index idx_delegated_tasks_principal on delegated_task_revisions(principal_id, status, created_at)",
                "create index idx_delegated_tasks_claim on delegated_task_revisions(status, claim_expires_at, created_at)",
                """
                create table delegated_task_events (
                  event_id text primary key,
                  task_id text not null,
                  task_revision integer not null,
                  sequence integer not null check (sequence >= 1),
                  event_type text not null check (event_type in ('activity','question','approval_required','capability_request','artifact','result','failed','cancelled')),
                  principal_id text not null references principals(principal_id),
                  parent_runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  child_runtime_instance_id text not null references runtime_instances(runtime_instance_id),
                  child_attempt_id text not null,
                  payload_json text not null,
                  created_at text not null,
                  unique(task_id, task_revision, sequence),
                  foreign key(task_id, task_revision) references delegated_task_revisions(task_id, task_revision)
                )
                """,
                "create index idx_delegated_task_events_parent on delegated_task_events(parent_runtime_instance_id, created_at)",
            ),
        ),
        MigrationStep(
            version=12,
            name="global_knowledge_and_workspace_scheduler",
            statements=(
                """
                create table knowledge_sources (
                  source_id text primary key,
                  revision integer not null check (revision >= 1),
                  status text not null check (status in ('ready','indexing','failed','deleted')),
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """,
                "create index idx_knowledge_sources_status on knowledge_sources(status, updated_at)",
                """
                create table knowledge_documents (
                  document_id text primary key,
                  source_id text not null references knowledge_sources(source_id),
                  revision integer not null check (revision >= 1),
                  status text not null check (status in ('ready','deleted')),
                  title text not null,
                  mime_type text not null,
                  content text not null,
                  content_digest text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """,
                "create index idx_knowledge_documents_source on knowledge_documents(source_id, status, updated_at)",
                """
                create table scheduler_jobs (
                  job_id text primary key,
                  workspace_id text not null references workspaces(workspace_id),
                  revision integer not null check (revision >= 1),
                  status text not null check (status in ('enabled','paused','deleted')),
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """,
                "create index idx_scheduler_jobs_workspace on scheduler_jobs(workspace_id, status, updated_at)",
                """
                create table scheduler_runs (
                  run_id text primary key,
                  job_id text not null references scheduler_jobs(job_id),
                  status text not null check (status in ('queued','running','completed','failed','cancelled')),
                  runtime_instance_id text references runtime_instances(runtime_instance_id),
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  terminal_at text
                )
                """,
                "create index idx_scheduler_runs_job on scheduler_runs(job_id, created_at)",
            ),
        ),
        MigrationStep(
            version=13,
            name="workspace_display_identity",
            statements=(
                "alter table workspaces add column title text",
            ),
        ),
        MigrationStep(
            version=14,
            name="workspace_mount_records",
            statements=(
                """
                create table workspace_mount_records (
                  mount_record_id text primary key,
                  principal_id text not null references principals(principal_id),
                  source_path text not null,
                  title text not null,
                  status text not null check (status in ('active','detached','deleted')),
                  revision integer not null check (revision >= 1),
                  created_at text not null,
                  updated_at text not null
                )
                """,
                "create index idx_workspace_mounts_owner on workspace_mount_records(principal_id, status, updated_at)",
            ),
        ),
        MigrationStep(
            version=15,
            name="workspace_project_mode",
            statements=(
                "alter table workspaces add column mode text not null default 'project' check (mode in ('isolated', 'project'))",
            ),
        ),
        MigrationStep(
            version=16,
            name="delegated_task_completion_mailbox",
            statements=(
                """
                create table delegated_task_notifications (
                  event_id text primary key,
                  task_id text not null,
                  task_revision integer not null,
                  principal_id text not null references principals(principal_id),
                  session_id text not null references conversations(session_id),
                  payload_json text not null,
                  delivered_runtime_instance_id text references runtime_instances(runtime_instance_id),
                  created_at text not null,
                  delivered_at text
                )
                """,
                "create index idx_delegated_task_notifications_delivery on delegated_task_notifications(principal_id, session_id, delivered_at, created_at)",
            ),
        ),
        MigrationStep(
            version=17,
            name="schema_compatibility_epoch",
            statements=(
                f"""
                create table dynamic_runtime_schema_epoch (
                  epoch integer primary key check (epoch = {DYNAMIC_RUNTIME_SCHEMA_EPOCH}),
                  initialized_at text not null
                )
                """,
                f"""
                insert into dynamic_runtime_schema_epoch(epoch, initialized_at)
                values ({DYNAMIC_RUNTIME_SCHEMA_EPOCH}, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
            ),
        ),
        MigrationStep(
            version=18,
            name="hybrid_capability_search",
            statements=(
                """
                create table capability_search_generations (
                  generation_id text primary key,
                  dataset_digest text not null,
                  search_mode text not null check (search_mode in ('lexical', 'hybrid')),
                  embedding_fingerprint text,
                  embedding_profile_id text,
                  embedding_dimensions integer check (embedding_dimensions is null or embedding_dimensions >= 1),
                  status text not null check (status in ('building', 'active', 'retired', 'failed')),
                  diagnostic text,
                  created_at text not null,
                  activated_at text,
                  unique(dataset_digest, search_mode, embedding_fingerprint)
                )
                """,
                "create index idx_capability_search_generation_status on capability_search_generations(status, created_at)",
                """
                create table capability_search_documents (
                  generation_id text not null references capability_search_generations(generation_id) on delete cascade,
                  capability_id text not null,
                  index_revision_id text not null,
                  kind text not null,
                  display_name text not null,
                  description text not null,
                  keywords_json text not null,
                  parameter_text text not null,
                  searchable_text text not null,
                  embedding_json text,
                  primary key(generation_id, capability_id)
                )
                """,
                "create index idx_capability_search_document_capability on capability_search_documents(capability_id, generation_id)",
                """
                create table capability_search_active_generation (
                  singleton integer primary key check (singleton = 1),
                  generation_id text not null references capability_search_generations(generation_id),
                  changed_at text not null
                )
                """,
                """
                create table capability_search_receipts (
                  receipt_id text primary key,
                  generation_id text not null references capability_search_generations(generation_id),
                  query_digest text not null,
                  candidate_digest text not null,
                  result_json text not null,
                  created_at text not null
                )
                """,
                "create index idx_capability_search_receipt_generation on capability_search_receipts(generation_id, created_at)",
                """
                create virtual table capability_search_fts using fts5(
                  generation_id unindexed,
                  capability_id unindexed,
                  searchable_text,
                  tokenize='unicode61 remove_diacritics 2'
                )
                """,
            ),
        ),
        MigrationStep(
            version=19,
            name="detachable_memory_provenance",
            statements=(
                """
                create table memory_revisions_v19 (
                  memory_id text not null,
                  revision integer not null check (revision >= 1),
                  principal_id text not null references principals(principal_id),
                  scope text not null check (scope in ('user','workspace')),
                  workspace_id text references workspaces(workspace_id),
                  kind text not null check (kind in ('constraint','preference','decision','fact','artifact')),
                  status text not null check (status in ('active','deleted')),
                  content_digest text not null,
                  payload_json text not null,
                  source_session_id text references conversations(session_id),
                  source_turn_id text references conversation_turns(turn_id),
                  created_by_runtime_instance_id text references runtime_instances(runtime_instance_id),
                  created_at text not null,
                  primary key(memory_id, revision),
                  check ((scope = 'user' and workspace_id is null)
                    or (scope = 'workspace' and workspace_id is not null))
                )
                """,
                """
                insert into memory_revisions_v19
                select * from memory_revisions
                """,
                """
                create table memory_heads_v19 (
                  memory_id text primary key,
                  revision integer not null check (revision >= 1),
                  principal_id text not null references principals(principal_id),
                  scope text not null check (scope in ('user','workspace')),
                  workspace_id text references workspaces(workspace_id),
                  status text not null check (status in ('active','deleted')),
                  content_digest text not null,
                  updated_at text not null,
                  foreign key(memory_id, revision) references memory_revisions_v19(memory_id, revision),
                  check ((scope = 'user' and workspace_id is null)
                    or (scope = 'workspace' and workspace_id is not null))
                )
                """,
                "insert into memory_heads_v19 select * from memory_heads",
                "drop table memory_heads",
                "drop table memory_revisions",
                "alter table memory_revisions_v19 rename to memory_revisions",
                "alter table memory_heads_v19 rename to memory_heads",
                "create index idx_memory_revisions_owner on memory_revisions(principal_id, scope, workspace_id, created_at)",
                "create index idx_memory_revisions_digest on memory_revisions(principal_id, scope, workspace_id, content_digest)",
                "create index idx_memory_heads_owner on memory_heads(principal_id, scope, workspace_id, status, updated_at)",
            ),
        ),
        MigrationStep(
            version=20,
            name="hybrid_memory_search",
            statements=(
                """
                create table memory_search_generations (
                  generation_id text primary key,
                  dataset_digest text not null,
                  search_mode text not null check (search_mode in ('lexical', 'hybrid')),
                  embedding_fingerprint text,
                  embedding_profile_id text,
                  embedding_dimensions integer check (embedding_dimensions is null or embedding_dimensions >= 1),
                  status text not null check (status in ('building', 'active', 'retired', 'failed')),
                  diagnostic text,
                  created_at text not null,
                  activated_at text,
                  unique(dataset_digest, search_mode, embedding_fingerprint)
                )
                """,
                "create index idx_memory_search_generation_status on memory_search_generations(status, created_at)",
                """
                create table memory_search_documents (
                  generation_id text not null references memory_search_generations(generation_id) on delete cascade,
                  memory_id text not null,
                  memory_revision integer not null,
                  principal_id text not null,
                  scope text not null,
                  workspace_id text,
                  content_digest text not null,
                  searchable_text text not null,
                  embedding_json text,
                  primary key(generation_id, memory_id)
                )
                """,
                "create index idx_memory_search_document_owner on memory_search_documents(principal_id, workspace_id, generation_id)",
                """
                create table memory_search_active_generation (
                  singleton integer primary key check (singleton = 1),
                  generation_id text not null references memory_search_generations(generation_id),
                  changed_at text not null
                )
                """,
                """
                create virtual table memory_search_fts using fts5(
                  generation_id unindexed,
                  memory_id unindexed,
                  searchable_text,
                  tokenize='unicode61 remove_diacritics 2'
                )
                """,
            ),
        ),
        MigrationStep(
            version=21,
            name="scheduler_run_container",
            statements=(
                "alter table scheduler_jobs add column next_fire_at text",
                "alter table scheduler_jobs add column last_fire_at text",
                "alter table conversations add column source text not null default 'user' check (source in ('user', 'scheduler'))",
                "alter table scheduler_runs rename to scheduler_runs_v20",
                "drop index idx_scheduler_runs_job",
                """
                create table scheduler_runs (
                  run_id text primary key,
                  job_id text not null references scheduler_jobs(job_id),
                  status text not null check (status in ('queued','running','waiting_approval','waiting_external','completed','failed','cancelled')),
                  runtime_instance_id text references runtime_instances(runtime_instance_id),
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  terminal_at text
                )
                """,
                """
                insert into scheduler_runs(run_id, job_id, status, runtime_instance_id, payload_json, created_at, updated_at, terminal_at)
                select run_id, job_id, status, runtime_instance_id, payload_json, created_at, updated_at, terminal_at
                from scheduler_runs_v20
                """,
                "drop table scheduler_runs_v20",
                "create index idx_scheduler_runs_job on scheduler_runs(job_id, created_at)",
                "create unique index idx_scheduler_runs_fire on scheduler_runs(job_id, json_extract(payload_json, '$.scheduled_fire_at'))",
                """
                create table scheduler_run_events (
                  run_id text not null references scheduler_runs(run_id) on delete cascade,
                  sequence integer not null check (sequence >= 1),
                  event_type text not null,
                  payload_json text not null,
                  created_at text not null,
                  primary key(run_id, sequence)
                )
                """,
                "create index idx_scheduler_run_events_created on scheduler_run_events(run_id, created_at)",
            ),
        ),
        MigrationStep(
            version=22,
            name="scheduler_source_conversation",
            statements=(
                """
                update scheduler_jobs
                set payload_json = json_set(
                  payload_json,
                  '$.source_session_id',
                  (
                    select turn.session_id
                    from tool_calls as tool
                    join conversation_turns as turn on turn.turn_id = tool.turn_id
                    where json_extract(tool.payload_json, '$.model_alias') = 'scheduler'
                      and json_extract(tool.payload_json, '$.result.action') = 'create'
                      and json_extract(tool.payload_json, '$.result.job.job_id') = scheduler_jobs.job_id
                    order by tool.updated_at desc
                    limit 1
                  )
                )
                where json_extract(payload_json, '$.source_session_id') is null
                  and exists (
                    select 1
                    from tool_calls as tool
                    where json_extract(tool.payload_json, '$.model_alias') = 'scheduler'
                      and json_extract(tool.payload_json, '$.result.action') = 'create'
                      and json_extract(tool.payload_json, '$.result.job.job_id') = scheduler_jobs.job_id
                  )
                """,
            ),
        ),
        MigrationStep(
            version=23,
            name="explicit_execution_modes",
            statements=(
                """
                update user_runtime_policies
                set payload_json = json_set(payload_json, '$.execution_preference', 'react')
                where json_extract(payload_json, '$.execution_preference') = 'auto'
                """,
                """
                update scheduler_jobs
                set payload_json = json_set(payload_json, '$.strategy', 'react')
                where json_extract(payload_json, '$.strategy') = 'auto'
                """,
                """
                update command_inbox
                set envelope_json = json_set(envelope_json, '$.payload.execution_preference', 'react')
                where json_extract(envelope_json, '$.payload.execution_preference') = 'auto'
                """,
                """
                update runtime_instances
                set payload_json = json_set(
                  json_remove(payload_json, '$.request.route_decision'),
                  '$.request.capability_requirements',
                  coalesce(
                    json_extract(payload_json, '$.request.route_decision.capability_requirements'),
                    json('[]')
                  )
                )
                where json_type(payload_json, '$.request.route_decision') is not null
                """,
            ),
        ),
        MigrationStep(
            version=24,
            name="hybrid_knowledge_search",
            statements=(
                """
                create table knowledge_search_generations (
                  generation_id text primary key,
                  dataset_digest text not null,
                  search_mode text not null check (search_mode in ('lexical','hybrid')),
                  embedding_fingerprint text,
                  embedding_profile_id text,
                  embedding_dimensions integer,
                  status text not null check (status in ('building','active','retired','failed')),
                  diagnostic text,
                  created_at text not null,
                  activated_at text
                )
                """,
                "create index idx_knowledge_search_generation_status on knowledge_search_generations(status, created_at)",
                """
                create table knowledge_search_chunks (
                  generation_id text not null references knowledge_search_generations(generation_id) on delete cascade,
                  chunk_id text not null,
                  source_id text not null,
                  document_id text not null,
                  chunk_index integer not null,
                  title text not null,
                  content text not null,
                  content_digest text not null,
                  embedding_json text,
                  primary key(generation_id, chunk_id)
                )
                """,
                "create index idx_knowledge_search_chunk_source on knowledge_search_chunks(generation_id, source_id, document_id)",
                """
                create table knowledge_search_active_generation (
                  singleton integer primary key check(singleton = 1),
                  generation_id text not null references knowledge_search_generations(generation_id),
                  changed_at text not null
                )
                """,
                """
                create virtual table knowledge_search_fts using fts5(
                  generation_id unindexed,
                  chunk_id unindexed,
                  title,
                  content,
                  tokenize='unicode61'
                )
                """,
                """
                create table knowledge_search_settings (
                  singleton integer primary key check(singleton = 1),
                  revision integer not null,
                  payload_json text not null,
                  updated_at text not null
                )
                """,
            ),
        ),
        MigrationStep(
            version=25,
            name="scoped_capability_search",
            statements=(
                """
                alter table capability_search_documents
                add column search_scope text not null default 'capability_catalog'
                  check (search_scope in ('capability_catalog','mcp_catalog'))
                """,
                """
                alter table capability_search_documents
                add column parent_capability_id text
                """,
                """
                create index idx_capability_search_document_scope
                on capability_search_documents(generation_id, search_scope, parent_capability_id)
                """,
            ),
        ),
        MigrationStep(
            version=26,
            name="conversation_context_snapshots",
            statements=(
                """
                create table conversation_context_snapshots (
                  snapshot_id text primary key,
                  session_id text not null references conversations(session_id),
                  principal_id text not null references principals(principal_id),
                  through_task_revision integer not null check (through_task_revision >= 1),
                  payload_json text not null,
                  created_at text not null
                )
                """,
                """
                create index idx_conversation_context_snapshots_session
                on conversation_context_snapshots(session_id, created_at)
                """,
            ),
        ),
        MigrationStep(
            version=27,
            name="three_level_reasoning_intensity",
            statements=(
                """
                update user_runtime_policies
                set payload_json = json_set(payload_json, '$.reasoning_intensity', 2)
                where json_type(payload_json, '$.reasoning_intensity') is null
                   or json_extract(payload_json, '$.reasoning_intensity') not in (1, 2, 3)
                """,
            ),
        ),
    )


def remove_sqlite_database_files(path: str | Path) -> None:
    database_path = Path(path).expanduser().resolve()
    for candidate in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        candidate.unlink(missing_ok=True)


def _schema_allowlist() -> set[tuple[str, str]]:
    return {
        ("table", "dynamic_runtime_schema_migrations"),
        ("table", "dynamic_runtime_schema_epoch"),
        ("table", "principals"),
        ("table", "workspaces"),
        ("table", "conversations"),
        ("table", "conversation_turns"),
        ("index", "idx_conversation_turns_session"),
        ("table", "conversation_messages"),
        ("index", "idx_conversation_messages_turn"),
        ("table", "conversation_context_snapshots"),
        ("index", "idx_conversation_context_snapshots_session"),
        ("table", "capability_snapshots"),
        ("table", "runtime_instances"),
        ("index", "idx_runtime_instances_session"),
        ("table", "command_inbox"),
        ("index", "idx_command_inbox_claim"),
        ("index", "idx_command_inbox_kind"),
        ("table", "tool_calls"),
        ("index", "idx_tool_calls_runtime"),
        ("table", "runtime_outbox"),
        ("index", "idx_runtime_outbox_publish"),
        ("table", "runtime_events"),
        ("index", "idx_runtime_events_session"),
        ("index", "idx_runtime_events_instance"),
        ("index", "idx_runtime_events_session_sequence"),
        ("table", "revocations"),
        ("table", "delivery_commits"),
        ("table", "delete_plans"),
        ("table", "user_runtime_policies"),
        ("table", "capability_drafts"),
        ("index", "idx_capability_drafts_namespace"),
        ("table", "capability_validation_receipts"),
        ("index", "idx_capability_validation_source"),
        ("table", "capability_revisions"),
        ("index", "idx_capability_revisions_namespace"),
        ("table", "capability_index_revisions"),
        ("index", "idx_capability_index_source"),
        ("table", "capability_activations"),
        ("index", "idx_capability_active_namespace"),
        ("table", "capability_tombstones"),
        ("table", "capability_health_receipts"),
        ("index", "idx_capability_health_source"),
        ("table", "dependency_environment_receipts"),
        ("index", "idx_dependency_environment_resolution"),
        ("table", "capability_approval_grants"),
        ("index", "idx_capability_approval_active_scope"),
        ("index", "idx_capability_approval_lookup"),
        ("table", "runtime_model_usage"),
        ("index", "idx_runtime_model_usage_created"),
        ("index", "idx_runtime_model_usage_profile"),
        ("index", "idx_runtime_model_usage_runtime"),
        ("index", "idx_runtime_model_usage_workspace"),
        ("table", "memory_revisions"),
        ("index", "idx_memory_revisions_owner"),
        ("index", "idx_memory_revisions_digest"),
        ("table", "memory_heads"),
        ("index", "idx_memory_heads_owner"),
        ("table", "memory_search_generations"),
        ("index", "idx_memory_search_generation_status"),
        ("table", "memory_search_documents"),
        ("index", "idx_memory_search_document_owner"),
        ("table", "memory_search_active_generation"),
        ("table", "memory_search_fts"),
        ("table", "memory_search_fts_data"),
        ("table", "memory_search_fts_idx"),
        ("table", "memory_search_fts_content"),
        ("table", "memory_search_fts_docsize"),
        ("table", "memory_search_fts_config"),
        ("table", "delegation_grants"),
        ("index", "idx_delegation_grants_parent"),
        ("index", "idx_delegation_grants_principal"),
        ("table", "delegated_task_revisions"),
        ("index", "idx_delegated_tasks_parent"),
        ("index", "idx_delegated_tasks_principal"),
        ("index", "idx_delegated_tasks_claim"),
        ("table", "delegated_task_events"),
        ("index", "idx_delegated_task_events_parent"),
        ("table", "delegated_task_notifications"),
        ("index", "idx_delegated_task_notifications_delivery"),
        ("table", "knowledge_sources"),
        ("index", "idx_knowledge_sources_status"),
        ("table", "knowledge_documents"),
        ("index", "idx_knowledge_documents_source"),
        ("table", "knowledge_search_generations"),
        ("index", "idx_knowledge_search_generation_status"),
        ("table", "knowledge_search_chunks"),
        ("index", "idx_knowledge_search_chunk_source"),
        ("table", "knowledge_search_active_generation"),
        ("table", "knowledge_search_settings"),
        ("table", "knowledge_search_fts"),
        ("table", "knowledge_search_fts_data"),
        ("table", "knowledge_search_fts_idx"),
        ("table", "knowledge_search_fts_content"),
        ("table", "knowledge_search_fts_docsize"),
        ("table", "knowledge_search_fts_config"),
        ("table", "scheduler_jobs"),
        ("index", "idx_scheduler_jobs_workspace"),
        ("table", "scheduler_runs"),
        ("index", "idx_scheduler_runs_job"),
        ("index", "idx_scheduler_runs_fire"),
        ("table", "scheduler_run_events"),
        ("index", "idx_scheduler_run_events_created"),
        ("table", "workspace_mount_records"),
        ("index", "idx_workspace_mounts_owner"),
        ("table", "capability_search_generations"),
        ("index", "idx_capability_search_generation_status"),
        ("table", "capability_search_documents"),
        ("index", "idx_capability_search_document_capability"),
        ("index", "idx_capability_search_document_scope"),
        ("table", "capability_search_active_generation"),
        ("table", "capability_search_receipts"),
        ("index", "idx_capability_search_receipt_generation"),
        ("table", "capability_search_fts"),
        ("table", "capability_search_fts_data"),
        ("table", "capability_search_fts_idx"),
        ("table", "capability_search_fts_content"),
        ("table", "capability_search_fts_docsize"),
        ("table", "capability_search_fts_config"),
    }
