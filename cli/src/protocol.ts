import {z} from 'zod';
import {randomUUID} from 'node:crypto';

export const factoryModeSchema = z.enum(['chat', 'create_agent']);
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
});

export type FactoryCommand = z.infer<typeof commandSchema>;

export const eventSchema = z.object({
	event_id: z.string(),
	event_type: z.enum([
		'runtime_ready',
		'session_started',
		'session_switched',
		'sessions_listed',
		'mode_changed',
		'run_started',
		'run_completed',
		'run_failed',
		'stage_started',
		'stage_completed',
		'stage_failed',
		'node_started',
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
		'interrupt_requested',
		'runtime_paused',
		'runtime_resumed',
		'resource_input_requested',
		'trace_snapshot',
		'debug_patch',
		'error'
	]),
	request_id: z.string().nullable().optional(),
	run_id: z.string().nullable().optional(),
	session_id: z.string().nullable().optional(),
	mode: factoryModeSchema.nullable().optional(),
	graph_id: z.string().nullable().optional(),
	node_id: z.string().nullable().optional(),
	stage_id: z.string().nullable().optional(),
	span_id: z.string().nullable().optional(),
	parent_span_id: z.string().nullable().optional(),
	sequence: z.number(),
	timestamp: z.string(),
	message: z.string().nullable().optional(),
	payload: z.record(z.unknown()).optional()
});

export type FactoryEvent = z.infer<typeof eventSchema>;

export function command(type: FactoryCommand['type'], patch: Partial<FactoryCommand> = {}): FactoryCommand {
	return {
		type,
		request_id: patch.request_id ?? randomUUID(),
		...patch
	};
}
