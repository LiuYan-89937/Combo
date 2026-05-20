import {z} from 'zod';
import {randomUUID} from 'node:crypto';

export const factoryModeSchema = z.enum(['chat', 'create_agent', 'agent_package']);
export type FactoryMode = z.infer<typeof factoryModeSchema>;

export const commandSchema = z.object({
	type: z.enum([
		'start_session',
		'list_sessions',
		'switch_session',
		'new_session',
		'set_mode',
		'send_message',
		'rerun_from_stage',
		'list_agent_packages',
		'select_agent_package',
		'delete_agent_package',
		'list_agent_package_sessions',
		'run_agent_package',
		'resume_interrupt',
		'set_options',
		'shutdown'
	]),
	request_id: z.string().nullable().optional(),
	session_id: z.string().nullable().optional(),
	resume_latest: z.boolean().optional(),
	mode: factoryModeSchema.nullable().optional(),
	message: z.string().nullable().optional(),
	payload: z.record(z.unknown()).optional(),
	options: z.record(z.unknown()).optional()
}).strict();

export type FactoryCommand = z.infer<typeof commandSchema>;

export const eventSchema = z.object({
	event_id: z.string(),
	event_type: z.enum([
		'runtime_ready',
		'runtime_options_changed',
		'session_started',
		'session_switched',
		'sessions_listed',
		'agent_packages_listed',
		'agent_package_selected',
		'agent_package_deleted',
		'agent_package_sessions_listed',
		'mode_changed',
		'run_started',
		'run_completed',
		'run_failed',
		'stage_started',
		'stage_completed',
		'stage_failed',
		'node_started',
		'node_progress',
		'node_completed',
		'node_failed',
		'model_call_started',
		'model_stream_delta',
		'model_message_completed',
		'model_call_completed',
		'model_call_failed',
		'tool_call_proposed',
		'tool_approval_requested',
		'tool_approval_resolved',
		'tool_call_started',
		'tool_call_completed',
		'tool_call_failed',
		'tool_observation_available',
		'memory_write_queued',
		'memory_write_queued_failed',
		'memory_segment_prepared',
		'memory_extraction_completed',
		'memory_write_completed',
		'memory_write_failed',
		'memory_retrieval_completed',
		'memory_injection_completed',
		'scheduler_job_created',
		'scheduler_job_updated',
		'scheduler_job_deleted',
		'scheduler_run_scheduled',
		'scheduler_run_started',
		'scheduler_run_completed',
		'scheduler_run_failed',
		'scheduler_run_skipped',
		'scheduler_run_cancelled',
		'interrupt_requested',
		'runtime_paused',
		'runtime_resumed',
		'trace_snapshot',
		'debug_patch',
		'error'
	]),
	protocol_version: z.string(),
	producer_type: z.string(),
	request_id: z.string().nullable(),
	run_id: z.string().nullable(),
	session_id: z.string().nullable(),
	thread_id: z.string().nullable(),
	mode: factoryModeSchema.nullable(),
	graph_id: z.string().nullable(),
	node_id: z.string().nullable(),
	node_label: z.string().nullable(),
	node_kind: z.string().nullable(),
	stage_id: z.string().nullable(),
	span_id: z.string().nullable(),
	parent_span_id: z.string().nullable(),
	sequence: z.number(),
	timestamp: z.string(),
	severity: z.string().nullable(),
	message: z.string().nullable(),
	payload: z.record(z.unknown())
}).strict();

export type FactoryEvent = z.infer<typeof eventSchema>;

export function command(type: FactoryCommand['type'], patch: Partial<FactoryCommand> = {}): FactoryCommand {
	return {
		type,
		request_id: patch.request_id ?? randomUUID(),
		...patch
	};
}
