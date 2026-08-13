from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
}

EXCLUDED_PARTS = {
    ".agentfactory",
    ".git",
    ".idea",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

EXCLUDED_SOURCE_PREFIXES = (
    "docs/DYNAMIC_AGENT_RUNTIME_REFACTOR.md",
    "docs/refactor/",
    "scripts/audit_dynamic_runtime_refactor.py",
    "src-tauri/resources/python/",
)

LEGACY_PATTERNS = {
    "agent_package": re.compile(r"AgentPackage|agent_package|agent-package", re.IGNORECASE),
    "manufacturing": re.compile(r"create_agent|create-agent|manufactur", re.IGNORECASE),
    "evolution": re.compile(r"evolve_agent|evolution|agent_evolve", re.IGNORECASE),
    "system_package": re.compile(r"SystemPackage|system_package|factory_chat", re.IGNORECASE),
    "package_assembly": re.compile(r"assembly_spec|runtime_contract|package_state", re.IGNORECASE),
    "package_identity": re.compile(r"package_id|package_session|owner_package", re.IGNORECASE),
    "package_collaboration": re.compile(
        r"agent_search|agent_list|agent_manufacture|agent_team|assignee_package",
        re.IGNORECASE,
    ),
    "package_scheduler": re.compile(r"package_seed|scheduler_seed", re.IGNORECASE),
    "package_process_bridge": re.compile(
        r"agent_runtime_bridge|NativeAgentRuntime|AGENTFACTORY_(?:BRIDGE|AGENT_RUNTIME|SYSTEM_PACKAGE|PACKAGE_ROOT)",
        re.IGNORECASE,
    ),
    "legacy_client_state": re.compile(
        r"LAST_AGENT_SESSION|ACTIVE_GROUP_STORAGE_KEY|agent_package_selected|selectedAgentPackage|activeChatPackageId",
        re.IGNORECASE,
    ),
    "agent_hub_package_config": re.compile(
        r"AGENTHUB_MAX_PACKAGE_BYTES|AGENTHUB_MAX_ARCHIVE_FILES|AGENTHUB_MAX_UNCOMPRESSED_BYTES|"
        r"AGENTHUB_MAX_COMPRESSION_RATIO|AGENTHUB_VALIDATION_POLL_SECONDS",
        re.IGNORECASE,
    ),
    "legacy_tool_compatibility": re.compile(
        r"LEGACY_BUILTIN_TOOL_ALIASES|tool_permissions\.v0|permission_scope[^\n]{0,80}package",
        re.IGNORECASE,
    ),
    "legacy_storage_topology": re.compile(
        r"create_agent_workspaces|delete_agent_package_session|attachment_uploads|"
        r"\.agentfactory[/\\]tool_outputs",
        re.IGNORECASE,
    ),
    "dynamic_legacy_entrypoint": re.compile(
        r"entrypoint[^\n]{0,160}(?:create_agent|evolution|package)|"
        r"(?:create_agent|evolution|package)[^\n]{0,160}entrypoint",
        re.IGNORECASE,
    ),
    "duplicate_capability_authority": re.compile(
        r"extension_bindings\.json|factory_extensions|default_extension_registry_root|"
        r"SkillHubGateway|MCPGateway|enabled_skills\.json|mcp_servers\.json",
        re.IGNORECASE,
    ),
    "implicit_runtime_policy": re.compile(
        r"DEFAULT_TOOL_APPROVAL_TRUST_STORE|EXECUTOR_FALLBACK_REASON_FIELD|"
        r"AGENTFACTORY_EMBEDDING_(?:PROVIDER|MODEL|API_KEY|BASE_URL|DIMS|TIMEOUT_SECONDS)|"
        r"source=[\"']env_legacy[\"']",
        re.IGNORECASE,
    ),
    "unowned_runtime_state": re.compile(
        r"[\"']unscoped[\"']|[\"']default-agent[\"']|[\"']unknown-agent[\"']|"
        r"DEFAULT_TOOL_APPROVAL_TRUST_STORE|PROCESS_MANAGER\s*=|TRANSACTION_STORE\s*=|STAGED_WRITE_STORE\s*=",
        re.IGNORECASE,
    ),
    "legacy_prompt_assembly": re.compile(
        r"prompt_binding|runtime_prompt_fragments_from_state|generated Agent runtime model|package/domain tools",
        re.IGNORECASE,
    ),
    "client_owned_runtime_policy": re.compile(
        r"runtimeMainModelProfileId|runtimeRequestTimeoutSeconds|runtimeMaxRetries|"
        r"maxParallelSubAgents|DEFAULT_RUNTIME_(?:REQUEST_TIMEOUT_SECONDS|MAX_RETRIES|MAX_PARALLEL_SUB_AGENTS)",
        re.IGNORECASE,
    ),
    "scheduler_environment_policy": re.compile(
        r"AGENTFACTORY_SCHEDULER_(?:ENABLED|STORE_BACKEND|STORE_PATH|TIMEZONE|DEFAULT_TIMEOUT_SECONDS|"
        r"UNATTENDED_POLICY|FAILURE_AUTO_PAUSE_ENABLED|MAX_CONSECUTIVE_FAILURES)|"
        r"SchedulerOwnerType\s*=\s*Literal\[[^\n]*(?:factory|agent)|"
        r"SchedulerTargetType\s*=\s*Literal\[[^\n]*(?:script_run|tool_call)",
        re.IGNORECASE,
    ),
    "attachment_multi_projection": re.compile(
        r"AttachmentUploadStore|AttachmentImportPolicy|import_runtime_attachments|"
        r"session_attachments_from_state|fallback_attachments",
        re.IGNORECASE,
    ),
    "temporal_context_multi_authority": re.compile(
        r"current_date_system_context|ToolDescriptionContext|AGENTFACTORY_SCHEDULER_TIMEZONE|"
        r"timezone:\s*str\s*=\s*[\"']Asia/Shanghai[\"']",
        re.IGNORECASE,
    ),
    "retry_without_attempt_identity": re.compile(
        r"max_retries|retry_policy|fallback_attempt|attempts\s*>\s*state\.execution\.max_retries",
        re.IGNORECASE,
    ),
    "tip_side_runtime": re.compile(
        r"TipService|TipStore|TIP_SYSTEM_PROMPT|/api/tips|TipPanel\.vue|tip_system",
        re.IGNORECASE,
    ),
    "message_history_repair_authority": re.compile(
        r"repair_incomplete_message_checkpoint|finalize_drained_runtime_checkpoint|"
        r"close_incomplete_tool_call_history|incomplete_tool_call_ids|drained_checkpoint",
        re.IGNORECASE,
    ),
    "stream_normalization_authority": re.compile(
        r"EventNormalizerStreamState|pending_tool_call_ids_by_name|reasoning_delta|"
        r"_tool_calls_from_response|streaming_tool_calls",
        re.IGNORECASE,
    ),
    "fragmented_admission_control": re.compile(
        r"max_parallel_sub_agents|ModelSlotCoordinator|CapacityCoordinator|"
        r"_session_running_requests|serialization_key_strategy|dependency_build_slot",
        re.IGNORECASE,
    ),
    "auxiliary_model_bypass": re.compile(
        r"structured_model\.invoke|model\.invoke\(self\._messages\(tip\)\)|"
        r"get_compression_model|get_embedding_model\(|ImageGenerationService",
        re.IGNORECASE,
    ),
    "blocking_control_plane_work": re.compile(
        r"subprocess\.run\(|time\.sleep\(|urllib\.request|urlopen\(|build_opener\(",
        re.IGNORECASE,
    ),
    "legacy_model_operation_roles": re.compile(
        r"ModelPoolRole\s*=\s*Literal\[[^\n]*(?:main|task|compression)|"
        r"ModelBindingRole\s*=\s*Literal\[[^\n]*(?:main|task|compression)|"
        r"resolve_available_chat_model\(|mainmodel",
        re.IGNORECASE,
    ),
    "force_kill_sidecar_lifecycle": re.compile(
        r"restart_backend|shutdown_backend|process\.kill\(\)|PythonSidecar::spawn",
        re.IGNORECASE,
    ),
    "workspace_path_authority": re.compile(
        r"filesystem_allowed_roots|WorkspacePathAdapter|workspace_mounts|"
        r"resolve\(strict=False\)|destination\.symlink_to",
        re.IGNORECASE,
    ),
    "unstructured_runtime_errors": re.compile(
        r"后台任务执行失败|internal server error|emit_run_failed|"
        r"RuntimeErrorEnvelope|user_message_key",
        re.IGNORECASE,
    ),
    "volatile_command_ingress": re.compile(
        r"_background_commands|_session_dispatch_queues|factory-runtime-command|"
        r"command\.request_id\s+or\s+f?[\"'][^\"']*id\(command\)",
        re.IGNORECASE,
    ),
    "split_state_event_commit": re.compile(
        r"RuntimeEventJournal|prepare_for_delivery\(|record_model_usage_frontend_event\(|"
        r"event_history\.append\(",
        re.IGNORECASE,
    ),
    "partial_startup_reconciliation": re.compile(
        r"recover_workspace_transactions\(|migrate_legacy_background_tasks\(|"
        r"@app\.on_event\([\"']startup[\"']\)|background_task_scheduler\.start\(",
        re.IGNORECASE,
    ),
    "application_generation_authority": re.compile(
        r"runtime_bridge\s*=\s*RuntimeBridge\(|agent_group_service\s*=\s*AgentGroupService\(|"
        r"background_task_scheduler\s*:\s*BackgroundTaskService\s*\|\s*None|PythonSidecar::spawn",
        re.IGNORECASE,
    ),
    "capability_instruction_trust": re.compile(
        r"_enabled_skills_prompt_fragment|prompt_fragments\.append\(|"
        r"description=tool\.description\s+or\s+f?[\"']MCP tool|SKILL\.md body to the model",
        re.IGNORECASE,
    ),
    "capability_revocation_boundary": re.compile(
        r"MCP server is disabled|Skill is disabled|active_revision|credential_revision|revocation",
        re.IGNORECASE,
    ),
    "split_delivery_commit": re.compile(
        r"create_workspace_commit\(|artifact_refs|deliver_result|background_task_result",
        re.IGNORECASE,
    ),
    "unified_storage_lifecycle_gap": re.compile(
        r"RuntimeEventJournal|runtime_events|tool_outputs|dependency_pool|"
        r"\.jsonl|trace_root|journal_root",
        re.IGNORECASE,
    ),
    "distributed_deletion_topology": re.compile(
        r"cleanup_expired\(|delete_session|delete_agent_package_session|"
        r"rmtree\(|unlink\(missing_ok=True\)",
        re.IGNORECASE,
    ),
    "revision_bound_runtime_cache": re.compile(
        r"importlib\.import_module|sys\.modules|MCPRuntimeManager|mcp_client|schema_cache|client_pool",
        re.IGNORECASE,
    ),
    "multi_client_projection": re.compile(
        r"new EventSource\(|processedEventIds|seenEventIds|client_instance_id|BroadcastChannel|navigator\.locks",
        re.IGNORECASE,
    ),
    "cross_store_cutover": re.compile(
        r"migrate_legacy|MigrationRegistry|CutoverManifest|schema_migrations|migration_receipt",
        re.IGNORECASE,
    ),
    "sqlite_auxiliary_state": re.compile(
        r"create virtual table|fts5|(?:-wal|-shm)|pragma\s+(?:wal_checkpoint|user_version)|sqlite_sequence",
        re.IGNORECASE,
    ),
    "legacy_bootstrap_reseeding": re.compile(
        r"DEFAULT_AGENT_PACKAGE_ID|builtin_packages|SystemPackage|factory_chat|initialize_agent_package",
        re.IGNORECASE,
    ),
    "loose_protocol_boundary": re.compile(
        r"payload:\s*dict\[str,\s*Any\]|payload\.get\([\"'](?:package_id|mode|package_session_id)|"
        r"ConfigDict\(extra=[\"']ignore[\"']\)",
        re.IGNORECASE,
    ),
    "legacy_external_deep_link": re.compile(
        r"redirect|deep.?link|notification_target|route\.query|"
        r"package_id[^\n]{0,120}(?:path|route|url|redirect)",
        re.IGNORECASE,
    ),
    "provider_continuation_state": re.compile(
        r"additional_kwargs|response_metadata|reasoning_details|reasoning_content|"
        r"previous_response_id|thought_signature|provider_continuation",
        re.IGNORECASE,
    ),
    "capability_dependency_closure": re.compile(
        r"CapabilityResourceRef|dependency_digest|dependency_environment_id|"
        r"tool_aliases|MCPDiscoveredTool|resolved_version",
        re.IGNORECASE,
    ),
    "runtime_projection_audience": re.compile(
        r"tool_call_output_delta|tool_observation_available|TraceFactRecord|"
        r"runtime_log_store|observation_summary|payload\.get\([\"']arguments",
        re.IGNORECASE,
    ),
    "managed_process_tree": re.compile(
        r"process\.terminate\(\)|process\.kill\(\)|terminate_tree|kill_tree|"
        r"start_new_session|CREATE_NEW_PROCESS_GROUP|taskkill",
        re.IGNORECASE,
    ),
    "schema_downgrade_fence": re.compile(
        r"schema_migrations|SCHEMA_VERSION|build_revision|minimum_writer|"
        r"unsupported[^\n]{0,80}schema",
        re.IGNORECASE,
    ),
    "suspend_resume_reconciliation": re.compile(
        r"misfire_grace_time|coalesce\s*=\s*True|time\.monotonic\(|"
        r"lease_expires_at|scheduled_at|next_run_time",
        re.IGNORECASE,
    ),
    "detached_background_execution": re.compile(
        r"asyncio\.create_task\(|asyncio\.ensure_future\(|daemon\s*=\s*True|"
        r"ThreadPoolExecutor\(|ProcessPoolExecutor\(",
        re.IGNORECASE,
    ),
    "process_global_service_singleton": re.compile(
        r"_FACTORY_(?:MEMORY|CONTEXT)_(?:RUNTIME|WORKER)|_DEFAULT_ATTACHMENT_UPLOAD_STORE|"
        r"_DEFAULT_BROWSER_RUNTIME|_MCP_CLIENT_CACHE|DEFAULT_TOOL_APPROVAL_TRUST_STORE|"
        r"TRANSACTION_STORE\s*=|STAGED_WRITE_STORE\s*=",
        re.IGNORECASE,
    ),
    "runtime_configuration_provenance": re.compile(
        r"load_agentfactory_dotenv\(|os\.environ\.copy\(\)|dict\(os\.environ\)|"
        r"env\s*=\s*\{\*\*os\.environ|AGENTFACTORY_(?:RUNTIME_EVENT_PIPELINE_CAPACITY|"
        r"ATTACHMENT_MAX_|TOOL_OUTPUT_MAX_MODEL_CHARS|MEMORY_WRITE_INTERVAL_TURNS)",
        re.IGNORECASE,
    ),
    "stream_backpressure_authority": re.compile(
        r"asyncio\.Queue\([^\n]*maxsize|QueueFull|critical_overflow|stale_subscribers|"
        r"runtime event pipeline capacity|StreamingResponse\(",
        re.IGNORECASE,
    ),
    "distributed_application_data_roots": re.compile(
        r"app_local_data_dir\(|factory_artifact_root\(|\.agent_runtime|"
        r"Path\.home\(\)\s*/\s*[\"']\.skillhub[\"']|"
        r"AGENTFACTORY_(?:PROJECT_ROOT|EXTENSION_REGISTRY_ROOT|RESOURCE_STORE_PATH|"
        r"MODEL_POOL_STORE_PATH|MEMORY_STORE_PATH|SCHEDULER_STORE_PATH)",
        re.IGNORECASE,
    ),
    "outbound_network_policy_bypass": re.compile(
        r"httpx\.(?:get|post|request|Client|AsyncClient)|urlopen\(|build_opener\(|"
        r"ProxyHandler\(|_NO_PROXY_OPENER|follow_redirects\s*=\s*True",
        re.IGNORECASE,
    ),
    "resource_master_key_lifecycle": re.compile(
        r"RESOURCE_MASTER_KEY_ENV|AGENTFACTORY_RESOURCE_MASTER_KEY|AESGCM\(|"
        r"master_key|nonce_b64|ciphertext_b64",
        re.IGNORECASE,
    ),
    "ephemeral_staging_residue": re.compile(
        r"TemporaryDirectory\(|NamedTemporaryFile\(|tempfile\.gettempdir\(|"
        r"mkdtemp\(|mkstemp\(|agentfactory-(?:office|skillhub|write)|\.agentfactory-edit-",
        re.IGNORECASE,
    ),
    "host_execution_containment": re.compile(
        r"isolation:\s*str\s*=\s*[\"']native[\"']|TODO:\s*Extract from sandbox|"
        r"subprocess\.Popen\(|shell_runtime\.environment\(os\.environ\)|"
        r"permission_scope\s*=\s*[\"'](?:system|extension|package)[\"']",
        re.IGNORECASE,
    ),
    "untrusted_context_authority": re.compile(
        r"CONTEXT_SUMMARY_KIND|runtime_context_compression|DYNAMIC_EVIDENCE_HEADER|"
        r"runtime_dynamic_evidence|runtime_knowledge_guidance|KNOWLEDGE_GUIDANCE_CONTEXT_KEY",
        re.IGNORECASE,
    ),
    "hierarchical_runtime_budget": re.compile(
        r"token_budget|loop_call_limits|max_parallel_sub_agents|max_tool_calls_per_turn|"
        r"max_consecutive_calls|provider_input_tokens|usage_metadata",
        re.IGNORECASE,
    ),
    "filesystem_operation_toctou": re.compile(
        r"resolve\(strict=False\)|symlink_to\(|is_symlink\(\)|"
        r"(?:resolved|candidate|target)\.(?:open|unlink|replace|rename|rmdir)\(",
        re.IGNORECASE,
    ),
    "loopback_control_plane_identity": re.compile(
        r"allow_origins\s*=\s*\[[\"']\*[\"']\]|allocate_loopback_port\(|"
        r"--host[\"']?\)?\s*\.?arg\([\"']127\.0\.0\.1|is_loopback",
        re.IGNORECASE,
    ),
    "capability_validation_execution_boundary": re.compile(
        r"spec\.loader\.exec_module\(|PythonEntrypointAdapter|ToolCompiler\(|"
        r"loader\.load\(spec\.entrypoint\)|load_risk_evaluator\(",
        re.IGNORECASE,
    ),
    "model_profile_revision_lifecycle": re.compile(
        r"delete_(?:profile|credential)\(|credential_revision|model_profile_revision|"
        r"RuntimeModelHandleRegistry|reset_embedding_model\(",
        re.IGNORECASE,
    ),
    "embedding_index_generation": re.compile(
        r"get_embedding_model_settings\(|embedding_dimensions|settings\.dims|"
        r"requires_embedding|semantic_vector_store",
        re.IGNORECASE,
    ),
    "capability_edit_concurrency": re.compile(
        r"upsert_mcp|upsert_skill|replace_skill_id|update_tool_permissions|"
        r"set_tool_permission",
        re.IGNORECASE,
    ),
    "control_command_starvation": re.compile(
        r"_session_running_requests|_session_dispatch_queues|cannot send a new message while an interrupt is pending|"
        r"ALWAYS_LONG_RUNNING_COMMANDS",
        re.IGNORECASE,
    ),
    "event_replay_subscription_race": re.compile(
        r"event_history|replay_history|after_event_id|subscribers\.add\(",
        re.IGNORECASE,
    ),
    "split_command_acceptance": re.compile(
        r"CommandInbox|command_inbox|receipt_revision|queue_sequence",
        re.IGNORECASE,
    ),
    "implicit_event_semantics": re.compile(
        r"event_persistence\(|endswith\([\"']_delta[\"']\)|after_event_id_for_session|"
        r"select rowid, session_id from runtime_events|delivered_ids:\s*set\[str\]",
        re.IGNORECASE,
    ),
    "approval_binding_gap": re.compile(
        r"ApprovalRequiredPayload|ResumeInterruptPayload|resume_payload\s*=\s*\{|"
        r"interrupt_id[\"']?:\s*payload\.interrupt_id",
        re.IGNORECASE,
    ),
    "credential_revision_secret_duplication": re.compile(
        r"model_credential_revisions|credential\.model_dump_json\(\)|"
        r"api_key\s+text|payload_json[^\n]{0,120}api_key",
        re.IGNORECASE,
    ),
    "hardcoded_capability_classification": re.compile(
        r"IMAGE_INPUT_REQUIRED_TOOL_IDS|ALWAYS_AVAILABLE_SYSTEM_TOOL_IDS|"
        r"READ_ONLY_SYSTEM_TOOL_IDS|tool_id\.startswith\([\"']browser_[\"']\)",
        re.IGNORECASE,
    ),
    "runtime_resource_reflection": re.compile(
        r"build_tool_resource_context|tool_resource_(?:context|summary)|"
        r"def _resource_summary\(",
        re.IGNORECASE,
    ),
    "detached_graph_checkpoint_lifecycle": re.compile(
        r"_run_graph_with_control|graph_detached|daemon\s*=\s*True|"
        r"graph_app\.get_state\(config\)",
        re.IGNORECASE,
    ),
    "delegated_authority_attenuation": re.compile(
        r"BackgroundTaskOwner|parent_package_id|assignee_package_id|visible_context|"
        r"agent_delegate|DelegationGrant",
        re.IGNORECASE,
    ),
    "typed_human_interaction_lifecycle": re.compile(
        r"ask_user|pending_external|clarification_question|waiting_external|"
        r"InteractionRequest|InteractionResponse",
        re.IGNORECASE,
    ),
    "mcp_schema_dialect_projection": re.compile(
        r"normalize_mcp_schema|Draft202012Validator|schema_repairs|"
        r"inputSchema|outputSchema|SchemaDialect",
        re.IGNORECASE,
    ),
    "reproducible_dependency_resolution": re.compile(
        r"pip[\"']?\)?\s*,?\s*[\"']wheel|npm[\"']?\)?\s*,?\s*[\"']install|"
        r"--find-links|request_fingerprint|DependencyRevision",
        re.IGNORECASE,
    ),
    "canonical_digest_encoding": re.compile(
        r"default\s*=\s*str|st_mtime_ns|abs\(hash\(|"
        r"hexdigest\(\)\[:(?:16|24|32)\]|CanonicalEncoding",
        re.IGNORECASE,
    ),
    "runtime_response_language_policy": re.compile(
        r"用中文生成|clarification_question\s*=\s*[\"']请|"
        r"response_language_policy|ui_locale",
        re.IGNORECASE,
    ),
    "desktop_ipc_ambient_authority": re.compile(
        r"shell:allow-open|updater:default|process:allow-restart|notification:default|"
        r"tauri_plugin_(?:shell|updater|process|notification)",
        re.IGNORECASE,
    ),
    "runtime_prompt_graph_revision": re.compile(
        r"FileSystemPromptProvider|prompt_provider\.load\(|main_agent\.md|"
        r"build_react_graph\(|build_plan_and_execute_graph\(|fixed_graphs",
        re.IGNORECASE,
    ),
    "shared_mutable_record_concurrency": re.compile(
        r"MemoryStoreWriter|upsert_source\(|upsert_job\(|"
        r"on conflict\((?:source_id|job_id)\) do update|set_job_enabled\(",
        re.IGNORECASE,
    ),
    "builtin_capability_source_lifecycle": re.compile(
        r"get_builtin_tool_specs\(|IMPLEMENTED_BUILTIN_TOOL_IDS|BuiltinToolProvider|"
        r"default_tools_contract\(|builtin_tools_enabled",
        re.IGNORECASE,
    ),
    "principal_identity_migration": re.compile(
        r"local_memory_user_id\(|memory_identity\.v1|"
        r"factory_artifact_path\([\"']memory[\"'],\s*[\"']identity\.json[\"']\)",
        re.IGNORECASE,
    ),
    "workspace_event_reconciliation": re.compile(
        r"refreshWorkspace\(|refresh_workspace|workspace_revision|"
        r"WorkspaceExplorer\.vue|st_mtime_ns",
        re.IGNORECASE,
    ),
    "frontend_stream_projection_pressure": re.compile(
        r"reasoningContent\s*\+=|state\.transcript\.push\(|"
        r"assistantMessages\.push\(|applyRuntimeEvent|requestAnimationFrame\(",
        re.IGNORECASE,
    ),
    "attempt_scoped_assistant_drafts": re.compile(
        r"model_content_delta|model_reasoning_delta|assistant_stream_started|"
        r"streamingMessage|activeAssistantMessage|partial_output",
        re.IGNORECASE,
    ),
    "workspace_content_delivery_authority": re.compile(
        r"/raw|native-path|native_path|Content-Disposition[^\n]{0,80}inline|"
        r"workspaceApi\.rawUrl|workspaceApi\.nativePath",
        re.IGNORECASE,
    ),
    "browser_view_control_authority": re.compile(
        r"default_browser_runtime\(|dispatch_view_input|close_browser_page|"
        r"subscribe_view\(|browser_view_id|page_id",
        re.IGNORECASE,
    ),
    "skillhub_bootstrap_trust": re.compile(
        r"DEFAULT_SKILLHUB_(?:INSTALL|KIT|SELF_UPDATE)_URL|"
        r"_download_install_script|self_update_manifest_url|latest\.tar\.gz",
        re.IGNORECASE,
    ),
    "capability_content_tree_portability": re.compile(
        r"SkillContentRef|logical_path|PurePosixPath|copytree\([^\n]{0,160}symlinks\s*=\s*False|"
        r"content_manifest",
        re.IGNORECASE,
    ),
    "scheduler_workspace_lifecycle": re.compile(
        r"WorkspaceStore\(\)\.delete|archived\s*=|workspace_id|"
        r"scheduler_jobs_owner|factory_scheduler_owner_id",
        re.IGNORECASE,
    ),
    "browser_network_session_boundary": re.compile(
        r"host_validation_ttl_seconds|_safe_web_socket_url|accept_downloads\s*=\s*True|"
        r"browser\.new_context\(|download\.save_as\(",
        re.IGNORECASE,
    ),
    "imported_content_tree_transaction": re.compile(
        r"webkitRelativePath|webkitGetAsEntry|_safe_upload_relative_path|"
        r"filesFromDataTransferItems|KnowledgeUploadFile|import_runtime_attachments",
        re.IGNORECASE,
    ),
    "managed_interprocess_lock_lifecycle": re.compile(
        r"exclusive_file_lock|fcntl\.flock|msvcrt\.locking|\.pool\.lock|\.cache_locks",
        re.IGNORECASE,
    ),
    "application_update_recovery_transaction": re.compile(
        r"download_and_install|update\.download\(|update\.install\(|"
        r"shutdown_backend|TAURI_SIGNING_PRIVATE_KEY|updater:default",
        re.IGNORECASE,
    ),
    "release_composition_provenance": re.compile(
        r"softprops/action-gh-release|cargo tauri build|npm install|npm ci|"
        r"package_macos\.sh|package_windows\.ps1|bundle_python\.py|ReleaseCompositionManifest",
        re.IGNORECASE,
    ),
    "mcp_auth_session_lifecycle": re.compile(
        r"MCPResourceBinding|target:\s*Literal\[[^\n]*(?:environment|header)|"
        r"headers:\s*dict\[str,\s*str\]|env:\s*dict\[str,\s*str\]|"
        r"MCPAuthSession|refresh_token|PKCE",
        re.IGNORECASE,
    ),
    "mcp_protocol_capability_boundary": re.compile(
        r"ClientSession|session\.initialize\(|list_tools\(|call_tool\(|"
        r"(?:sampling|elicitation|roots|resources|prompts|notifications)/(?:list|create|changed)|"
        r"MCPProtocolProfile",
        re.IGNORECASE,
    ),
    "model_invocation_usage_ledger": re.compile(
        r"record_model_usage_frontend_event|model_usage_events|usage_update|"
        r"cache_(?:read|write)_tokens|estimated_cost|ModelInvocationReceipt",
        re.IGNORECASE,
    ),
    "derived_context_revision_lifecycle": re.compile(
        r"CONTEXT_SUMMARY_KIND|context-summary-|MemoryExtractionDecision|"
        r"memory_extraction_completed|compression_report|DerivedContextRevision",
        re.IGNORECASE,
    ),
    "scheduler_calendar_semantics_revision": re.compile(
        r"CronTrigger|IntervalTrigger|DateTrigger|ZoneInfo\(|coalesce\s*=|"
        r"misfire_grace_time|ScheduleSemanticsRevision|tzdb",
        re.IGNORECASE,
    ),
    "provider_remote_object_lifecycle": re.compile(
        r"file_id:\s*str|files?\.create\(|files?\.delete\(|b64_json|"
        r"data:image/|ProviderObjectLease",
        re.IGNORECASE,
    ),
    "diagnostic_export_snapshot_boundary": re.compile(
        r"diagnostic_ref|log_tail|runtime_event_journal|trace.*(?:download|export)|"
        r"support.?bundle|RecoveryBundleManifest|DiagnosticBundleManifest",
        re.IGNORECASE,
    ),
    "archive_special_entry_boundary": re.compile(
        r"tarfile\.open|zipfile\.ZipFile|extractall\(|unpack_archive|hardlink_to\(|"
        r"(?:xattr|alternate.data.stream|CapabilityContentManifest)",
        re.IGNORECASE,
    ),
    "object_level_authorization_boundary": re.compile(
        r"authenticated_principal|principal_id|workspace_id|session_id|resource_id|"
        r"conversation is owned by a different principal|owner.*(?:check|match)|ACL",
        re.IGNORECASE,
    ),
    "sensitive_error_projection_boundary": re.compile(
        r"HTTPException\([^\n]*detail\s*=\s*(?:str\(exc\)|f[\"'][^\"']*\{exc\})|"
        r"ValidationError|traceback\.format|exc_info=|RuntimeErrorEnvelope",
        re.IGNORECASE,
    ),
    "mutable_collection_snapshot_pagination": re.compile(
        r"(?:limit|page_size)\s*[:=][^\n]{0,80}(?:offset|cursor)|"
        r"offset\s*\+=|order by[^\n]{0,120}limit|snapshot_cursor|page_token",
        re.IGNORECASE,
    ),
    "application_installation_channel_identity": re.compile(
        r"factory_artifact_root\(|AGENTFACTORY_PROJECT_ROOT|app_local_data_dir\(|"
        r"com\.fastagentfactory\.app|productName|ApplicationDataRootManifest",
        re.IGNORECASE,
    ),
    "bounded_request_ingress": re.compile(
        r"UploadFile|request\.body\(|request\.json\(|multipart|Content-Length|"
        r"max_(?:file|archive|uncompressed|request|body)_bytes|replay_limit",
        re.IGNORECASE,
    ),
    "runtime_readiness_contract": re.compile(
        r"@(?:router|app)\.get\([\"']/health|runtime_service_active|"
        r"sqlite_lifecycle_available|runtime_ready|status[\"']?\s*:\s*[\"']ok[\"']",
        re.IGNORECASE,
    ),
    "notification_delivery_authority": re.compile(
        r"seenTaskNotifications|nativeNotificationTargets|publishTaskNotification|"
        r"stableNotificationId|sendNotification\(|NotificationDeliveryReceipt",
        re.IGNORECASE,
    ),
    "security_audit_ledger_boundary": re.compile(
        r"audit_log|record_audit\(|diagnostic_ref|TraceRecorder|"
        r"SecurityAuditRecord|authorization_decision_id",
        re.IGNORECASE,
    ),
    "dependency_sbom_and_advisory_lifecycle": re.compile(
        r"pip[\"']?\)?\s*,?\s*[\"']wheel|npm[\"']?\)?\s*,?\s*[\"']install|"
        r"license_id|DependencyRevision|SBOM|CycloneDX|SPDX|advisory|CVE",
        re.IGNORECASE,
    ),
    "restore_import_quarantine_boundary": re.compile(
        r"sqlite3\.connect\([^\n]{0,120}(?:backup|restore)|source\.backup\(|"
        r"RecoveryBundleManifest|UserDataImportManifest|restore.*database|import.*backup",
        re.IGNORECASE,
    ),
    "bulk_destructive_operation_lifecycle": re.compile(
        r"conversations/clear|clear_conversations|ConversationStorageService|"
        r"for\s+session\s+in[^\n]{0,120}sessions|BulkDeletePlan|bulk.*delete",
        re.IGNORECASE,
    ),
    "capability_tool_alias_identity": re.compile(
        r"_tool_surface\(|model_tool_ids|tool_aliases|"
        r"tool_ids[^\n]{0,160}(?:selected|capability|alias)|RuntimeScopedToolRegistry",
        re.IGNORECASE,
    ),
    "capability_search_receipt_boundary": re.compile(
        r"CapabilitySearchMatch|CapabilitySearchIndex|index_revision_id|"
        r"CapabilitySearchReceipt|requirements_digest|candidate.*digest",
        re.IGNORECASE,
    ),
    "capability_surface_budget_boundary": re.compile(
        r"bind_tools\(|model_tools\(|model_prompt_fragments|"
        r"CapabilitySurfaceBudget|CapabilitySurfaceReceipt|max_(?:tools|schema|prompt).*",
        re.IGNORECASE,
    ),
    "provider_tool_schema_projection_boundary": re.compile(
        r"compile_json_schema|model_json_schema\(|bind_tools\(|"
        r"ProviderToolSchemaProjector|ProviderToolSurfaceReceipt|provider.*schema.*projection",
        re.IGNORECASE,
    ),
    "tool_call_identity_mapping_boundary": re.compile(
        r"call_\{index\}_\{name\}|call\.get\([\"']id[\"']\)\s+or\s+(?:tool_id|RUNTIME_PLAN_TOOL_ID)|"
        r"provider_tool_call_id|ToolCallIdentityMap|tool_call_id",
        re.IGNORECASE,
    ),
    "untrusted_document_processing_boundary": re.compile(
        r"UploadFile|content_type|accepted_file_extensions|parse_file\(|"
        r"DocumentConverter|partition\(filename|soffice|DocumentProcessingJob|ContentInspectionManifest",
        re.IGNORECASE,
    ),
}

LEGACY_COMPONENTS = (
    {
        "component": "manufacturing_runtime",
        "classification": "delete",
        "execution_unit": 1,
        "paths": ["agent_factory/create_agent", "web_frontend/backend/routes/create_agent.py"],
    },
    {
        "component": "evolution_runtime",
        "classification": "delete",
        "execution_unit": 1,
        "paths": ["agent_factory/evolution"],
    },
    {
        "component": "agent_package_distribution",
        "classification": "delete",
        "execution_unit": 1,
        "paths": ["agent_factory/package_distribution.py", "web_frontend/backend/routes/agent_hub.py"],
    },
    {
        "component": "agent_hub_package_registry",
        "classification": "delete_package_features_preserve_app_releases",
        "execution_unit": 1,
        "paths": ["services/agent_hub/agent_hub/package_inspector.py", "services/agent_hub/agent_hub/registry.py"],
    },
    {
        "component": "package_management_surface",
        "classification": "delete",
        "execution_unit": 2,
        "paths": [
            "web_frontend/backend/routes/agent_packages.py",
            "web_frontend/frontend/src/api/agentPackages.ts",
            "web_frontend/frontend/src/views/AgentPackageDetailView.vue",
        ],
    },
    {
        "component": "package_contract_and_assembly",
        "classification": "delete_at_main_runtime_cutover",
        "execution_unit": 5,
        "paths": ["agent_factory/runtime_contracts", "agent_factory/assembly"],
    },
    {
        "component": "package_runtime",
        "classification": "delete_at_main_runtime_cutover",
        "execution_unit": 5,
        "paths": ["agent_factory/package_runtime", "agent_factory/factory_graph/frontend_bridge/agent_package_runtime.py"],
    },
    {
        "component": "system_chat_package",
        "classification": "delete_at_main_runtime_cutover",
        "execution_unit": 5,
        "paths": ["SystemPackage/factory_chat"],
    },
    {
        "component": "package_process_bridge",
        "classification": "extract_process_control_then_delete",
        "execution_unit": 6,
        "paths": ["agent_factory/agent_runtime_bridge", "agent_factory/native_runtime/launcher.py"],
    },
    {
        "component": "package_agent_registry",
        "classification": "delete_replace_with_capability_index",
        "execution_unit": 1,
        "paths": ["agent_factory/agent_registry"],
    },
    {
        "component": "package_agent_group",
        "classification": "replace_with_temporary_runtime_projection",
        "execution_unit": 7,
        "paths": ["agent_factory/agent_group_system", "web_frontend/backend/routes/agent_group.py"],
    },
    {
        "component": "package_scoped_state",
        "classification": "migrate_then_delete",
        "execution_unit": 8,
        "paths": [
            "agent_factory/memory_system",
            "agent_factory/knowledge_system",
            "agent_factory/scheduler_system",
            "agent_factory/resource_system",
            "agent_factory/trace_system",
        ],
    },
    {
        "component": "legacy_protocol_projection_and_navigation",
        "classification": "replace",
        "execution_unit": 3,
        "paths": [
            "agent_factory/factory_graph/frontend_bridge/protocol_catalog.json",
            "web_frontend/frontend/src/router/index.ts",
            "web_frontend/frontend/src/services/taskNotifications.ts",
            "web_frontend/backend/runtime_event_journal.py",
        ],
    },
    {
        "component": "package_attribution_and_telemetry",
        "classification": "migrate_then_delete",
        "execution_unit": 8,
        "paths": [
            "agent_factory/artifact_system",
            "agent_factory/model_pool/usage.py",
            "agent_factory/trace_system",
            "agent_factory/tip_system",
        ],
    },
    {
        "component": "generated_package_artifacts",
        "classification": "delete_at_release_cutover",
        "execution_unit": 11,
        "paths": [
            "src-tauri/gen",
            "src-tauri/resources",
            "web_frontend/frontend/dist",
            "services/agent_hub/agent_hub/agent_package_schemas.json",
        ],
    },
    {
        "component": "legacy_client_persistence",
        "classification": "invalidate_and_replace",
        "execution_unit": 11,
        "paths": [
            "web_frontend/frontend/src/stores/agent.ts",
            "web_frontend/frontend/src/stores/agentGroup.ts",
            "web_frontend/frontend/src/services/taskNotifications.ts",
            "web_frontend/frontend/src/stores/runtimePreferences.ts",
        ],
    },
    {
        "component": "agent_hub_package_configuration_and_backups",
        "classification": "delete_package_settings_migrate_database_preserve_app_releases",
        "execution_unit": 11,
        "paths": [
            "services/agent_hub/agent_hub/config.py",
            "services/agent_hub/deploy/fastagenthub.env.example",
            "services/agent_hub/agent_hub/backup.py",
        ],
    },
    {
        "component": "legacy_model_and_embedding_attribution",
        "classification": "migrate_roles_and_rebuild_indexes",
        "execution_unit": 8,
        "paths": [
            "agent_factory/model_pool/usage.py",
            "agent_factory/models/embedding_model.py",
            "agent_factory/memory_system/store_index.py",
            "agent_factory/knowledge_system/store_index.py",
        ],
    },
    {
        "component": "execution_residue_and_leases",
        "classification": "drain_then_replace_ownership",
        "execution_unit": 7,
        "paths": [
            "agent_factory/tooling/builtins/process/manager.py",
            "agent_factory/tooling/builtins/filesystem/workspace_transaction.py",
            "agent_factory/tooling/builtins/filesystem/staged_write.py",
            "agent_factory/scheduler_system/worker.py",
            "agent_factory/collaboration_system/execution_registry.py",
        ],
    },
    {
        "component": "legacy_permission_defaults_and_tool_aliases",
        "classification": "migrate_stable_revisions_then_delete_compatibility",
        "execution_unit": 10,
        "paths": [
            "SystemPackage/extensions/tool_permissions.json",
            "agent_factory/tooling/builtins/aliases.py",
            "agent_factory/tooling/approval_policy.py",
        ],
    },
    {
        "component": "legacy_conversation_storage_cleanup",
        "classification": "replace_with_conversation_store_retention_service",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/conversation_storage.py",
            "web_frontend/backend/attachment_upload_store.py",
            "agent_factory/tooling/output_store.py",
        ],
    },
    {
        "component": "dynamic_entrypoints_and_lazy_exports",
        "classification": "rewrite_then_scan_serialized_references",
        "execution_unit": 12,
        "paths": [
            "agent_factory/tooling/entrypoint.py",
            "agent_factory/tooling/entrypoints",
            "agent_factory/tooling/providers/__init__.py",
            "agent_factory/tooling/__init__.py",
        ],
    },
    {
        "component": "interactive_tool_lifecycle",
        "classification": "attach_to_runtime_instance_cancellation_tree",
        "execution_unit": 7,
        "paths": [
            "agent_factory/tooling/builtins/browser/runtime.py",
            "web_frontend/backend/routes/browser_views.py",
            "agent_factory/models/image_generation",
        ],
    },
    {
        "component": "duplicate_capability_registries_and_gateways",
        "classification": "converge_to_single_capability_control_plane",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/extension_registry.py",
            "agent_factory/tooling/factory_extensions.py",
            "agent_factory/tooling/skills",
            "agent_factory/tooling/skillhub",
            "agent_factory/skillhub_gateway",
            "agent_factory/mcp_gateway",
        ],
    },
    {
        "component": "implicit_runtime_configuration_and_policy",
        "classification": "replace_with_explicit_authoritative_configuration",
        "execution_unit": 6,
        "paths": [
            "agent_factory/models/embedding_model.py",
            "agent_factory/tooling/approval_policy.py",
            "agent_factory/tooling/gateway.py",
            "agent_factory/tooling/executor_fallback.py",
            "agent_factory/scheduler_system/config.py",
        ],
    },
    {
        "component": "unowned_process_global_runtime_state",
        "classification": "scope_to_runtime_instance_or_managed_service",
        "execution_unit": 7,
        "paths": [
            "agent_factory/tooling/gateway.py",
            "agent_factory/tooling/output_store.py",
            "agent_factory/tooling/builtins/process/manager.py",
            "agent_factory/tooling/builtins/filesystem/workspace_transaction.py",
            "agent_factory/tooling/builtins/filesystem/staged_write.py",
        ],
    },
    {
        "component": "legacy_prompt_binding_and_executor_fallback",
        "classification": "replace_with_direct_main_prompt_and_capability_policy",
        "execution_unit": 4,
        "paths": [
            "agent_factory/runtime_kernel/model_inputs.py",
            "agent_factory/runtime_kernel/prompt_fragments.py",
            "agent_factory/tooling/executor_fallback.py",
        ],
    },
    {
        "component": "client_owned_runtime_policy",
        "classification": "replace_with_versioned_server_policy_and_request_snapshot",
        "execution_unit": 3,
        "paths": [
            "web_frontend/frontend/src/stores/runtimePreferences.ts",
            "web_frontend/frontend/src/api/commands.ts",
            "agent_factory/package_runtime/request_lifecycle.py",
            "agent_factory/collaboration_system/persistence/settings_repository.py",
        ],
    },
    {
        "component": "attachment_ingestion_and_context_projection",
        "classification": "converge_to_owned_attachment_record_and_immutable_turn_reference",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/attachment_upload_store.py",
            "agent_factory/runtime_attachments.py",
            "agent_factory/runtime_kernel/session.py",
            "agent_factory/runtime_protocol/chat_parts.py",
            "agent_factory/office_document_parsers.py",
        ],
    },
    {
        "component": "temporal_context_and_scheduler_clock",
        "classification": "replace_with_single_clock_and_user_timezone_authority",
        "execution_unit": 8,
        "paths": [
            "agent_factory/models/temporal_context.py",
            "agent_factory/tooling/description_context.py",
            "agent_factory/scheduler_system/config.py",
            "agent_factory/scheduler_system/triggers.py",
        ],
    },
    {
        "component": "model_retry_attempt_and_usage_accounting",
        "classification": "add_attempt_identity_and_side_effect_idempotency_boundary",
        "execution_unit": 7,
        "paths": [
            "agent_factory/runtime_kernel/patterns/wrapper_pipeline.py",
            "agent_factory/runtime_kernel/model_operations/service.py",
            "agent_factory/model_pool/usage.py",
            "web_frontend/frontend/src/stores/runtimePreferences.ts",
        ],
    },
    {
        "component": "context_compaction_and_queued_input_authority",
        "classification": "converge_to_turn_ledger_and_single_context_policy",
        "execution_unit": 8,
        "paths": [
            "agent_factory/context_system",
            "agent_factory/runtime_kernel/model_inputs.py",
            "agent_factory/runtime_kernel/session.py",
            "web_frontend/frontend/src/stores/contextReferences.ts",
        ],
    },
    {
        "component": "event_delivery_and_derived_status_projection",
        "classification": "sequence_events_and_rebuild_views_from_authoritative_stores",
        "execution_unit": 3,
        "paths": [
            "web_frontend/backend/runtime_event_journal.py",
            "web_frontend/frontend/src/api/events.ts",
            "web_frontend/frontend/src/stores/runtimeSync.ts",
            "agent_factory/tip_system",
            "agent_factory/contracts/background_tasks.py",
        ],
    },
    {
        "component": "execution_environment_and_capability_supply_chain",
        "classification": "explicit_environment_projection_and_verified_capability_revision",
        "execution_unit": 6,
        "paths": [
            "agent_factory/environment_system",
            "agent_factory/native_runtime/dependency_pool.py",
            "agent_factory/tooling/builtins/process",
            "agent_factory/tooling/skillhub",
            "agent_factory/mcp_gateway",
        ],
    },
    {
        "component": "desktop_sidecar_transport_authority",
        "classification": "preserve_single_discovered_backend_endpoint_for_all_transports",
        "execution_unit": 5,
        "paths": [
            "src-tauri/src/main.rs",
            "web_frontend/frontend/src/api/backendUrl.ts",
            "web_frontend/frontend/src/api/events.ts",
            "web_frontend/frontend/vite.config.ts",
        ],
    },
    {
        "component": "sqlite_schema_and_settings_authority",
        "classification": "centralize_migration_registry_and_transaction_ownership",
        "execution_unit": 8,
        "paths": [
            "agent_factory/sqlite_runtime.py",
            "agent_factory/collaboration_system/persistence/schema.py",
            "agent_factory/scheduler_system/store.py",
            "agent_factory/model_pool/usage.py",
            "agent_factory/tip_system/store.py",
        ],
    },
    {
        "component": "tip_side_conversation_runtime",
        "classification": "delete_runtime_preserve_selection_as_context_reference",
        "execution_unit": 8,
        "paths": [
            "agent_factory/tip_system",
            "web_frontend/backend/routes/tips.py",
            "web_frontend/frontend/src/components/chat/TipPanel.vue",
        ],
    },
    {
        "component": "provider_message_and_tool_call_closure",
        "classification": "replace_with_canonical_turn_ledger_and_single_provider_projection",
        "execution_unit": 4,
        "paths": [
            "agent_factory/package_runtime/drained_checkpoint.py",
            "agent_factory/context_system/compression.py",
            "agent_factory/tooling/langgraph_node.py",
            "agent_factory/runtime_protocol/messages.py",
        ],
    },
    {
        "component": "model_stream_normalization",
        "classification": "converge_to_single_model_stream_normalizer",
        "execution_unit": 4,
        "paths": [
            "agent_factory/runtime_kernel/model_operations/service.py",
            "agent_factory/factory_graph/frontend_bridge/event_normalizer.py",
            "agent_factory/models/adapters",
            "web_frontend/frontend/src/stores/runtimeSync.ts",
        ],
    },
    {
        "component": "fragmented_runtime_admission_control",
        "classification": "replace_with_single_admission_controller_and_resource_queues",
        "execution_unit": 7,
        "paths": [
            "web_frontend/backend/runtime_bridge.py",
            "agent_factory/collaboration_system/capacity.py",
            "agent_factory/collaboration_system/task_service.py",
            "agent_factory/tooling/mcp_runtime.py",
        ],
    },
    {
        "component": "auxiliary_model_execution_bypass",
        "classification": "route_all_model_operations_through_model_execution_coordinator",
        "execution_unit": 7,
        "paths": [
            "agent_factory/scheduler_system/feedback.py",
            "agent_factory/tip_system/service.py",
            "agent_factory/memory_system/extraction.py",
            "agent_factory/tooling/output_compressor.py",
            "agent_factory/models/image_generation",
            "agent_factory/models/embedding_model.py",
        ],
    },
    {
        "component": "blocking_control_plane_work",
        "classification": "move_to_managed_cancellable_workers",
        "execution_unit": 7,
        "paths": [
            "web_frontend/backend/event_api_server.py",
            "agent_factory/environment_system",
            "agent_factory/document_processing.py",
            "agent_factory/tooling/skillhub",
            "agent_factory/mcp_gateway",
        ],
    },
    {
        "component": "model_operation_role_fallback",
        "classification": "replace_roles_with_explicit_operation_requirements_and_snapshots",
        "execution_unit": 6,
        "paths": [
            "agent_factory/model_pool/schema.py",
            "agent_factory/model_pool/resolver.py",
            "agent_factory/models/chat_model.py",
        ],
    },
    {
        "component": "local_principal_identity",
        "classification": "add_stable_principal_owner_without_multitenant_compatibility",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_protocol/contracts.py",
            "agent_factory/memory_system",
            "agent_factory/resource_system",
            "agent_factory/tooling/approval_policy.py",
        ],
    },
    {
        "component": "desktop_sidecar_shutdown_and_update_lifecycle",
        "classification": "replace_force_kill_with_quiesce_drain_flush_ack_protocol",
        "execution_unit": 12,
        "paths": [
            "src-tauri/src/main.rs",
            "src-tauri/src/python_sidecar.rs",
            "web_frontend/backend/event_api_server.py",
        ],
    },
    {
        "component": "frontend_backend_protocol_version_handshake",
        "classification": "add_protocol_schema_build_revision_handshake",
        "execution_unit": 3,
        "paths": [
            "agent_factory/factory_graph/frontend_bridge/protocol_catalog.json",
            "web_frontend/backend/routes/runtime.py",
            "web_frontend/frontend/src/api/events.ts",
            "src-tauri/src/main.rs",
        ],
    },
    {
        "component": "workspace_canonical_path_identity",
        "classification": "converge_mount_authorization_and_watchers_to_workspace_path_adapter",
        "execution_unit": 8,
        "paths": [
            "agent_factory/workspace_system.py",
            "agent_factory/workspace_mounts.py",
            "agent_factory/workspace_directories.py",
            "agent_factory/tooling/builtins/filesystem/common.py",
        ],
    },
    {
        "component": "runtime_error_and_terminal_taxonomy",
        "classification": "replace_free_form_exceptions_with_runtime_error_envelope",
        "execution_unit": 3,
        "paths": [
            "web_frontend/backend/runtime_bridge.py",
            "agent_factory/contracts/background_tasks.py",
            "agent_factory/scheduler_system",
            "web_frontend/frontend/src/i18n/index.ts",
        ],
    },
    {
        "component": "durable_command_ingress_and_idempotency",
        "classification": "replace_process_local_queue_with_command_inbox",
        "execution_unit": 5,
        "paths": [
            "web_frontend/backend/runtime_bridge.py",
            "web_frontend/backend/routes/utils.py",
            "web_frontend/frontend/src/composables/commands/transport.ts",
        ],
    },
    {
        "component": "transactional_state_event_outbox",
        "classification": "replace_split_persistence_with_transactional_outbox",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/runtime_event_journal.py",
            "web_frontend/backend/runtime_bridge.py",
            "agent_factory/model_pool/usage.py",
        ],
    },
    {
        "component": "runtime_startup_reconciliation",
        "classification": "replace_partial_recovery_with_authoritative_reconciler",
        "execution_unit": 5,
        "paths": [
            "web_frontend/backend/event_api_server.py",
            "web_frontend/backend/runtime_bridge.py",
            "agent_factory/collaboration_system/task_service.py",
        ],
    },
    {
        "component": "application_generation_and_single_writer_ownership",
        "classification": "add_leased_application_generation_and_fencing",
        "execution_unit": 5,
        "paths": [
            "web_frontend/backend/event_api_server.py",
            "src-tauri/src/python_sidecar.rs",
            "agent_factory/scheduler_system/worker.py",
        ],
    },
    {
        "component": "capability_content_trust_boundary",
        "classification": "add_trust_level_and_bounded_model_projection",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/providers/skill.py",
            "agent_factory/tooling/providers/mcp.py",
            "agent_factory/runtime_kernel/model_inputs.py",
        ],
    },
    {
        "component": "capability_emergency_revocation",
        "classification": "add_revocation_registry_and_active_runtime_fence",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/providers/skill.py",
            "agent_factory/tooling/providers/mcp.py",
            "agent_factory/resource_system",
        ],
    },
    {
        "component": "cross_store_delivery_commit",
        "classification": "converge_file_artifact_result_and_event_finalization",
        "execution_unit": 7,
        "paths": [
            "agent_factory/agent_group_system/workspace_transaction.py",
            "agent_factory/collaboration_system/result_delivery.py",
            "agent_factory/artifact_system/store.py",
        ],
    },
    {
        "component": "storage_retention_and_quota_authority",
        "classification": "replace_per_module_cleanup_with_storage_lifecycle_service",
        "execution_unit": 11,
        "paths": [
            "web_frontend/backend/runtime_event_journal.py",
            "agent_factory/tooling/output_store.py",
            "agent_factory/trace_system",
            "agent_factory/environment_system",
        ],
    },
    {
        "component": "referential_delete_plan_and_barrier",
        "classification": "replace_distributed_cleanup_with_owned_delete_plan",
        "execution_unit": 11,
        "paths": [
            "web_frontend/backend/conversation_storage.py",
            "web_frontend/backend/attachment_upload_store.py",
            "agent_factory/knowledge_system",
            "agent_factory/memory_system",
            "agent_factory/resource_system",
        ],
    },
    {
        "component": "revision_scoped_runtime_loaders_and_clients",
        "classification": "bind_live_modules_clients_and_processes_to_capability_revision_leases",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/entrypoint.py",
            "agent_factory/tooling/compiler.py",
            "agent_factory/tooling/mcp_runtime.py",
            "agent_factory/tooling/providers",
        ],
    },
    {
        "component": "multi_client_command_and_projection_ownership",
        "classification": "add_client_instance_identity_and_server_side_command_cas",
        "execution_unit": 3,
        "paths": [
            "web_frontend/frontend/src/api/events.ts",
            "web_frontend/frontend/src/composables/commands/transport.ts",
            "web_frontend/frontend/src/stores/runtime.ts",
            "web_frontend/backend/runtime_bridge.py",
        ],
    },
    {
        "component": "cross_store_atomic_cutover",
        "classification": "gate_new_composition_root_on_durable_cutover_manifest",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/event_api_server.py",
            "agent_factory/collaboration_system/persistence/legacy_migration.py",
            "agent_factory/resource_system/migration.py",
            "agent_factory/memory_system/migration.py",
        ],
    },
    {
        "component": "sqlite_virtual_tables_wal_and_connection_generation",
        "classification": "enumerate_checkpoint_close_rebuild_and_allowlist_all_sqlite_objects",
        "execution_unit": 11,
        "paths": [
            "agent_factory/sqlite_runtime.py",
            "agent_factory/knowledge_system/catalog.py",
            "agent_factory/scheduler_system/store.py",
            "agent_factory/collaboration_system/persistence/schema.py",
        ],
    },
    {
        "component": "clean_install_bootstrap_and_default_assets",
        "classification": "replace_legacy_package_seeding_with_empty_dynamic_runtime_bootstrap",
        "execution_unit": 5,
        "paths": [
            "agent_factory/builtin_packages.py",
            "SystemPackage",
            "web_frontend/frontend/src/showcase",
            "src-tauri/resources",
        ],
    },
    {
        "component": "strict_protocol_and_retired_field_rejection",
        "classification": "reject_unknown_or_retired_fields_outside_offline_migration",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_protocol",
            "agent_factory/factory_graph/frontend_bridge/protocol.py",
            "web_frontend/backend/routes",
            "web_frontend/frontend/src/types/protocol.ts",
        ],
    },
    {
        "component": "python_install_and_bytecode_residue",
        "classification": "clean_rebuild_and_verify_from_fresh_installed_artifact",
        "execution_unit": 11,
        "paths": [
            "pyproject.toml",
            "scripts/bundle_python.py",
            "src-tauri/resources/python",
            "agent_factory",
        ],
    },
    {
        "component": "external_deep_link_and_redirect_scope",
        "classification": "converge_to_allowlisted_deep_link_resolver",
        "execution_unit": 3,
        "paths": [
            "web_frontend/frontend/src/router/index.ts",
            "web_frontend/frontend/src/services/taskNotifications.ts",
            "services/agent_hub/agent_hub/api.py",
            "src-tauri/src/main.rs",
        ],
    },
    {
        "component": "provider_continuation_and_opaque_state",
        "classification": "isolate_provider_continuation_from_canonical_conversation",
        "execution_unit": 4,
        "paths": [
            "agent_factory/runtime_kernel/state/messages.py",
            "agent_factory/models",
            "agent_factory/runtime_kernel/model_operations/service.py",
            "agent_factory/runtime_protocol/model_stream.py",
        ],
    },
    {
        "component": "capability_transitive_dependency_closure",
        "classification": "freeze_and_digest_complete_capability_dependency_graph",
        "execution_unit": 6,
        "paths": [
            "agent_factory/runtime_protocol/capabilities.py",
            "agent_factory/runtime_protocol/contracts.py",
            "agent_factory/tooling/providers",
            "agent_factory/environment_system",
        ],
    },
    {
        "component": "runtime_data_projection_audience",
        "classification": "project_once_by_explicit_audience_and_sensitivity_policy",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_kernel/observability/tool_events.py",
            "agent_factory/trace_system/recorder.py",
            "agent_factory/tooling/output_store.py",
            "web_frontend/backend/runtime_event_journal.py",
        ],
    },
    {
        "component": "cross_platform_process_tree_ownership",
        "classification": "bind_complete_process_trees_to_runtime_cancellation_and_reaping",
        "execution_unit": 7,
        "paths": [
            "agent_factory/observed_process.py",
            "agent_factory/tooling/builtins/process",
            "agent_factory/tooling/mcp_runtime.py",
            "agent_factory/environment_system",
        ],
    },
    {
        "component": "database_downgrade_writer_fence",
        "classification": "reject_older_writers_and_require_explicit_restore_protocol",
        "execution_unit": 11,
        "paths": [
            "agent_factory/dynamic_runtime/database.py",
            "agent_factory/runtime_protocol/versioning.py",
            "agent_factory/runtime_protocol/lifecycle.py",
            "src-tauri/src/main.rs",
        ],
    },
    {
        "component": "host_suspend_resume_runtime_reconciliation",
        "classification": "reconcile_deadlines_leases_and_scheduler_runs_after_clock_discontinuity",
        "execution_unit": 8,
        "paths": [
            "agent_factory/scheduler_system/worker.py",
            "agent_factory/scheduler_system/store.py",
            "agent_factory/observed_process.py",
            "web_frontend/backend/event_api_server.py",
        ],
    },
    {
        "component": "structured_background_execution_ownership",
        "classification": "bind_every_task_thread_and_event_pump_to_application_and_runtime_lifecycle",
        "execution_unit": 7,
        "paths": [
            "web_frontend/backend/runtime_bridge.py",
            "web_frontend/backend/routes/browser_views.py",
            "agent_factory/collaboration_system/task_service.py",
            "agent_factory/knowledge_system/runtime.py",
            "agent_factory/tooling/mcp_runtime.py",
        ],
    },
    {
        "component": "composition_root_owned_service_instances",
        "classification": "remove_late_process_singletons_and_scope_services_by_generation_revision_and_owner",
        "execution_unit": 5,
        "paths": [
            "agent_factory/memory_system/factory.py",
            "agent_factory/context_system/factory.py",
            "web_frontend/backend/attachment_upload_store.py",
            "agent_factory/tooling/builtins/browser/runtime.py",
            "agent_factory/tooling/mcp_runtime.py",
        ],
    },
    {
        "component": "runtime_configuration_snapshot_and_provenance",
        "classification": "resolve_configuration_once_then_freeze_redacted_provenance_per_application_generation",
        "execution_unit": 5,
        "paths": [
            "agent_factory/env.py",
            "web_frontend/backend/event_api_server.py",
            "web_frontend/backend/runtime_bridge.py",
            "agent_factory/native_runtime/launcher.py",
            "agent_factory/tooling/mcp_runtime.py",
        ],
    },
    {
        "component": "bounded_stream_and_projection_backpressure",
        "classification": "unify_flow_control_gap_recovery_and_slow_consumer_policy",
        "execution_unit": 3,
        "paths": [
            "web_frontend/backend/runtime_event_pipeline.py",
            "web_frontend/backend/runtime_bridge.py",
            "web_frontend/backend/routes/runtime.py",
            "web_frontend/backend/routes/browser_views.py",
            "web_frontend/frontend/src/api/events.ts",
        ],
    },
    {
        "component": "application_data_root_discovery_and_ownership",
        "classification": "discover_all_managed_and_external_roots_then_migrate_by_ownership_manifest",
        "execution_unit": 8,
        "paths": [
            "src-tauri/src/python_sidecar.rs",
            "agent_factory/paths.py",
            "agent_factory/runtime_contracts",
            "agent_factory/tooling/extension_registry.py",
            "agent_factory/tooling/skillhub/service.py",
        ],
    },
    {
        "component": "outbound_network_and_remote_content_policy",
        "classification": "converge_all_egress_and_remote_ingestion_to_managed_network_service",
        "execution_unit": 6,
        "paths": [
            "agent_factory/document_processing.py",
            "agent_factory/knowledge_system/loaders.py",
            "agent_factory/models/image_generation",
            "agent_factory/tooling/skillhub/service.py",
            "agent_factory/mcp_gateway/client.py",
            "agent_factory/skillhub_gateway/client.py",
        ],
    },
    {
        "component": "resource_master_key_and_credential_vault_lifecycle",
        "classification": "replace_unversioned_environment_master_key_with_managed_versioned_credential_vault",
        "execution_unit": 6,
        "paths": [
            "agent_factory/resource_system/store.py",
            "agent_factory/resource_system/migration.py",
            "agent_factory/native_runtime/launcher.py",
            "agent_factory/tooling/mcp_runtime.py",
        ],
    },
    {
        "component": "ephemeral_staging_and_crash_residue",
        "classification": "register_staging_ownership_then_reconcile_and_securely_expire_crash_residue",
        "execution_unit": 7,
        "paths": [
            "agent_factory/document_processing.py",
            "agent_factory/environment_system/pool.py",
            "agent_factory/tooling/skillhub/service.py",
            "agent_factory/tooling/builtins/filesystem/workspace_transaction.py",
            "agent_factory/tooling/builtins/filesystem/staged_write.py",
            "agent_factory/tooling/extension_registry.py",
        ],
    },
    {
        "component": "host_tool_execution_containment",
        "classification": "replace_approval_only_execution_with_explicit_cross_platform_containment_profiles",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/builtins/process/manager.py",
            "agent_factory/tooling/gateway.py",
            "agent_factory/native_runtime/launcher.py",
            "agent_factory/environment_system",
            "agent_factory/tooling/mcp_runtime.py",
        ],
    },
    {
        "component": "model_context_instruction_data_boundary",
        "classification": "project_untrusted_evidence_as_provenanced_data_without_system_authority_escalation",
        "execution_unit": 4,
        "paths": [
            "agent_factory/runtime_kernel/model_inputs.py",
            "agent_factory/context_system/compression.py",
            "agent_factory/runtime_kernel/wrappers/system_knowledge.py",
            "agent_factory/memory_system/injection.py",
            "agent_factory/runtime_attachments.py",
        ],
    },
    {
        "component": "hierarchical_runtime_budget_enforcement",
        "classification": "enforce_principal_session_turn_runtime_and_operation_budgets_at_admission_boundaries",
        "execution_unit": 7,
        "paths": [
            "agent_factory/context_system/token_counter.py",
            "agent_factory/runtime_kernel/model_operations/service.py",
            "agent_factory/runtime_kernel/tool_governance.py",
            "agent_factory/collaboration_system",
            "agent_factory/model_pool/usage.py",
        ],
    },
    {
        "component": "filesystem_authorization_toctou_boundary",
        "classification": "bind_authorization_and_mutation_to_revalidated_file_identity_and_mount_revision",
        "execution_unit": 8,
        "paths": [
            "agent_factory/tooling/builtins/filesystem/common.py",
            "agent_factory/tooling/builtins/filesystem/workspace_transaction.py",
            "agent_factory/workspace_mounts.py",
            "agent_factory/runtime_attachments.py",
            "agent_factory/knowledge_system/tools.py",
        ],
    },
    {
        "component": "desktop_loopback_control_plane_identity",
        "classification": "bind_preopened_loopback_transport_to_authenticated_application_generation",
        "execution_unit": 5,
        "paths": [
            "src-tauri/src/python_sidecar.rs",
            "web_frontend/backend/event_api_server.py",
            "web_frontend/backend/routes",
            "web_frontend/frontend/src/api/backendUrl.ts",
            "web_frontend/frontend/src/api/events.ts",
        ],
    },
    {
        "component": "capability_validation_execution_isolation",
        "classification": "separate_static_validation_from_isolated_executable_probe",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/compiler.py",
            "agent_factory/tooling/entrypoints/python_entrypoint.py",
            "agent_factory/tooling/extension_registry.py",
            "web_frontend/backend/routes/extensions.py",
        ],
    },
    {
        "component": "model_profile_and_credential_revision_lifecycle",
        "classification": "tombstone_and_lease_model_revisions_instead_of_destructive_active_lookup",
        "execution_unit": 6,
        "paths": [
            "agent_factory/model_pool/store.py",
            "agent_factory/dynamic_runtime/model_service.py",
            "agent_factory/runtime_kernel/model_operations/service.py",
            "web_frontend/backend/routes/model_pool.py",
        ],
    },
    {
        "component": "embedding_index_generation_cutover",
        "classification": "rebuild_and_atomically_activate_dimensioned_embedding_index_generations",
        "execution_unit": 8,
        "paths": [
            "agent_factory/models/embedding_model.py",
            "agent_factory/knowledge_system/store_index.py",
            "agent_factory/memory_system/store_index.py",
            "agent_factory/knowledge_system/runtime.py",
        ],
    },
    {
        "component": "capability_draft_concurrency_and_lost_update_fence",
        "classification": "require_revision_cas_for_draft_edit_publish_and_delete",
        "execution_unit": 6,
        "paths": [
            "web_frontend/backend/routes/extensions.py",
            "agent_factory/tooling/extension_registry.py",
            "web_frontend/frontend/src/views/ExtensionsView.vue",
        ],
    },
    {
        "component": "control_command_admission_lane",
        "classification": "separate_non_blocking_cancel_admission_from_long_running_work_lanes",
        "execution_unit": 7,
        "paths": [
            "web_frontend/backend/runtime_bridge.py",
            "agent_factory/dynamic_runtime/repositories.py",
            "agent_factory/dynamic_runtime/supervisor.py",
        ],
    },
    {
        "component": "durable_event_replay_subscription_boundary",
        "classification": "subscribe_before_replay_and_recover_from_authoritative_event_cursor",
        "execution_unit": 9,
        "paths": [
            "web_frontend/backend/routes/runtime.py",
            "web_frontend/backend/dynamic_runtime_api.py",
            "agent_factory/dynamic_runtime/event_stream.py",
        ],
    },
    {
        "component": "atomic_command_acceptance_boundary",
        "classification": "atomically_persist_envelope_queued_receipt_and_outbox_before_dispatch",
        "execution_unit": 5,
        "paths": [
            "web_frontend/backend/runtime_bridge.py",
            "agent_factory/dynamic_runtime/repositories.py",
            "web_frontend/backend/dynamic_runtime_api.py",
        ],
    },
    {
        "component": "explicit_event_persistence_and_session_cursor",
        "classification": "replace_name_and_rowid_conventions_with_typed_persistence_and_session_sequence",
        "execution_unit": 3,
        "paths": [
            "agent_factory/event_persistence.py",
            "agent_factory/dynamic_runtime/repositories.py",
            "web_frontend/backend/dynamic_runtime_api.py",
        ],
    },
    {
        "component": "approval_grant_operation_binding",
        "classification": "bind_approval_to_exact_tool_revision_arguments_scope_policy_and_expiry",
        "execution_unit": 7,
        "paths": [
            "agent_factory/runtime_protocol/events.py",
            "agent_factory/runtime_protocol/commands.py",
            "agent_factory/dynamic_runtime/resume.py",
        ],
    },
    {
        "component": "credential_revision_secret_storage",
        "classification": "move_secret_material_to_vault_and_revision_only_opaque_resource_references",
        "execution_unit": 6,
        "paths": [
            "agent_factory/model_pool/store.py",
            "agent_factory/dynamic_runtime/model_service.py",
            "agent_factory/resource_system/store.py",
        ],
    },
    {
        "component": "capability_metadata_authority",
        "classification": "replace_tool_name_sets_and_prefixes_with_revisioned_capability_metadata",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/model_visibility.py",
            "agent_factory/tooling/builtins/registry.py",
            "agent_factory/tooling/providers/builtin.py",
        ],
    },
    {
        "component": "runtime_resource_projection_boundary",
        "classification": "replace_recursive_resource_reflection_with_allowlisted_typed_redacted_projection",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/resource_context.py",
            "agent_factory/tooling/gateway.py",
            "agent_factory/runtime_protocol/observations.py",
        ],
    },
    {
        "component": "detached_graph_worker_and_checkpoint_lifecycle",
        "classification": "own_detached_workers_and_checkpoint_namespaces_by_generation_attempt_and_recovery_receipt",
        "execution_unit": 7,
        "paths": [
            "agent_factory/dynamic_runtime/runtime_service.py",
            "agent_factory/dynamic_runtime/application.py",
            "agent_factory/runtime_kernel/persistence/checkpointer.py",
        ],
    },
    {
        "component": "temporary_runtime_delegated_authority",
        "classification": "replace_package_or_session_ownership_with_attenuated_revisioned_delegation_grants",
        "execution_unit": 7,
        "paths": [
            "agent_factory/contracts/background_tasks.py",
            "agent_factory/collaboration_system/task_client.py",
            "agent_factory/dynamic_runtime/main_turn.py",
            "agent_factory/runtime_protocol/contracts.py",
        ],
    },
    {
        "component": "typed_human_interaction_requests",
        "classification": "separate_clarification_external_input_and_approval_into_typed_single_projection_records",
        "execution_unit": 3,
        "paths": [
            "agent_factory/collaboration_system/interactions.py",
            "agent_factory/dynamic_runtime/runtime_service.py",
            "agent_factory/runtime_protocol/commands.py",
            "web_frontend/frontend/src/stores/runtime",
        ],
    },
    {
        "component": "mcp_schema_dialect_and_provider_projection",
        "classification": "preserve_source_schema_and_publish_validated_dialect_aware_provider_projections",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/mcp_schema.py",
            "agent_factory/tooling/schema_compiler.py",
            "agent_factory/tooling/providers/mcp.py",
            "agent_factory/models/adapters",
        ],
    },
    {
        "component": "dependency_resolution_lock_and_supply_chain",
        "classification": "publish_platform_specific_resolved_graphs_and_hash_verified_artifacts_before_runtime",
        "execution_unit": 6,
        "paths": [
            "agent_factory/environment_system/python_requirements.py",
            "agent_factory/environment_system/service.py",
            "agent_factory/native_runtime/dependency_pool.py",
            "agent_factory/environment_system/pool.py",
        ],
    },
    {
        "component": "canonical_encoding_and_digest_identity",
        "classification": "replace_bespoke_serialization_and_truncated_hashes_with_versioned_domain_separated_canonical_encoding",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_protocol",
            "agent_factory/contracts/background_tasks.py",
            "agent_factory/runtime_kernel/model_inputs.py",
            "agent_factory/factory_graph/frontend_bridge/agent_package_runtime.py",
        ],
    },
    {
        "component": "runtime_response_language_authority",
        "classification": "separate_ui_locale_from_snapshot_response_language_and_remove_module_hardcoded_language",
        "execution_unit": 4,
        "paths": [
            "agent_factory/collaboration_system/progress_summary.py",
            "agent_factory/runtime_kernel/adapters/model.py",
            "agent_factory/dynamic_runtime/prompts",
            "web_frontend/frontend/src/stores/ui.ts",
        ],
    },
    {
        "component": "desktop_ipc_least_privilege_boundary",
        "classification": "replace_webview_ambient_plugin_authority_with_scoped_audited_desktop_commands",
        "execution_unit": 11,
        "paths": [
            "src-tauri/capabilities/main.json",
            "src-tauri/src/main.rs",
            "web_frontend/frontend/src/services/taskNotifications.ts",
            "web_frontend/frontend/src/api/backendUrl.ts",
        ],
    },
    {
        "component": "runtime_prompt_graph_revision_lifecycle",
        "classification": "pin_prompt_graph_and_build_revisions_in_runtime_request_and_recovery",
        "execution_unit": 4,
        "paths": [
            "agent_factory/dynamic_runtime/launch_context.py",
            "agent_factory/dynamic_runtime/prompts",
            "agent_factory/runtime_kernel/fixed_graphs.py",
            "agent_factory/runtime_protocol/contracts.py",
        ],
    },
    {
        "component": "shared_mutable_domain_record_concurrency",
        "classification": "replace_last_write_wins_updates_with_revisioned_commands_and_cas",
        "execution_unit": 8,
        "paths": [
            "agent_factory/memory_system/writer.py",
            "agent_factory/knowledge_system/catalog.py",
            "agent_factory/knowledge_system/runtime.py",
            "agent_factory/scheduler_system/store.py",
            "agent_factory/scheduler_system/runtime.py",
        ],
    },
    {
        "component": "builtin_capability_source_and_upgrade_lifecycle",
        "classification": "publish_builtin_sources_through_the_same_revisioned_capability_store",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/builtins/registry.py",
            "agent_factory/tooling/providers/builtin.py",
            "agent_factory/tooling/registry.py",
            "agent_factory/runtime_contracts/builtins",
        ],
    },
    {
        "component": "principal_identity_alias_and_migration",
        "classification": "map_legacy_installation_identity_once_to_the_canonical_principal",
        "execution_unit": 8,
        "paths": [
            "agent_factory/memory_system/scopes.py",
            "agent_factory/runtime_protocol/contracts.py",
            "agent_factory/dynamic_runtime/repositories.py",
            "web_frontend/backend/dynamic_runtime_api.py",
        ],
    },
    {
        "component": "workspace_event_overflow_and_snapshot_reconciliation",
        "classification": "replace_refresh_side_effects_with_revisioned_watch_events_and_authoritative_rescan",
        "execution_unit": 8,
        "paths": [
            "web_frontend/frontend/src/components/workspace/WorkspaceExplorer.vue",
            "web_frontend/frontend/src/composables/commands/useWorkspaceCommands.ts",
            "agent_factory/workspace_system.py",
            "agent_factory/workspace_mounts.py",
        ],
    },
    {
        "component": "frontend_stream_reducer_and_render_backpressure",
        "classification": "project_events_through_one_idempotent_reducer_and_frame_batched_render_model",
        "execution_unit": 9,
        "paths": [
            "web_frontend/frontend/src/stores/runtime/messageMutations.ts",
            "web_frontend/frontend/src/stores/runtime/modelMutations.ts",
            "web_frontend/frontend/src/stores/runtime/sessionSnapshots.ts",
            "web_frontend/frontend/src/components/chat/MessageItem.vue",
        ],
    },
    {
        "component": "attempt_scoped_assistant_draft_lifecycle",
        "classification": "separate_tentative_stream_drafts_from_committed_conversation_messages_and_reconcile_terminal_partial_output",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_kernel/model_operations/service.py",
            "agent_factory/dynamic_runtime/runtime_service.py",
            "web_frontend/backend/runtime_event_pipeline.py",
            "web_frontend/frontend/src/stores/runtime/modelMutations.ts",
        ],
    },
    {
        "component": "workspace_content_gateway_and_native_path_boundary",
        "classification": "replace_raw_paths_and_same_origin_inline_files_with_revisioned_authorized_content_references",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/routes/workspace.py",
            "web_frontend/frontend/src/api/workspace.ts",
            "web_frontend/frontend/src/api/desktopWorkspaceFiles.ts",
            "web_frontend/frontend/src/components/workspace/FilePreview.vue",
        ],
    },
    {
        "component": "browser_view_control_lease_and_acl",
        "classification": "bind_browser_view_and_input_channels_to_principal_runtime_generation_and_expiring_control_leases",
        "execution_unit": 7,
        "paths": [
            "web_frontend/backend/routes/browser_views.py",
            "agent_factory/tooling/builtins/browser/runtime.py",
            "agent_factory/tooling/builtins/browser/tools.py",
            "web_frontend/frontend/src/components/browser/BrowserPanel.vue",
        ],
    },
    {
        "component": "skillhub_bootstrap_and_update_trust_chain",
        "classification": "replace_unsigned_remote_installers_and_metadata_selected_updates_with_signed_pinned_source_revisions",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/skillhub/service.py",
            "agent_factory/tooling/skillhub",
            "agent_factory/skillhub_gateway",
        ],
    },
    {
        "component": "cross_platform_capability_content_manifest",
        "classification": "publish_portable_content_trees_with_canonical_paths_collision_checks_entry_types_and_digests",
        "execution_unit": 6,
        "paths": [
            "agent_factory/dynamic_runtime/capability_definitions.py",
            "agent_factory/dynamic_runtime/capability_kind_adapters.py",
            "agent_factory/tooling/extension_registry.py",
            "agent_factory/tooling/skills",
        ],
    },
    {
        "component": "scheduler_workspace_lifecycle_coupling",
        "classification": "atomically_pause_or_tombstone_workspace_jobs_when_workspace_authority_changes",
        "execution_unit": 8,
        "paths": [
            "agent_factory/scheduler_system/store.py",
            "agent_factory/scheduler_system/runtime.py",
            "agent_factory/workspace_system.py",
            "web_frontend/backend/routes/workspace.py",
        ],
    },
    {
        "component": "browser_network_and_session_data_boundary",
        "classification": "enforce_per_request_browser_egress_and_bind_context_data_to_runtime_leases",
        "execution_unit": 7,
        "paths": [
            "agent_factory/tooling/builtins/browser/runtime.py",
            "agent_factory/tooling/builtins/browser/tools.py",
            "web_frontend/backend/routes/browser_views.py",
        ],
    },
    {
        "component": "imported_content_tree_and_ingestion_transaction",
        "classification": "canonicalize_validate_digest_and_atomically_publish_user_import_manifests",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/routes/knowledge.py",
            "web_frontend/frontend/src/components/knowledge/KnowledgeSourceFormModal.vue",
            "agent_factory/runtime_attachments.py",
            "web_frontend/backend/attachment_upload_store.py",
        ],
    },
    {
        "component": "managed_interprocess_lock_and_deadlock_boundary",
        "classification": "replace_unbounded_file_locks_with_owned_deadline_aware_cancellable_lock_leases",
        "execution_unit": 7,
        "paths": [
            "agent_factory/file_lock.py",
            "agent_factory/environment_system/pool.py",
            "agent_factory/memory_system/migration.py",
            "agent_factory/tooling/skills/skill_tool_protocol.py",
        ],
    },
    {
        "component": "application_update_and_recovery_bundle_transaction",
        "classification": "bind_binary_install_quiesce_data_cutover_and_verified_restore_to_one_durable_update_transaction",
        "execution_unit": 11,
        "paths": [
            "web_frontend/frontend/src/stores/appUpdate.ts",
            "src-tauri/src/main.rs",
            "src-tauri/src/python_sidecar.rs",
            "scripts/package_macos.sh",
            "scripts/package_windows.ps1",
        ],
    },
    {
        "component": "release_composition_manifest_and_build_provenance",
        "classification": "publish_one_verified_manifest_for_source_locks_protocols_builtin_revisions_and_platform_artifacts",
        "execution_unit": 12,
        "paths": [
            "pyproject.toml",
            "web_frontend/frontend/package-lock.json",
            "src-tauri/Cargo.lock",
            "scripts/package_macos.sh",
            "scripts/package_windows.ps1",
            ".github/workflows/build.yml",
        ],
    },
    {
        "component": "mcp_authentication_session_and_token_lifecycle",
        "classification": "separate_static_server_revision_from_principal_scoped_vault_backed_auth_leases",
        "execution_unit": 6,
        "paths": [
            "agent_factory/dynamic_runtime/capability_definitions.py",
            "agent_factory/tooling/providers/mcp.py",
            "agent_factory/tooling/mcp_runtime.py",
            "agent_factory/resource_system/store.py",
        ],
    },
    {
        "component": "mcp_protocol_capability_negotiation_and_reverse_requests",
        "classification": "negotiate_and_pin_supported_mcp_features_then_policy_gate_every_server_initiated_operation",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/mcp_runtime.py",
            "agent_factory/mcp_gateway",
            "agent_factory/dynamic_runtime/capability_definitions.py",
            "agent_factory/runtime_protocol/capabilities.py",
        ],
    },
    {
        "component": "model_invocation_usage_and_cost_ledger",
        "classification": "record_backend_authoritative_attempt_scoped_usage_receipts_with_reservation_and_idempotent_finalization",
        "execution_unit": 7,
        "paths": [
            "agent_factory/runtime_kernel/model_operations/service.py",
            "agent_factory/runtime_protocol/model_stream.py",
            "agent_factory/model_pool/usage.py",
            "web_frontend/backend/runtime_bridge.py",
        ],
    },
    {
        "component": "derived_context_summary_and_memory_revision_lifecycle",
        "classification": "version_source_ranges_policies_and_invalidation_for_all_derived_context_materializations",
        "execution_unit": 8,
        "paths": [
            "agent_factory/context_system/compression.py",
            "agent_factory/context_system/runtime.py",
            "agent_factory/memory_system/extraction.py",
            "agent_factory/memory_system/background.py",
        ],
    },
    {
        "component": "scheduler_calendar_and_timezone_semantics_revision",
        "classification": "pin_schedule_tzdb_and_dst_policy_then_derive_stable_occurrence_identities",
        "execution_unit": 8,
        "paths": [
            "agent_factory/scheduler_system/triggers.py",
            "agent_factory/scheduler_system/worker.py",
            "agent_factory/scheduler_system/schema.py",
            "agent_factory/scheduler_system/store.py",
        ],
    },
    {
        "component": "provider_remote_object_and_upload_lease_lifecycle",
        "classification": "bind_remote_provider_files_and_generated_assets_to_owner_revision_retention_and_revocation_receipts",
        "execution_unit": 7,
        "paths": [
            "agent_factory/models/protocol.py",
            "agent_factory/runtime_attachments.py",
            "agent_factory/models/adapters",
            "agent_factory/models/image_generation",
        ],
    },
    {
        "component": "diagnostic_support_and_export_snapshot_boundary",
        "classification": "export_consistent_redacted_owner_scoped_diagnostic_manifests_instead_of_raw_live_files",
        "execution_unit": 11,
        "paths": [
            "agent_factory/trace_system",
            "web_frontend/backend/runtime_event_journal.py",
            "web_frontend/backend/event_loop_watchdog.py",
            "src-tauri/src/python_sidecar.rs",
        ],
    },
    {
        "component": "archive_and_special_filesystem_entry_boundary",
        "classification": "validate_archive_members_and_materialized_entry_types_before_content_manifest_publication",
        "execution_unit": 6,
        "paths": [
            "agent_factory/tooling/skillhub/service.py",
            "agent_factory/environment_system/pool.py",
            "scripts/bundle_python.py",
            "agent_factory/dynamic_runtime/capability_definitions.py",
        ],
    },
    {
        "component": "principal_object_authorization_closure",
        "classification": "authorize_every_read_write_list_stream_and_opaque_reference_against_one_principal_scope",
        "execution_unit": 3,
        "paths": [
            "web_frontend/backend/dynamic_runtime_api.py",
            "web_frontend/backend/routes",
            "agent_factory/dynamic_runtime/repositories.py",
            "services/agent_hub/agent_hub/api.py",
        ],
    },
    {
        "component": "sensitive_error_and_validation_projection",
        "classification": "map_internal_failures_to_typed_redacted_public_errors_and_restricted_diagnostic_references",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_protocol/errors.py",
            "agent_factory/dynamic_runtime/capability_kind_adapters.py",
            "web_frontend/backend/routes",
            "web_frontend/frontend/src/i18n",
        ],
    },
    {
        "component": "mutable_collection_snapshot_and_cursor_contract",
        "classification": "page_mutable_lists_against_stable_high_watermarks_and_revision_bound_cursors",
        "execution_unit": 3,
        "paths": [
            "agent_factory/dynamic_runtime/repositories.py",
            "agent_factory/dynamic_runtime/capability_store.py",
            "web_frontend/backend/routes/background_tasks.py",
            "services/agent_hub/agent_hub/api.py",
        ],
    },
    {
        "component": "installation_channel_and_application_identity",
        "classification": "bind_data_roots_loopback_credentials_updates_and_cleanup_to_explicit_product_channel_identity",
        "execution_unit": 11,
        "paths": [
            "agent_factory/paths.py",
            "src-tauri/tauri.conf.json",
            "src-tauri/src/python_sidecar.rs",
            "scripts/package_macos.sh",
            "scripts/package_windows.ps1",
        ],
    },
    {
        "component": "bounded_authenticated_request_ingress",
        "classification": "enforce_streaming_size_count_depth_rate_and_connection_limits_before_domain_parsing",
        "execution_unit": 3,
        "paths": [
            "web_frontend/backend/event_api_server.py",
            "web_frontend/backend/dynamic_runtime_api.py",
            "web_frontend/backend/attachment_upload_store.py",
            "services/agent_hub/agent_hub/api.py",
        ],
    },
    {
        "component": "application_liveness_readiness_and_degraded_state",
        "classification": "separate_process_liveness_from_generation_bound_dependency_readiness_and_degraded_capability_status",
        "execution_unit": 11,
        "paths": [
            "web_frontend/backend/routes/runtime.py",
            "web_frontend/backend/runtime_bridge.py",
            "web_frontend/backend/event_api_server.py",
            "services/agent_hub/agent_hub/api.py",
        ],
    },
    {
        "component": "durable_notification_intent_and_delivery_receipts",
        "classification": "derive_notifications_from_authoritative_outbox_intents_and_record_idempotent_platform_delivery_receipts",
        "execution_unit": 9,
        "paths": [
            "web_frontend/frontend/src/services/taskNotifications.ts",
            "web_frontend/frontend/src/services/taskNotificationEvents.ts",
            "web_frontend/frontend/src/stores/taskNotificationPreferences.ts",
            "agent_factory/runtime_protocol/events.py",
        ],
    },
    {
        "component": "security_audit_ledger_and_diagnostic_separation",
        "classification": "record_security_relevant_decisions_in_an_append_only_owner_scoped_ledger_separate_from_trace_and_logs",
        "execution_unit": 11,
        "paths": [
            "services/agent_hub/agent_hub/audit.py",
            "services/agent_hub/agent_hub/database.py",
            "agent_factory/trace_system",
            "agent_factory/runtime_protocol/events.py",
        ],
    },
    {
        "component": "dependency_sbom_advisory_and_emergency_revocation",
        "classification": "bind_resolved_dependency_graphs_to_sbom_license_advisory_state_and_runtime_revocation_fences",
        "execution_unit": 6,
        "paths": [
            "agent_factory/environment_system/pool.py",
            "agent_factory/native_runtime/dependency_pool.py",
            "agent_factory/runtime_protocol/capabilities.py",
            "pyproject.toml",
        ],
    },
    {
        "component": "user_data_restore_and_import_quarantine",
        "classification": "inspect_and_migrate_foreign_or_legacy_bundles_in_read_only_quarantine_before_atomic_import",
        "execution_unit": 8,
        "paths": [
            "services/agent_hub/agent_hub/backup.py",
            "agent_factory/dynamic_runtime/migration.py",
            "agent_factory/runtime_protocol/lifecycle.py",
            "web_frontend/backend/routes/storage.py",
        ],
    },
    {
        "component": "bulk_destructive_command_and_progress_lifecycle",
        "classification": "replace_snapshot_then_loop_deletion_with_revisioned_bulk_plans_per_target_receipts_and_resumable_terminal_state",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/conversation_storage.py",
            "web_frontend/backend/routes/storage.py",
            "agent_factory/runtime_protocol/lifecycle.py",
            "agent_factory/dynamic_runtime/lifecycle_repositories.py",
        ],
    },
    {
        "component": "capability_tool_alias_and_snapshot_identity",
        "classification": "freeze_model_alias_semantics_and_remove_capability_id_fallbacks_from_runtime_tool_lookup",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_protocol/contracts.py",
            "agent_factory/dynamic_runtime/capability_resolver.py",
            "agent_factory/runtime_kernel/capability_state.py",
            "agent_factory/runtime_kernel/adapters/tool.py",
        ],
    },
    {
        "component": "capability_search_generation_and_receipt",
        "classification": "bind_each_resolution_to_one_index_generation_store_high_watermark_query_digest_and_ranked_candidate_receipt",
        "execution_unit": 6,
        "paths": [
            "agent_factory/dynamic_runtime/capability_resolver.py",
            "agent_factory/dynamic_runtime/capability_store.py",
            "agent_factory/runtime_protocol/capabilities.py",
            "agent_factory/runtime_protocol/contracts.py",
        ],
    },
    {
        "component": "model_capability_surface_budget",
        "classification": "converge_selected_tools_schemas_skill_prompts_and_dependency_closure_before_snapshot_commit_without_adapter_truncation",
        "execution_unit": 6,
        "paths": [
            "agent_factory/dynamic_runtime/capability_resolver.py",
            "agent_factory/runtime_kernel/model_operations/service.py",
            "agent_factory/runtime_kernel/adapters/model.py",
            "agent_factory/runtime_protocol/contracts.py",
        ],
    },
    {
        "component": "provider_tool_schema_surface_projection",
        "classification": "project_both_tool_and_mcp_canonical_schemas_through_versioned_provider_capabilities_before_model_binding",
        "execution_unit": 6,
        "paths": [
            "agent_factory/dynamic_runtime/capability_adapters.py",
            "agent_factory/tooling/schema_compiler.py",
            "agent_factory/tooling/mcp_schema.py",
            "agent_factory/runtime_kernel/adapters/model.py",
        ],
    },
    {
        "component": "provider_and_internal_tool_call_identity_mapping",
        "classification": "separate_global_internal_tool_call_identity_from_provider_attempt_scoped_call_ids_and_name_index_fallbacks",
        "execution_unit": 3,
        "paths": [
            "agent_factory/runtime_protocol/tool_calls.py",
            "agent_factory/runtime_protocol/model_stream.py",
            "agent_factory/runtime_protocol/conversation.py",
            "agent_factory/runtime_kernel/adapters/model.py",
            "agent_factory/runtime_kernel/nodes/standard/tool_call.py",
        ],
    },
    {
        "component": "attachment_and_knowledge_document_inspection",
        "classification": "inspect_untrusted_content_then_parse_in_budgeted_managed_jobs_before_atomic_derived_content_publication",
        "execution_unit": 8,
        "paths": [
            "web_frontend/backend/attachment_upload_store.py",
            "web_frontend/backend/routes/knowledge.py",
            "agent_factory/runtime_attachments.py",
            "agent_factory/document_processing.py",
            "agent_factory/office_document_parsers.py",
        ],
    },
)

