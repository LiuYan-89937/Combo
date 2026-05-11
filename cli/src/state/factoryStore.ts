import {type FactoryEvent, type FactoryMode} from '../protocol.js';

export type ModelStream = {
	streamId: string;
	nodeId: string | null;
	content: string;
	active: boolean;
	completedAt: string | null;
};

export type ToolActivity = {
	eventType: FactoryEvent['event_type'];
	timestamp: string;
	nodeId: string | null;
	payload: Record<string, unknown>;
};

export type SpanRecord = {
	spanId: string;
	parentSpanId: string | null;
	eventType: FactoryEvent['event_type'];
	stageId: string | null;
	nodeId: string | null;
	timestamp: string;
	payload: Record<string, unknown>;
};

export type FactoryUiState = {
	ready: boolean;
	mode: FactoryMode | null;
	sessionId: string | null;
	sessions: Array<Record<string, unknown>>;
	logs: string[];
	events: Array<FactoryEvent>;
	spans: Record<string, SpanRecord>;
	modelStreams: Record<string, ModelStream>;
	toolActivities: ToolActivity[];
	debugPatches: FactoryEvent[];
	pendingInterrupt: FactoryEvent | null;
	currentRunId: string | null;
	runStatus: 'idle' | 'running' | 'interrupted' | 'completed' | 'failed';
	helpVisible: boolean;
	showState: boolean;
	showMessages: boolean;
	stopAfterStage: string | null;
	lastError: string | null;
};

export const initialFactoryUiState: FactoryUiState = {
	ready: false,
	mode: null,
	sessionId: null,
	sessions: [],
	logs: [],
	events: [],
	spans: {},
	modelStreams: {},
	toolActivities: [],
	debugPatches: [],
	pendingInterrupt: null,
	currentRunId: null,
	runStatus: 'idle',
	helpVisible: true,
	showState: false,
	showMessages: true,
	stopAfterStage: 'resource_and_condition_planning',
	lastError: null
};

export function reduceFactoryEvent(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	const base = recordEvent(recordSpan(state, event), event);
	switch (event.event_type) {
		case 'runtime_ready':
			return {...base, ready: true, logs: [...base.logs, 'runtime bridge ready']};
		case 'session_started':
		case 'session_switched': {
			const session = (event.payload?.session ?? {}) as Record<string, unknown>;
			return {
				...base,
				sessionId: String(session.session_id ?? event.session_id ?? ''),
				mode: (session.current_mode as FactoryMode | null) ?? event.mode ?? null,
				logs: [...base.logs, `session: ${String(session.session_id ?? event.session_id ?? '-')}`]
			};
		}
		case 'sessions_listed':
			return {...base, sessions: (event.payload?.sessions as Array<Record<string, unknown>>) ?? []};
		case 'mode_changed':
			return {...base, mode: event.mode ?? null, helpVisible: false, logs: [...base.logs, `mode: ${event.mode ?? '-'}`]};
		case 'run_started':
			return {
				...base,
				modelStreams: {},
				toolActivities: [],
				debugPatches: [],
				currentRunId: event.run_id ?? null,
				runStatus: 'running',
				pendingInterrupt: null,
				helpVisible: false,
				logs: [...base.logs, 'run started']
			};
		case 'model_call_started':
			return upsertModelStream({...base, logs: [...base.logs, `model started: ${event.node_id ?? '-'}`]}, event, true);
		case 'model_stream_delta':
			return appendModelDelta(base, event);
		case 'model_message_completed':
			return completeModelStream(base, event);
		case 'model_call_completed':
			return {...base, logs: [...base.logs, `model completed: ${String(event.payload?.prompt_id ?? event.node_id ?? '-')}`]};
		case 'model_call_failed':
			return {...base, logs: [...base.logs, `model failed: ${String(event.payload?.prompt_id ?? event.node_id ?? '-')}`], lastError: String(event.payload?.message ?? event.message ?? 'model failed')};
		case 'tool_call_proposed':
		case 'tool_approval_resolved':
		case 'tool_call_started':
		case 'tool_call_completed':
		case 'tool_call_failed':
		case 'tool_observation_available':
			return {...base, toolActivities: [...base.toolActivities.slice(-40), toolActivity(event)]};
		case 'debug_patch':
			return applyDebugPatch({...base, debugPatches: [...base.debugPatches.slice(-30), event]}, event);
		case 'node_started':
			return {...base, logs: [...base.logs, `node started: ${event.node_id ?? '-'}`]};
		case 'node_completed':
			return {...base, logs: [...base.logs, `node completed: ${event.node_id ?? '-'}`]};
		case 'node_failed':
			return {...base, runStatus: 'failed', lastError: `node failed: ${event.node_id ?? '-'}`};
		case 'interrupt_requested':
			return {
				...base,
				runStatus: 'interrupted',
				pendingInterrupt: base.pendingInterrupt ?? event,
				logs: [...base.logs, `interrupt: ${String(event.payload?.type ?? event.event_type)}`]
			};
		case 'resource_input_requested':
		case 'tool_approval_requested':
			return {
				...base,
				toolActivities: event.event_type === 'tool_approval_requested' ? [...base.toolActivities.slice(-40), toolActivity(event)] : base.toolActivities,
				runStatus: 'interrupted',
				pendingInterrupt: event,
				logs: [...base.logs, `interrupt: ${String(event.payload?.type ?? event.event_type)}`]
			};
		case 'runtime_resumed':
			return {...base, runStatus: 'running', pendingInterrupt: null, logs: [...base.logs, 'runtime resumed']};
		case 'stage_completed':
			return {...base, logs: [...base.logs, `stage completed: ${event.stage_id ?? '-'}`]};
		case 'run_completed':
			return {
				...base,
				runStatus: 'completed',
				pendingInterrupt: null,
				logs: [...base.logs, `run completed: ${String(event.payload?.status ?? '-')}`]
			};
		case 'run_failed':
			return {...base, runStatus: 'failed', pendingInterrupt: null, lastError: event.message ?? 'run failed'};
		case 'error':
			return {...base, lastError: event.message ?? 'unknown error'};
		default:
			return base;
	}
}

