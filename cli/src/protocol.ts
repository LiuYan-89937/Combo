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
	type: z.enum([
		'ready',
		'session_changed',
		'sessions_listed',
		'mode_changed',
		'run_started',
		'stage_started',
		'stage_delta',
		'model_token',
		'tool_call_requested',
		'tool_result',
		'interrupt_requested',
		'resource_input_requested',
		'stage_completed',
		'run_completed',
		'run_failed',
		'error'
	]),
	request_id: z.string().nullable().optional(),
	session_id: z.string().nullable().optional(),
	mode: factoryModeSchema.nullable().optional(),
	node_id: z.string().nullable().optional(),
	stage_id: z.string().nullable().optional(),
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