LEGACY_OWNERSHIP_RULES = (
    ("agent_factory/create_agent/", 1, "delete"),
    ("agent_factory/evolution/", 1, "delete"),
    ("agent_factory/agent_registry/", 1, "delete"),
    ("agent_factory/tooling/builtins/agent_search/", 1, "delete"),
    ("agent_factory/tooling/builtins/agent_list/", 1, "delete"),
    ("agent_factory/tooling/builtins/agent_manufacture/", 1, "delete"),
    ("agent_factory/tooling/builtins/agent_evolve/", 1, "delete"),
    ("agent_factory/package_distribution.py", 1, "delete"),
    ("scripts/generate_agent_hub_package_schemas.py", 1, "delete"),
    ("services/agent_hub/", 1, "rewrite_preserve_release_features"),
    ("web_frontend/backend/routes/create_agent.py", 1, "delete"),
    ("web_frontend/backend/routes/agent_hub.py", 1, "rewrite_preserve_release_features"),
    ("web_frontend/frontend/src/api/agentHub.ts", 1, "rewrite_preserve_release_features"),
    ("web_frontend/frontend/src/views/AgentHubView.vue", 1, "rewrite_preserve_release_features"),
    ("web_frontend/backend/routes/agent_packages.py", 2, "delete"),
    ("web_frontend/frontend/src/api/agentPackages.ts", 2, "delete"),
    ("web_frontend/frontend/src/components/agent/AgentPackage", 2, "delete"),
    ("web_frontend/frontend/src/components/agent/AgentSessionPanel.vue", 2, "rewrite"),
    ("web_frontend/frontend/src/components/agent/AgentToolSettingsPanel.vue", 2, "rewrite"),
    ("web_frontend/frontend/src/components/agent/NewAgentSessionDialog.vue", 2, "rewrite"),
    ("web_frontend/frontend/src/components/agent/agentPackagePresentation.ts", 2, "delete"),
    ("web_frontend/frontend/src/components/chat/PublishConfirmationPanel.vue", 2, "delete"),
    ("web_frontend/frontend/src/composables/agent/", 2, "rewrite"),
    ("web_frontend/frontend/src/composables/commands/useAgentPackageCommands.ts", 2, "delete"),
    ("web_frontend/frontend/src/views/AgentPackageDetailView.vue", 2, "delete"),
    ("web_frontend/frontend/src/views/PublishedView.vue", 2, "delete"),
    ("web_frontend/frontend/src/stores/agent.ts", 2, "delete"),
    ("agent_factory/factory_graph/frontend_bridge/protocol", 3, "rewrite"),
    ("agent_factory/factory_graph/frontend_bridge/event_normalizer.py", 3, "rewrite"),
    ("agent_factory/factory_graph/frontend_bridge/runtime_events.py", 3, "rewrite"),
    ("web_frontend/frontend/src/types/protocol.ts", 3, "rewrite"),
    ("web_frontend/frontend/src/composables/commands/", 3, "rewrite"),
    ("web_frontend/frontend/src/stores/runtime", 3, "rewrite"),
    ("web_frontend/frontend/src/stores/runtimeSync.ts", 3, "rewrite"),
    ("agent_factory/runtime_kernel/model_inputs.py", 4, "rewrite_direct_prompt_assembly"),
    ("agent_factory/prompts.py", 4, "rewrite_direct_prompt_assembly"),
    ("agent_factory/runtime_kernel/model_operations/", 4, "rewrite_stream_normalization"),
    ("agent_factory/tooling/langgraph_node.py", 4, "rewrite_tool_call_lifecycle"),
    ("agent_factory/runtime_kernel/", 4, "rewrite_fixed_dual_graph"),
    ("agent_factory/runtime_protocol/", 3, "replace_with_unified_runtime_protocol"),
    ("agent_factory/event_persistence.py", 3, "replace_with_explicit_typed_event_policy"),
    ("agent_factory/dynamic_runtime/", 5, "build_authoritative_dynamic_runtime_services"),
    ("agent_factory/file_lock.py", 7, "replace_with_managed_lock_service"),
    ("agent_factory/contracts/events.py", 3, "replace_with_unified_runtime_protocol"),
    ("web_frontend/backend/runtime_event_pipeline.py", 3, "rewrite_event_projection"),
    ("agent_factory/runtime_render/", 4, "delete_package_render_manifest_or_rewrite_fixed_projection"),
    ("agent_factory/assembly/", 5, "delete"),
    ("agent_factory/background_task_policy.py", 7, "rewrite_temporary_runtime_tool_visibility"),
    ("agent_factory/file_capabilities.py", 8, "retain_shared_file_format_registry"),
    ("agent_factory/runtime_contracts/", 5, "delete"),
    ("agent_factory/package_runtime/", 5, "delete"),
    ("agent_factory/builtin_packages.py", 5, "delete"),
    ("agent_factory/env.py", 5, "replace_application_config_resolver"),
    ("SystemPackage/", 5, "delete"),
    ("agent_factory/factory_graph/frontend_bridge/agent_package", 5, "delete"),
    ("agent_factory/factory_graph/frontend_bridge/system_package_runtime_handle.py", 5, "delete"),
    ("agent_factory/factory_graph/frontend_bridge/runtime_adapter", 5, "rewrite"),
    ("agent_factory/factory_graph/frontend_bridge/session.py", 5, "replace_conversation_store"),
    ("agent_factory/factory_graph/session.py", 5, "replace_conversation_store"),
    ("web_frontend/backend/event_api_server.py", 5, "rewrite_composition_root"),
    ("web_frontend/backend/runtime_bridge.py", 5, "replace_dynamic_runtime_service"),
    ("web_frontend/backend/dynamic_runtime_api.py", 5, "replace_with_unified_runtime_protocol"),
    ("agent_factory/paths.py", 5, "rewrite"),
    ("src-tauri/", 5, "rewrite_then_regenerate"),
    ("agent_factory/agent_runtime_bridge/", 6, "extract_process_control_then_delete"),
    ("agent_factory/native_runtime/", 6, "rewrite"),
    ("agent_factory/environment_system/", 6, "merge_dependency_pool"),
    ("agent_factory/mcp_gateway/", 6, "converge_capability_transport"),
    ("agent_factory/skillhub_gateway/", 6, "converge_capability_transport"),
    ("agent_factory/tooling/extension_registry.py", 6, "replace_capability_registry"),
    ("agent_factory/tooling/factory_extensions.py", 6, "delete_binding_merge"),
    ("agent_factory/tooling/executor_fallback.py", 4, "delete_legacy_executor_policy"),
    ("agent_factory/tooling/gateway.py", 6, "rewrite_scoped_capability_policy"),
    ("agent_factory/tooling/output_store.py", 8, "migrate_identity"),
    ("agent_factory/tooling/runtime_settings.py", 6, "rewrite"),
    ("agent_factory/tooling/skills/", 6, "rewrite"),
    ("agent_factory/tooling/providers/", 6, "rewrite"),
    ("agent_factory/tooling/builtins/browser/", 7, "rewrite_runtime_instance_browser_boundary"),
    ("agent_factory/tooling/builtins/registry.py", 6, "rewrite"),
    ("agent_factory/tooling/builtins/aliases.py", 10, "migrate_then_delete"),
    ("agent_factory/models/embedding_model.py", 8, "remove_implicit_env_fallback"),
    ("agent_factory/models/temporal_context.py", 8, "replace_clock_and_timezone_authority"),
    ("agent_factory/runtime_attachments.py", 8, "replace_attachment_identity_and_projection"),
    ("agent_factory/tooling/builtins/agent_delegate/", 7, "rewrite_runtime_instance"),
    ("agent_factory/tooling/builtins/agent_team/", 7, "rewrite_runtime_instance"),
    ("agent_factory/tooling/builtins/deliver_result/", 7, "rewrite_runtime_instance"),
    ("agent_factory/agent_group_system/", 7, "rewrite_runtime_instance_projection"),
    ("agent_factory/collaboration_system/", 7, "rewrite_runtime_instance"),
    ("agent_factory/contracts/background_tasks.py", 7, "rewrite_runtime_instance"),
    ("agent_factory/contracts/", 3, "replace_with_unified_runtime_protocol"),
    ("web_frontend/backend/routes/agent_group.py", 7, "rewrite_runtime_instance_projection"),
    ("web_frontend/frontend/src/api/agentGroup.ts", 7, "rewrite_runtime_instance_projection"),
    ("web_frontend/frontend/src/stores/agentGroup.ts", 7, "rewrite_runtime_instance_projection"),
    ("web_frontend/frontend/src/views/AgentGroupView.vue", 7, "rewrite_runtime_instance_projection"),
    ("agent_factory/memory_system/", 8, "migrate_scope"),
    ("agent_factory/knowledge_system/", 8, "migrate_scope"),
    ("agent_factory/scheduler_system/", 8, "migrate_scope"),
    ("agent_factory/resource_system/", 8, "migrate_identity"),
    ("agent_factory/trace_system/", 8, "migrate_identity"),
    ("agent_factory/tip_system/", 8, "migrate_identity"),
    ("agent_factory/model_pool/usage.py", 8, "migrate_dimensions"),
    ("agent_factory/model_pool/", 6, "rewrite_operation_selection"),
    ("agent_factory/models/", 7, "route_model_operations_through_coordinator"),
    ("agent_factory/context_system/", 8, "rewrite_single_context_policy"),
    ("agent_factory/document_processing.py", 7, "move_blocking_work_to_managed_worker"),
    ("agent_factory/office_document_parsers.py", 7, "move_blocking_work_to_managed_worker"),
    ("agent_factory/native_directory_picker.py", 8, "retain_platform_adapter"),
    ("agent_factory/observed_process.py", 7, "retain_managed_process_primitive"),
    ("agent_factory/runtime_workspace.py", 8, "rewrite_workspace_identity"),
    ("agent_factory/workspace_mounts.py", 8, "rewrite_canonical_mount_identity"),
    ("agent_factory/workspace_system.py", 8, "migrate_scope"),
    ("agent_factory/sqlite_runtime.py", 8, "retain_shared_sqlite_lifecycle_primitive"),
    ("agent_factory/artifact_system/", 8, "migrate_identity"),
    ("agent_factory/factory_graph/frontend_bridge/workspace_resources.py", 8, "migrate_scope"),
    ("web_frontend/backend/conversation_storage.py", 8, "replace_conversation_store"),
    ("web_frontend/backend/attachment_upload_store.py", 8, "migrate_identity"),
    ("web_frontend/backend/routes/knowledge.py", 8, "rewrite_import_transaction"),
    ("web_frontend/frontend/src/components/knowledge/KnowledgeSourceFormModal.vue", 8, "rewrite_import_manifest"),
    ("web_frontend/backend/runtime_event_journal.py", 8, "diagnostic_only"),
    ("web_frontend/backend/event_loop_watchdog.py", 7, "retain_as_diagnostic_only"),
    ("web_frontend/backend/parent_process_watchdog.py", 5, "rewrite_managed_application_lifecycle"),
    ("web_frontend/backend/routes/", 9, "rewrite"),
    ("web_frontend/backend/agent_hub_client.py", 9, "rewrite_preserve_release_features"),
    ("web_frontend/frontend/src/", 9, "rewrite"),
    ("agent_factory/tooling/", 10, "replace_capability_registry"),
    ("test_native_e2e_manual.py", 12, "delete_or_rewrite"),
    ("tests/", 12, "rewrite"),
    ("deploy/", 12, "rewrite"),
    ("docs/", 12, "rewrite"),
    ("README", 12, "rewrite"),
    ("scripts/bundle_python.py", 12, "rewrite_packaging_manifest"),
    ("scripts/package_macos.sh", 12, "rewrite_release_composition"),
    ("scripts/package_windows.ps1", 12, "rewrite_release_composition"),
    (".github/workflows/build.yml", 12, "rewrite_release_composition"),
    ("pyproject.toml", 12, "rewrite_distribution_manifest"),
    ("web_frontend/frontend/package-lock.json", 12, "regenerate_dependency_lock"),
    ("scripts/generate_icons.py", 12, "retain_generated_asset_pipeline"),
)