function recordEvent(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	return {...state, events: [...state.events.slice(-120), event]};
}

function recordSpan(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	if (!event.span_id) {
		return state;
	}
	return {
		...state,
		spans: {
			...state.spans,
			[event.span_id]: {
				spanId: event.span_id,
				parentSpanId: event.parent_span_id ?? null,
				eventType: event.event_type,
				stageId: event.stage_id ?? null,
				nodeId: event.node_id ?? null,
				timestamp: event.timestamp,
				payload: event.payload ?? {}
			}
		}
	};
}

function upsertModelStream(state: FactoryUiState, event: FactoryEvent, active: boolean): FactoryUiState {
	const streamId = streamIdOf(event);
	if (!streamId) {
		return state;
	}
	return {
		...state,
		modelStreams: {
			...state.modelStreams,
			[streamId]: state.modelStreams[streamId] ?? {
				streamId,
				nodeId: event.node_id ?? null,
				content: '',
				active,
				completedAt: null
			}
		}
	};
}

function appendModelDelta(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	const streamId = streamIdOf(event);
	if (!streamId) {
		return state;
	}
	const current = state.modelStreams[streamId] ?? {
		streamId,
		nodeId: event.node_id ?? null,
		content: '',
		active: true,
		completedAt: null
	};
	return {
		...state,
		modelStreams: {
			...state.modelStreams,
			[streamId]: {
				...current,
				content: current.content + String(event.payload?.delta ?? ''),
				active: true
			}
		}
	};
}

function completeModelStream(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	const streamId = streamIdOf(event);
	if (!streamId) {
		return state;
	}
	const current = state.modelStreams[streamId] ?? {
		streamId,
		nodeId: event.node_id ?? null,
		content: String(event.payload?.content ?? ''),
		active: false,
		completedAt: event.timestamp
	};
	return {
		...state,
		modelStreams: {
			...state.modelStreams,
			[streamId]: {
				...current,
				content: current.content || String(event.payload?.content ?? ''),
				active: false,
				completedAt: event.timestamp
			}
		}
	};
}

function toolActivity(event: FactoryEvent): ToolActivity {
	return {
		eventType: event.event_type,
		timestamp: event.timestamp,
		nodeId: event.node_id ?? null,
		payload: event.payload ?? {}
	};
}

function applyDebugPatch(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	if (event.node_id !== 'bridge_options') {
		return state;
	}
	const options = (event.payload?.options ?? {}) as Record<string, unknown>;
	return {
		...state,
		stopAfterStage: (options.stop_after_stage as string | null | undefined) ?? state.stopAfterStage,
		showState: Boolean(options.show_state ?? state.showState),
		showMessages: Boolean(options.show_messages ?? state.showMessages)
	};
}

function streamIdOf(event: FactoryEvent): string | null {
	const streamId = event.payload?.stream_id;
	return typeof streamId === 'string' && streamId ? streamId : null;
}
