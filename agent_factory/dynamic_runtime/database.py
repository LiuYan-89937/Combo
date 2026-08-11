from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from agent_factory.sqlite_runtime import DEFAULT_SQLITE_BUSY_TIMEOUT_MS, connect_sqlite


DYNAMIC_RUNTIME_DATABASE_SCHEMA = "dynamic_runtime_database.v9"


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

    def migrate(self, database: "DynamicRuntimeDatabase") -> None:
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
                  generation integer not null check (generation >= 1),
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
                  claimed_generation integer,
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
                create table application_generations (
                  generation_id text primary key,
                  generation integer not null unique check (generation >= 1),
                  status text not null,
                  payload_json text not null,
                  lease_expires_at text not null,
                  started_at text not null,
                  updated_at text not null,
                  closed_at text
                )
                """,
                """
                create table cutover_manifests (
                  cutover_id text primary key,
                  manifest_revision integer not null check (manifest_revision >= 1),
                  source_generation integer not null,
                  target_generation integer not null,
                  status text not null,
                  payload_json text not null,
                  created_at text not null,
                  updated_at text not null,
                  committed_at text,
                  check (source_generation <> target_generation)
                )
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
    )


def _schema_allowlist() -> set[tuple[str, str]]:
    return {
        ("table", "dynamic_runtime_schema_migrations"),
        ("table", "principals"),
        ("table", "workspaces"),
        ("table", "conversations"),
        ("table", "conversation_turns"),
        ("index", "idx_conversation_turns_session"),
        ("table", "conversation_messages"),
        ("index", "idx_conversation_messages_turn"),
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
        ("table", "application_generations"),
        ("table", "cutover_manifests"),
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
    }