DATA_ROOTS = (
    "agent_group",
    "agent_runtime",
    "attachment_uploads",
    "background_tasks",
    "benchmark",
    "checkpoints",
    "collaboration",
    "create_agent_workspaces",
    "dependency_pool",
    "extension_registry",
    "factory",
    "logs",
    "mcp",
    "memory",
    "model_pool",
    "packages",
    "resources",
    "runtime_events",
    "scheduler",
    "sessions",
    "tips",
    "tool_outputs",
    "workspaces",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit legacy Dynamic Runtime refactor surfaces without mutating data.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    data_root = (args.data_root or repo_root / ".agentfactory").expanduser().resolve()
    report = {
        "schema_version": "dynamic_runtime_legacy_inventory.v21",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "data_root": str(data_root),
        "secret_policy": "counts_and_paths_only_no_values",
        "source_inventory": source_inventory(repo_root),
        "component_ledger": component_ledger(repo_root),
        "data_inventory": data_inventory(data_root, repo_root=repo_root),
        "migration_policy": {
            "preserve": [
                "model_profiles_and_credentials",
                "registered_mcp_servers_and_credentials",
                "installed_skills",
                "custom_tools",
                "user_conversations_and_workspaces",
                "attachments_and_artifacts",
                "user_and_workspace_memory",
                "global_knowledge_sources",
                "workspace_bound_scheduler_jobs",
                "dependency_cache_with_valid_digest",
                "application_releases_and_update_metadata",
            ],
            "extract_then_delete": [
                "package_skills",
                "package_tools",
                "package_mcp_references",
                "package_resources_with_unambiguous_capability_owner",
                "package_sessions_with_valid_workspace",
                "package_knowledge_sources",
                "package_scheduler_jobs_convertible_to_main_agent_messages",
            ],
            "delete": [
                "package_runtime_state",
                "manufacturing_and_evolution_state",
                "agent_registry_search_index",
                "package_scheduler_seeds",
                "package_environment_locks",
                "package_process_bridge_state",
                "duplicate_runtime_event_transcript_projection",
                "process_global_tool_approval_trust",
                "unscoped_tool_outputs",
                "legacy_prompt_binding_and_executor_fallback_policy",
                "tip_side_conversation_runtime",
                "duplicate_provider_message_repair_paths",
                "volatile_process_local_command_state",
                "split_state_event_projection_without_outbox",
            ],
        },
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        output = args.output.expanduser()
        if not output.is_absolute():
            output = repo_root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(output)
        print(output)
    return 0


def source_inventory(repo_root: Path) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = {key: {} for key in LEGACY_PATTERNS}
    totals: Counter[str] = Counter()
    for path in iter_source_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(repo_root).as_posix()
        searchable = f"{relative}\n{text}"
        for key, pattern in LEGACY_PATTERNS.items():
            count = len(pattern.findall(searchable))
            if count:
                groups[key][relative] = count
                totals[key] += count
    file_ledger = legacy_file_ledger(groups)
    return {
        "totals": dict(sorted(totals.items())),
        "files": {key: dict(sorted(value.items())) for key, value in groups.items()},
        "file_ledger": file_ledger,
        "ownership_summary": dict(sorted(Counter(item["classification"] for item in file_ledger).items())),
        "unassigned_files": [item["path"] for item in file_ledger if item["execution_unit"] is None],
    }


def legacy_file_ledger(groups: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    files = sorted({path for entries in groups.values() for path in entries})
    ledger = []
    for path in files:
        rule = next((item for item in LEGACY_OWNERSHIP_RULES if path.startswith(item[0])), None)
        categories = sorted(key for key, entries in groups.items() if path in entries)
        ledger.append(
            {
                "path": path,
                "categories": categories,
                "execution_unit": rule[1] if rule else None,
                "classification": rule[2] if rule else "review_required",
                "matched_rule": rule[0] if rule else None,
            }
        )
    return ledger


def component_ledger(repo_root: Path) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for item in LEGACY_COMPONENTS:
        paths = [
            {
                "path": relative,
                "exists": (repo_root / relative).exists(),
            }
            for relative in item["paths"]
        ]
        ledger.append({**item, "paths": paths})
    return ledger


def data_inventory(data_root: Path, *, repo_root: Path) -> dict[str, Any]:
    roots = {
        name: path_summary(data_root / name)
        for name in DATA_ROOTS
    }
    sqlite_files = sorted(
        path
        for path in data_root.rglob("*.sqlite")
        if path.is_file() and not path.is_symlink()
    ) if data_root.is_dir() else []
    return {
        "roots": roots,
        "unclassified_roots": unclassified_data_roots(data_root),
        "external_legacy_roots": {
            ".agent_runtime": path_summary(repo_root / ".agent_runtime"),
        },
        "sqlite": {
            path.relative_to(data_root).as_posix(): sqlite_summary(path)
            for path in sqlite_files
        },
        "configured_counts": configured_counts(data_root),
    }


def configured_counts(data_root: Path) -> dict[str, int]:
    return {
        "package_directories": child_directory_count(data_root / "packages"),
        "session_json_files": file_count(data_root / "sessions", "*.json"),
        "workspace_records": file_count(data_root / "workspaces", "workspace.json"),
        "registered_mcp_servers": json_list_count(data_root / "extension_registry" / "mcp_servers.json", "servers"),
        "registered_skills": json_list_count(data_root / "extension_registry" / "enabled_skills.json", "skills"),
        "mcp_source_directories": child_directory_count(data_root / "mcp"),
        "sqlite_backup_files": sqlite_backup_count(data_root),
    }


def unclassified_data_roots(data_root: Path) -> list[str]:
    if not data_root.is_dir():
        return []
    known = set(DATA_ROOTS)
    return sorted(
        child.name
        for child in data_root.iterdir()
        if child.is_dir() and not child.is_symlink() and child.name not in known
    )


def sqlite_backup_count(data_root: Path) -> int:
    if not data_root.is_dir():
        return 0
    return sum(
        1
        for path in data_root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and (
            ".sqlite.backup" in path.name
            or path.name.endswith(".sqlite.bak")
            or ".sqlite.before_" in path.name
        )
    )


def sqlite_summary(path: Path) -> dict[str, Any]:
    if path.stat().st_size == 0:
        return {"status": "empty", "size_bytes": 0, "tables": {}}
    uri = f"file:{path.resolve()}?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            tables = [
                str(row[0])
                for row in connection.execute(
                    "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
                )
            ]
            counts = {}
            for table in tables:
                quoted = table.replace('"', '""')
                counts[table] = int(connection.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()[0])
        return {"status": "ok", "size_bytes": path.stat().st_size, "tables": counts}
    except sqlite3.Error as exc:
        return {
            "status": "unreadable",
            "size_bytes": path.stat().st_size,
            "error_type": type(exc).__name__,
        }


def path_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "file_count": 0, "directory_count": 0, "size_bytes": 0}
    if path.is_file():
        return {"exists": True, "file_count": 1, "directory_count": 0, "size_bytes": path.stat().st_size}
    file_total = 0
    directory_total = 0
    size_total = 0
    for child in path.rglob("*"):
        if child.is_symlink():
            continue
        if child.is_dir():
            directory_total += 1
        elif child.is_file():
            file_total += 1
            try:
                size_total += child.stat().st_size
            except OSError:
                continue
    return {
        "exists": True,
        "file_count": file_total,
        "directory_count": directory_total,
        "size_bytes": size_total,
    }


def iter_source_files(repo_root: Path):
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative_parts = path.relative_to(repo_root).parts
        relative = path.relative_to(repo_root).as_posix()
        if any(part in EXCLUDED_PARTS for part in relative_parts):
            continue
        if any(relative == prefix or relative.startswith(prefix) for prefix in EXCLUDED_SOURCE_PREFIXES):
            continue
        yield path


def child_directory_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_dir() and not child.is_symlink())


def file_count(path: Path, pattern: str) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.rglob(pattern) if child.is_file() and not child.is_symlink())


def json_list_count(path: Path, key: str) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    values = payload.get(key) if isinstance(payload, dict) else None
    return len(values) if isinstance(values, list) else 0


if __name__ == "__main__":
    raise SystemExit(main())
