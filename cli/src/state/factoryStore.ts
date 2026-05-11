import {type FactoryEvent, type FactoryMode} from '../protocol.js';

export type FactoryUiState = {
	ready: boolean;
	mode: FactoryMode | null;
	sessionId: string | null;
	sessions: Array<Record<string, unknown>>;
	logs: string[];
	stageDeltas: Array<FactoryEvent>;
	toolEvents: Array<FactoryEvent>;
	pendingInterrupt: FactoryEvent | null;
	streamingText: string;
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
	stageDeltas: [],
	toolEvents: [],
	pendingInterrupt: null,
	streamingText: '',
	showState: false,
	showMessages: true,
	stopAfterStage: 'resource_and_condition_planning',
	lastError: null
};

export function reduceFactoryEvent(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	switch (event.type) {
		case 'ready':
			return {...state, ready: true, logs: [...state.logs, 'runtime bridge ready']};
		case 'session_changed': {
			const session = (event.payload?.session ?? {}) as Record<string, unknown>;
			return {
				...state,
				sessionId: String(session.session_id ?? event.session_id ?? ''),
				mode: (session.current_mode as FactoryMode | null) ?? event.mode ?? null,
				logs: [...state.logs, `session: ${String(session.session_id ?? event.session_id ?? '-')}`]
			};
		}
		case 'sessions_listed':
			return {...state, sessions: (event.payload?.sessions as Array<Record<string, unknown>>) ?? []};
		case 'mode_changed':
			return {...state, mode: event.mode ?? null, logs: [...state.logs, `mode: ${event.mode ?? '-'}`]};
		case 'run_started':
			return {...state, streamingText: '', pendingInterrupt: null, logs: [...state.logs, 'run started']};
		case 'stage_delta':
			return {...state, stageDeltas: [...state.stageDeltas.slice(-30), event]};
		case 'model_token':
			return {...state, streamingText: state.streamingText + (event.message ?? '')};
		case 'tool_call_requested':
		case 'tool_result':
			return {...state, toolEvents: [...state.toolEvents.slice(-30), event]};
		case 'interrupt_requested':
		case 'resource_input_requested':
			return {...state, pendingInterrupt: event, logs: [...state.logs, `interrupt: ${String(event.payload?.type ?? event.type)}`]};
		case 'stage_completed':
			return {...state, logs: [...state.logs, `stage completed: ${event.stage_id ?? '-'}`]};
		case 'run_completed':
			return {
				...state,
				pendingInterrupt: null,
				logs: [...state.logs, `run completed: ${String(event.payload?.status ?? '-')}`]
			};
		case 'run_failed':
			return {...state, pendingInterrupt: null, lastError: event.message ?? 'run failed'};
		case 'error':
			return {...state, lastError: event.message ?? 'unknown error'};
		default:
			return state;
	}
}

