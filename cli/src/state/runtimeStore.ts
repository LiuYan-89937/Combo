import {type FactoryEvent, type FactoryMode} from '../protocol.js';

export type ModelStream = {
	streamId: string;
	nodeId: string | null;
	content: string;
	active: boolean;
	completedAt: string | null;
};

export type StageLifecycle = 'waiting' | 'running' | 'completed' | 'failed';

export type StageStatus = {
	stageId: string;
	status: StageLifecycle;
	nodeId: string | null;
	startedAt: string | null;
	completedAt: string | null;
	failedAt: string | null;
	lastEventType: FactoryEvent['event_type'];
	lastMessage: string | null;
};

export type NodeStatus = {
	nodeId: string;
	stageId: string | null;
	status: StageLifecycle;
	label: string | null;
	kind: string | null;
	startedAt: string | null;
	completedAt: string | null;
	failedAt: string | null;
	message: string | null;
	payload: Record<string, unknown>;
};

export type ActivityColor = 'gray' | 'blue' | 'cyan' | 'green' | 'yellow' | 'red';

export type RunActivity = {
	activityKey: string;
	eventType: FactoryEvent['event_type'];
	timestamp: string;
	stageId: string | null;
	nodeId: string | null;
	label: string;
	detail: string;
	color: ActivityColor;
};

export type ToolLifecycle = 'proposed' | 'approval' | 'started' | 'completed' | 'failed' | 'observed';

export type ToolActivity = {
	activityKey: string;
	eventType: FactoryEvent['event_type'];
	timestamp: string;
	createdAt: string;
	stageId: string | null;
	nodeId: string | null;
	toolCallId: string | null;
	toolName: string;
	status: ToolLifecycle;
	approvalState: 'pending' | 'approved' | 'rejected' | 'custom' | 'trusted' | null;
	argsPreview: string | null;
	resultPreview: string | null;
	stdoutPreview: string | null;
	stderrPreview: string | null;
	exitCode: number | null;
	durationMs: number | null;
	searchText: string;
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

export type TranscriptRole = 'user' | 'assistant' | 'tool' | 'interrupt' | 'system';

export type TranscriptItem = {
	id: string;
	role: TranscriptRole;
	timestamp: string;
	title: string;
	content: string;
	eventType?: FactoryEvent['event_type'];
	streamId?: string;
	active?: boolean;
	metadata?: Record<string, unknown>;
};

export type RuntimeState = {
	ready: boolean;
	mode: FactoryMode | null;
	sessionId: string | null;
	sessionTitle: string | null;
	sessions: Array<Record<string, unknown>>;
	sessionPickerOpen: boolean;
	logs: string[];
	transcript: TranscriptItem[];
	events: Array<FactoryEvent>;
	spans: Record<string, SpanRecord>;
	stageStatuses: Record<string, StageStatus>;
	nodeStatuses: Record<string, NodeStatus>;
	currentStageId: string | null;
	currentNodeId: string | null;
	recentActivities: RunActivity[];
	modelStreams: Record<string, ModelStream>;
	toolActivities: ToolActivity[];
	debugEvents: FactoryEvent[];
	pendingInterrupt: FactoryEvent | null;
	currentRunId: string | null;
	runStatus: 'idle' | 'running' | 'interrupted' | 'completed' | 'failed';
	helpVisible: boolean;
	showState: boolean;
	showMessages: boolean;
	toolGrep: string;
	stopAfterStage: string | null;
	lastError: string | null;
	errors: string[];
};

export type RuntimeAction =
	| FactoryEvent
	| {ui_type: 'set_tool_grep'; query: string}
	| {ui_type: 'set_session_picker_open'; open: boolean}
	| {ui_type: 'local_user_message'; message: string}
	| {ui_type: 'interrupt_response_submitted'; message: string}
	| {ui_type: 'show_help'}
	| {ui_type: 'notice'; message: string};

const STREAM_FLUSH_MS = 33;

export function createInitialRuntimeState(): RuntimeState {
	return {
	ready: false,
	mode: null,
	sessionId: null,
	sessionTitle: null,
	sessions: [],
	sessionPickerOpen: false,
	logs: [],
	transcript: [],
	events: [],
	spans: {},
	stageStatuses: {},
	nodeStatuses: {},
	currentStageId: null,
	currentNodeId: null,
	recentActivities: [],
	modelStreams: {},
	toolActivities: [],
	debugEvents: [],
	pendingInterrupt: null,
	currentRunId: null,
	runStatus: 'idle',
	helpVisible: true,
	showState: false,
	showMessages: true,
	toolGrep: '',
	stopAfterStage: 'assembly_spec_generation',
	lastError: null,
	errors: []
};
}

export class RuntimeStore {
	private state: RuntimeState = createInitialRuntimeState();
	private readonly listeners = new Set<() => void>();
	private pendingStreamEvents: FactoryEvent[] = [];
	private streamTimer: ReturnType<typeof setTimeout> | null = null;

	getSnapshot = (): RuntimeState => this.state;

	subscribe = (listener: () => void): (() => void) => {
		this.listeners.add(listener);
		return () => {
			this.listeners.delete(listener);
		};
	};

	dispatch = (action: RuntimeAction): void => {
		if ('event_type' in action && action.event_type === 'model_stream_delta') {
			this.pendingStreamEvents.push(action);
			this.scheduleStreamFlush();
			return;
		}
		if ('event_type' in action && isImmediateEvent(action.event_type)) {
			this.flushStreamEvents();
		}
		this.state = reduceRuntimeAction(this.state, action);
		this.notify();
	};

	destroy(): void {
		if (this.streamTimer) {
			clearTimeout(this.streamTimer);
			this.streamTimer = null;
		}
		this.pendingStreamEvents = [];
		this.listeners.clear();
	}

	private scheduleStreamFlush(): void {
		if (this.streamTimer) {
			return;
		}
		this.streamTimer = setTimeout(() => {
			this.streamTimer = null;
			this.flushStreamEvents();
		}, STREAM_FLUSH_MS);
	}

	private flushStreamEvents(): void {
		if (!this.pendingStreamEvents.length) {
			return;
		}
		let next = this.state;
		for (const event of this.pendingStreamEvents) {
			next = reduceRuntimeEvent(next, event);
		}
		this.pendingStreamEvents = [];
		this.state = next;
		this.notify();
	}

	private notify(): void {
		for (const listener of this.listeners) {
			listener();
		}
	}
}

export function createRuntimeStore(): RuntimeStore {
	return new RuntimeStore();
}

export function reduceRuntimeAction(state: RuntimeState, action: RuntimeAction): RuntimeState {
	if ('event_type' in action) {
		return reduceRuntimeEvent(state, action);
	}
	if (action.ui_type === 'set_tool_grep') {
		return setToolGrep(state, action.query === 'off' ? '' : action.query);
	}
	if (action.ui_type === 'set_session_picker_open') {
		return {...state, sessionPickerOpen: action.open};
	}
	if (action.ui_type === 'local_user_message') {
		return appendTranscript(state, {
			id: `local-user-${Date.now()}-${state.transcript.length}`,
			role: 'user',
			timestamp: new Date().toISOString(),
			title: 'You',
			content: action.message
		});
	}
	if (action.ui_type === 'interrupt_response_submitted') {
		return appendTranscript(state, {
			id: `local-interrupt-${Date.now()}-${state.transcript.length}`,
			role: 'interrupt',
			timestamp: new Date().toISOString(),
			title: 'Interrupt Response',
			content: action.message
		});
	}
	if (action.ui_type === 'show_help') {
		return {...state, helpVisible: true};
	}
	if (action.ui_type === 'notice') {
		return {...state, logs: [...state.logs.slice(-20), action.message]};
	}
	return state;
}

export function reduceRuntimeEvent(state: RuntimeState, event: FactoryEvent): RuntimeState {
	const base = recordEvent(recordSpan(state, event), event);
	switch (event.event_type) {
		case 'runtime_ready':
			return {...base, ready: true, logs: [...base.logs, 'runtime bridge ready']};
		case 'session_started':
		case 'session_switched': {
			const session = (event.payload?.session ?? {}) as Record<string, unknown>;
			const transcript = transcriptFromSession(session, event.mode ?? null);
			return {
				...base,
				sessionId: String(session.session_id ?? event.session_id ?? ''),
				sessionTitle: sessionTitle(session),
				mode: (session.current_mode as FactoryMode | null) ?? event.mode ?? null,
				transcript,
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
				stageStatuses: {},
				nodeStatuses: {},
				currentStageId: null,
				currentNodeId: null,
				recentActivities: appendRunActivity(base.recentActivities, event),
				modelStreams: {},
				toolActivities: [],
				debugEvents: [],
				currentRunId: event.run_id ?? null,
				runStatus: 'running',
				pendingInterrupt: null,
				helpVisible: false,
				logs: [...base.logs, 'run started']
			};
		case 'runtime_options_changed': {
			const options = (event.payload?.options ?? {}) as Record<string, unknown>;
			return {
				...base,
				stopAfterStage: (options.stop_after_stage as string | null | undefined) ?? base.stopAfterStage,
				showState: Boolean(options.show_state ?? base.showState),
				showMessages: Boolean(options.show_messages ?? base.showMessages),
				logs: [...base.logs, 'runtime options updated']
			};
		}
		case 'model_call_started':
			return upsertModelStream(
				{
					...base,
					recentActivities: appendRunActivity(base.recentActivities, event),
					logs: [...base.logs, `model started: ${event.node_id ?? '-'}`]
				},
				event,
				true
			);
		case 'model_stream_delta':
			return appendModelDelta(base, event);
		case 'model_message_completed':
			return completeModelStream({...base, recentActivities: appendRunActivity(base.recentActivities, event)}, event);
		case 'model_call_completed':
			return {
				...base,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `model completed: ${String(event.payload?.prompt_id ?? event.node_id ?? '-')}`]
			};
		case 'model_call_failed':
			return recordError(
				{
					...base,
					recentActivities: appendRunActivity(base.recentActivities, event),
					logs: [...base.logs, `model failed: ${String(event.payload?.prompt_id ?? event.node_id ?? '-')}`]
				},
				String(event.payload?.message ?? event.message ?? 'model failed')
			);
		case 'tool_call_proposed':
		case 'tool_call_started':
		case 'tool_call_completed':
		case 'tool_call_failed':
		case 'tool_observation_available':
			return appendToolTranscript({
				...base,
				recentActivities: appendRunActivity(base.recentActivities, event),
				toolActivities: upsertToolActivities(base.toolActivities, toolActivitiesForEvent(event))
			}, event);
		case 'tool_approval_resolved':
			return {
				...base,
				runStatus: 'running',
				pendingInterrupt: isToolApprovalInterrupt(base.pendingInterrupt) ? null : base.pendingInterrupt,
				recentActivities: appendRunActivity(base.recentActivities, event),
				toolActivities: applyToolApprovalResolution(base.toolActivities, event)
			};
		case 'debug_patch':
			return {...base, debugEvents: [...base.debugEvents.slice(-30), event]};
		case 'node_started':
			return {
				...updateNodeStatus(updateCurrentNode(base, event), event, 'running'),
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `node started: ${event.node_label ?? event.node_id ?? '-'}`]
			};
		case 'node_progress':
			return {
				...updateNodeStatus(updateCurrentNode(base, event), event, 'running'),
				recentActivities: appendRunActivity(base.recentActivities, event)
			};
		case 'node_completed':
			return {
				...updateNodeStatus(base, event, 'completed'),
				currentNodeId: event.node_id === base.currentNodeId ? null : base.currentNodeId,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `node completed: ${event.node_label ?? event.node_id ?? '-'}`]
			};
		case 'node_failed':
			return recordError(
				{...updateNodeStatus(base, event, 'failed'), runStatus: 'failed', recentActivities: appendRunActivity(base.recentActivities, event)},
				`node failed: ${event.node_label ?? event.node_id ?? '-'}`
			);
		case 'interrupt_requested':
			return appendInterruptTranscript({
				...base,
				runStatus: 'interrupted',
				pendingInterrupt: base.pendingInterrupt ?? event,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `interrupt: ${String(event.payload?.type ?? event.event_type)}`]
			}, event);
		case 'tool_approval_requested':
			return appendInterruptTranscript({
				...base,
				toolActivities: upsertToolActivities(base.toolActivities, toolActivitiesForEvent(event)),
				runStatus: 'interrupted',
				pendingInterrupt: event,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `interrupt: ${String(event.payload?.type ?? event.event_type)}`]
			}, event);
		case 'runtime_resumed':
			return {
				...base,
				runStatus: 'running',
				pendingInterrupt: null,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, 'runtime resumed']
			};
		case 'stage_started':
			return {
				...updateStageStatus(base, event, 'running'),
				currentStageId: event.stage_id ?? base.currentStageId,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `stage started: ${event.stage_id ?? '-'}`]
			};
		case 'stage_completed':
			return {
				...updateStageStatus(base, event, 'completed'),
				currentStageId: event.stage_id === base.currentStageId ? null : base.currentStageId,
				currentNodeId: event.stage_id === base.currentStageId ? null : base.currentNodeId,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `stage completed: ${event.stage_id ?? '-'}`]
			};
		case 'stage_failed':
			return recordError(
				{
					...updateStageStatus(base, event, 'failed'),
					runStatus: 'failed',
					recentActivities: appendRunActivity(base.recentActivities, event)
				},
				`stage failed: ${event.stage_id ?? '-'}`
			);
		case 'run_completed':
			return {
				...base,
				runStatus: 'completed',
				currentStageId: null,
				currentNodeId: null,
				pendingInterrupt: null,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `run completed: ${String(event.payload?.status ?? '-')}`]
			};
		case 'run_failed':
			return recordError(
				{...base, runStatus: 'failed', pendingInterrupt: null, recentActivities: appendRunActivity(base.recentActivities, event)},
				event.message ?? 'run failed'
			);
		case 'error':
			return recordError(base, event.message ?? 'unknown error');
		default:
			return base;
	}
}

function updateCurrentNode(state: RuntimeState, event: FactoryEvent): RuntimeState {
	return {
		...state,
		currentStageId: event.stage_id ?? state.currentStageId,
		currentNodeId: event.node_id ?? state.currentNodeId
	};
}

function updateNodeStatus(state: RuntimeState, event: FactoryEvent, status: StageLifecycle): RuntimeState {
	const nodeId = event.node_id;
	if (!nodeId) {
		return state;
	}
	const previous = state.nodeStatuses[nodeId];
	const next: NodeStatus = {
		nodeId,
		stageId: event.stage_id ?? previous?.stageId ?? null,
		status,
		label: event.node_label ?? previous?.label ?? null,
		kind: event.node_kind ?? previous?.kind ?? null,
		startedAt: status === 'running' ? event.timestamp : previous?.startedAt ?? null,
		completedAt: status === 'completed' ? event.timestamp : previous?.completedAt ?? null,
		failedAt: status === 'failed' ? event.timestamp : previous?.failedAt ?? null,
		message: event.message ?? previous?.message ?? null,
		payload: {...(previous?.payload ?? {}), ...(event.payload ?? {})}
	};
	return {
		...state,
		nodeStatuses: {
			...state.nodeStatuses,
			[nodeId]: next
		}
	};
}

function updateStageStatus(state: RuntimeState, event: FactoryEvent, status: StageLifecycle): RuntimeState {
	const stageId = event.stage_id;
	if (!stageId) {
		return state;
	}
	const previous = state.stageStatuses[stageId];
	const next: StageStatus = {
		stageId,
		status,
		nodeId: event.node_id ?? previous?.nodeId ?? null,
		startedAt: status === 'running' ? event.timestamp : previous?.startedAt ?? null,
		completedAt: status === 'completed' ? event.timestamp : previous?.completedAt ?? null,
		failedAt: status === 'failed' ? event.timestamp : previous?.failedAt ?? null,
		lastEventType: event.event_type,
		lastMessage: (event.message ?? stringValue(event.payload?.message)) || previous?.lastMessage || null
	};
	return {
		...state,
		stageStatuses: {
			...state.stageStatuses,
			[stageId]: next
		}
	};
}

function recordError(state: RuntimeState, message: string): RuntimeState {
	return {...state, lastError: message, errors: [...state.errors.slice(-8), message]};
}

function isToolApprovalInterrupt(event: FactoryEvent | null): boolean {
	return String(event?.payload?.type ?? event?.event_type ?? '') === 'tool_approval';
}

function recordEvent(state: RuntimeState, event: FactoryEvent): RuntimeState {
	return {...state, events: [...state.events.slice(-120), event]};
}

function recordSpan(state: RuntimeState, event: FactoryEvent): RuntimeState {
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

function upsertModelStream(state: RuntimeState, event: FactoryEvent, active: boolean): RuntimeState {
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

function appendModelDelta(state: RuntimeState, event: FactoryEvent): RuntimeState {
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
	const next = {
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
	return upsertAssistantTranscript(next, {
		streamId,
		timestamp: event.timestamp,
		content: next.modelStreams[streamId]?.content ?? '',
		active: true,
		nodeId: event.node_id ?? null,
		eventType: event.event_type
	});
}

function completeModelStream(state: RuntimeState, event: FactoryEvent): RuntimeState {
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
	const content = current.content || String(event.payload?.content ?? '');
	const next = {
		...state,
		modelStreams: {
			...state.modelStreams,
			[streamId]: {
				...current,
				content,
				active: false,
				completedAt: event.timestamp
			}
		}
	};
	return upsertAssistantTranscript(next, {
		streamId,
		timestamp: event.timestamp,
		content,
		active: false,
		nodeId: event.node_id ?? null,
		eventType: event.event_type
	});
}

function toolActivitiesForEvent(event: FactoryEvent): ToolActivity[] {
	const requests = event.event_type === 'tool_approval_requested' ? event.payload?.requests : null;
	if (Array.isArray(requests) && requests.length > 0) {
		return requests
			.filter((request): request is Record<string, unknown> => Boolean(request) && typeof request === 'object' && !Array.isArray(request))
			.map(request => toolActivity(event, {
				...event.payload,
				...request,
				arguments: request.args ?? request.arguments ?? {},
				type: 'tool_approval'
			}));
	}
	return [toolActivity(event)];
}

function toolActivity(event: FactoryEvent, payloadOverride?: Record<string, unknown>): ToolActivity {
	const payload = payloadOverride ?? event.payload ?? {};
	const normalizedPayload = normalizeToolPayload(payload);
	return {
		activityKey: toolActivityKey(event, payload),
		eventType: event.event_type,
		timestamp: event.timestamp,
		createdAt: event.timestamp,
		stageId: event.stage_id ?? null,
		nodeId: event.node_id ?? null,
		toolCallId: payloadToolCallId(payload) || null,
		toolName: normalizedPayload.toolName,
		status: lifecycleForToolEvent(event.event_type),
		approvalState: approvalState(payload),
		argsPreview: normalizedPayload.argsPreview,
		resultPreview: normalizedPayload.resultPreview,
		stdoutPreview: normalizedPayload.stdoutPreview,
		stderrPreview: normalizedPayload.stderrPreview,
		exitCode: normalizedPayload.exitCode,
		durationMs: normalizedPayload.durationMs,
		searchText: normalizedPayload.searchText,
		payload
	};
}

function upsertToolActivities(current: ToolActivity[], incoming: ToolActivity[]): ToolActivity[] {
	return incoming.reduce((items, item) => upsertToolActivity(items, item), current);
}

function upsertToolActivity(current: ToolActivity[], incoming: ToolActivity): ToolActivity[] {
	const existingIndex = current.findIndex(item => item.activityKey === incoming.activityKey);
	if (existingIndex < 0) {
		return [...current.slice(-40), incoming];
	}
	const existing = current[existingIndex];
	const merged = mergeToolActivity(existing, incoming);
	return [
		...current.slice(0, existingIndex),
		merged,
		...current.slice(existingIndex + 1)
	].slice(-40);
}

function applyToolApprovalResolution(current: ToolActivity[], event: FactoryEvent): ToolActivity[] {
	const payload = event.payload ?? {};
	const toolCallId = payloadToolCallId(payload);
	if (toolCallId) {
		return upsertToolActivities(current, [toolActivity(event)]);
	}
	const resolution = approvalState(payload);
	if (!resolution) {
		return current;
	}
	return current.map(item => {
		if (item.status !== 'approval' || item.approvalState !== 'pending') {
			return item;
		}
		return mergeToolActivity(item, toolActivity(event, {
			...payload,
			tool_call_id: item.toolCallId ?? undefined,
			tool_name: item.toolName,
			arguments: item.payload.arguments ?? item.payload.args ?? undefined
		}));
	});
}

function mergeToolActivity(existing: ToolActivity, incoming: ToolActivity): ToolActivity {
	const mergedPayload = {...existing.payload, ...incoming.payload};
	const normalizedPayload = normalizeToolPayload(mergedPayload);
	return {
		...incoming,
		createdAt: existing.createdAt,
		stageId: incoming.stageId ?? existing.stageId,
		nodeId: incoming.nodeId ?? existing.nodeId,
		toolCallId: incoming.toolCallId ?? existing.toolCallId,
		toolName: incoming.toolName === '-' ? existing.toolName : incoming.toolName,
		status: nextToolStatus(existing.status, incoming.status),
		approvalState: incoming.approvalState ?? existing.approvalState,
		argsPreview: incoming.argsPreview ?? existing.argsPreview ?? normalizedPayload.argsPreview,
		resultPreview: incoming.resultPreview ?? existing.resultPreview ?? normalizedPayload.resultPreview,
		stdoutPreview: incoming.stdoutPreview ?? existing.stdoutPreview ?? normalizedPayload.stdoutPreview,
		stderrPreview: incoming.stderrPreview ?? existing.stderrPreview ?? normalizedPayload.stderrPreview,
		exitCode: incoming.exitCode ?? existing.exitCode ?? normalizedPayload.exitCode,
		durationMs: incoming.durationMs ?? existing.durationMs ?? normalizedPayload.durationMs,
		searchText: [existing.searchText, incoming.searchText, normalizedPayload.searchText].filter(Boolean).join('\n'),
		payload: incoming.eventType === 'tool_observation_available' ? {...mergedPayload, observation: incoming.payload} : mergedPayload
	};
}

function toolActivityKey(event: FactoryEvent, payload: Record<string, unknown> = event.payload ?? {}): string {
	const toolCallId = payloadToolCallId(payload);
	if (toolCallId) {
		return `${event.run_id ?? '-'}:tool:${toolCallId}`;
	}
	return `${event.run_id ?? '-'}:${event.event_type}:${event.span_id ?? event.event_id}`;
}

function payloadToolCallId(payload: Record<string, unknown>): string {
	const direct = payload.tool_call_id;
	if (typeof direct === 'string' && direct) {
		return direct;
	}
	const message = payload.message as Record<string, unknown> | undefined;
	if (typeof message?.tool_call_id === 'string' && message.tool_call_id) {
		return message.tool_call_id;
	}
	const requests = payload.requests;
	if (Array.isArray(requests)) {
		const first = requests.find(item => item && typeof item === 'object' && !Array.isArray(item)) as Record<string, unknown> | undefined;
		if (typeof first?.tool_call_id === 'string' && first.tool_call_id) {
			return first.tool_call_id;
		}
	}
	const resourceCheck = payload.resource_check as Record<string, unknown> | undefined;
	const actionId = resourceCheck?.action_id;
	return typeof actionId === 'string' ? actionId : '';
}

function appendRunActivity(current: RunActivity[], event: FactoryEvent): RunActivity[] {
	const activity = runActivity(event);
	if (!activity) {
		return current;
	}
	return [...current.slice(-39), activity];
}

function runActivity(event: FactoryEvent): RunActivity | null {
	const payload = event.payload ?? {};
	const eventType = event.event_type;
	const toolPayload = normalizeToolPayload(payload);
	const node = event.node_id ?? event.stage_id ?? '-';
	if (eventType.startsWith('tool_')) {
		return {
			activityKey: `${event.event_id}:activity`,
			eventType,
			timestamp: event.timestamp,
			stageId: event.stage_id ?? null,
			nodeId: event.node_id ?? null,
			label: labelForToolLifecycle(lifecycleForToolEvent(eventType)),
			detail: `${toolPayload.toolName}${toolPayload.argsPreview ? ` ${toolPayload.argsPreview}` : ''}`,
			color: colorForEvent(eventType)
		};
	}
	if (eventType.startsWith('model_')) {
		return {
			activityKey: `${event.event_id}:activity`,
			eventType,
			timestamp: event.timestamp,
			stageId: event.stage_id ?? null,
			nodeId: event.node_id ?? null,
			label: eventType === 'model_call_started' ? 'model thinking' : eventType === 'model_message_completed' ? 'model answered' : 'model update',
			detail: String(payload.prompt_id ?? node),
			color: colorForEvent(eventType)
		};
	}
	if (eventType.startsWith('stage_') || eventType.startsWith('node_') || eventType.startsWith('run_') || eventType.includes('interrupt') || eventType.startsWith('runtime_')) {
		return {
			activityKey: `${event.event_id}:activity`,
			eventType,
			timestamp: event.timestamp,
			stageId: event.stage_id ?? null,
			nodeId: event.node_id ?? null,
			label: readableEventType(eventType),
			detail: event.message ?? String(payload.type ?? payload.status ?? event.node_label ?? node),
			color: colorForEvent(eventType)
		};
	}
	return null;
}

function lifecycleForToolEvent(eventType: FactoryEvent['event_type']): ToolLifecycle {
	if (eventType === 'tool_call_failed') {
		return 'failed';
	}
	if (eventType === 'tool_observation_available') {
		return 'observed';
	}
	if (eventType === 'tool_call_completed') {
		return 'completed';
	}
	if (eventType === 'tool_call_started') {
		return 'started';
	}
	if (eventType === 'tool_approval_requested' || eventType === 'tool_approval_resolved') {
		return 'approval';
	}
	return 'proposed';
}

function nextToolStatus(previous: ToolLifecycle, incoming: ToolLifecycle): ToolLifecycle {
	const rank: Record<ToolLifecycle, number> = {
		proposed: 1,
		approval: 2,
		started: 3,
		completed: 4,
		observed: 5,
		failed: 6
	};
	return rank[incoming] >= rank[previous] ? incoming : previous;
}

function labelForToolLifecycle(status: ToolLifecycle): string {
	const labels: Record<ToolLifecycle, string> = {
		proposed: 'tool proposed',
		approval: 'tool approval',
		started: 'tool running',
		completed: 'tool completed',
		failed: 'tool failed',
		observed: 'observation'
	};
	return labels[status];
}

function readableEventType(eventType: string): string {
	return eventType.replaceAll('_', ' ');
}

function colorForEvent(eventType: string): ActivityColor {
	if (eventType.endsWith('failed') || eventType === 'run_failed' || eventType === 'error') {
		return 'red';
	}
	if (eventType.includes('interrupt') || eventType.includes('approval')) {
		return 'yellow';
	}
	if (eventType.endsWith('completed')) {
		return 'green';
	}
	if (eventType.includes('model')) {
		return 'cyan';
	}
	if (eventType.includes('tool')) {
		return 'yellow';
	}
	return 'blue';
}

function approvalState(payload: Record<string, unknown>): ToolActivity['approvalState'] {
	const action = stringValue(payload.action);
	const approved = payload.approved;
	if (action === 'custom' || action === 'revise') {
		return 'custom';
	}
	if (action === 'trust_tool' || action === 'trust' || payload.trust_tool || payload.trust_scope === 'tool') {
		return 'trusted';
	}
	if (approved === true || action === 'approve') {
		return 'approved';
	}
	if (approved === false || action === 'deny' || action === 'reject') {
		return 'rejected';
	}
	if (payload.type === 'tool_approval' || payload.approval_request) {
		return 'pending';
	}
	return null;
}

function normalizeToolPayload(payload: Record<string, unknown>): {
	toolName: string;
	argsPreview: string | null;
	resultPreview: string | null;
	stdoutPreview: string | null;
	stderrPreview: string | null;
	exitCode: number | null;
	durationMs: number | null;
	searchText: string;
} {
	const message = recordValue(payload.message);
	const resourceCheck = recordValue(payload.resource_check);
	const rawResult = payload.result ?? payload.output ?? payload.content ?? message?.content ?? resourceCheck?.raw_result ?? resourceCheck?.result_summary;
	const result = parseJsonLike(rawResult);
	const resultRecord = recordValue(result);
	const observation = recordValue(resultRecord?.type === 'tool_observation' ? resultRecord : resultRecord?.observation);
	const outputRecord = recordValue(observation?.output) ?? resultRecord;
	const args = payload.arguments ?? payload.args ?? payload.tool_args ?? observation?.arguments ?? resourceCheck?.arguments ?? message?.args;
	const toolName = stringValue(payload.tool_name) || stringValue(payload.name) || stringValue(observation?.tool_id) || stringValue(message?.name) || stringValue(resourceCheck?.tool_name) || '-';
	const stdoutPreview = textPreview(outputRecord?.stdout ?? outputRecord?.out);
	const stderrPreview = textPreview(outputRecord?.stderr ?? outputRecord?.err);
	const resultPreview = textPreview(
		resourceCheck?.result_summary
		?? observation?.message
		?? outputRecord?.result_summary
		?? outputSummary(outputRecord)
		?? rawResult
	);
	const exitCode = numberValue(outputRecord?.exit_code ?? outputRecord?.returncode ?? payload.exit_code);
	const durationMs = numberValue(payload.duration_ms ?? outputRecord?.duration_ms);
	const argsPreview = args === undefined ? null : compactValue(args, 360);
	return {
		toolName,
		argsPreview,
		resultPreview,
		stdoutPreview,
		stderrPreview,
		exitCode,
		durationMs,
		searchText: [toolName, argsPreview, resultPreview, stdoutPreview, stderrPreview, compactValue(payload, 800)].filter(Boolean).join('\n')
	};
}

function parseJsonLike(value: unknown): unknown {
	if (typeof value !== 'string') {
		return value;
	}
	const trimmed = value.trim();
	if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) {
		return value;
	}
	try {
		return JSON.parse(trimmed);
	} catch {
		return value;
	}
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
	return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function numberValue(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function textPreview(value: unknown, limit = 900): string | null {
	if (value === undefined || value === null) {
		return null;
	}
	const raw = typeof value === 'string' ? value : compactValue(value, limit);
	const normalized = raw.replace(/\r/g, '').trim();
	if (!normalized) {
		return null;
	}
	return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

function compactValue(value: unknown, limit = 360): string {
	try {
		return JSON.stringify(value).replace(/\s+/g, ' ').slice(0, limit);
	} catch {
		return String(value).replace(/\s+/g, ' ').slice(0, limit);
	}
}

export function setToolGrep(state: RuntimeState, query: string): RuntimeState {
	return {...state, toolGrep: query};
}

function isImmediateEvent(eventType: FactoryEvent['event_type']): boolean {
	return [
		'run_failed',
		'interrupt_requested',
		'tool_approval_requested',
		'model_message_completed',
		'runtime_resumed',
		'run_completed',
		'error'
	].includes(eventType);
}

function appendTranscript(state: RuntimeState, item: TranscriptItem): RuntimeState {
	return {...state, transcript: [...state.transcript.slice(-199), item]};
}

function upsertAssistantTranscript(
	state: RuntimeState,
	{
		streamId,
		timestamp,
		content,
		active,
		nodeId,
		eventType
	}: {
		streamId: string;
		timestamp: string;
		content: string;
		active: boolean;
		nodeId: string | null;
		eventType: FactoryEvent['event_type'];
	}
): RuntimeState {
	if (!content) {
		return state;
	}
	const item: TranscriptItem = {
		id: `assistant-${streamId}`,
		role: 'assistant',
		timestamp,
		title: nodeId ? `Assistant / ${nodeId}` : 'Assistant',
		content,
		eventType,
		streamId,
		active,
		metadata: {node_id: nodeId}
	};
	const existingIndex = state.transcript.findIndex(entry => entry.id === item.id);
	if (existingIndex < 0) {
		return appendTranscript(state, item);
	}
	return {
		...state,
		transcript: [
			...state.transcript.slice(0, existingIndex),
			item,
			...state.transcript.slice(existingIndex + 1)
		]
	};
}

function appendToolTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	return event.event_type === 'tool_call_failed'
		? appendTranscript(state, {
			id: `tool-error-${event.event_id}`,
			role: 'tool',
			timestamp: event.timestamp,
			title: 'Tool Failed',
			content: normalizeToolPayload(event.payload ?? {}).resultPreview ?? compactValue(event.payload, 1000),
			eventType: event.event_type,
			metadata: event.payload ?? {}
		})
		: state;
}

function appendInterruptTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	const payload = event.payload ?? {};
	const interruptType = String(payload.type ?? event.event_type);
	if (interruptType === 'tool_approval') {
		return state;
	}
	const requests = (payload.requests as Array<Record<string, unknown>> | undefined) ?? [];
	const requestLines = requests.map((item, index) => {
		const tool = String(item.tool_name ?? '-');
		const summary = String(item.summary ?? compactValue(item.args ?? item.arguments ?? {}, 360));
		return `${index + 1}. ${tool} ${summary}`.trim();
	});
	const content = requestLines.length ? requestLines.join('\n') : compactValue(payload, 1200);
	return appendTranscript(state, {
		id: `interrupt-${event.event_id}`,
		role: 'interrupt',
		timestamp: event.timestamp,
		title: `Interrupt / ${interruptType}`,
		content,
		eventType: event.event_type,
		metadata: payload
	});
}

function transcriptFromSession(session: Record<string, unknown>, mode: FactoryMode | null): TranscriptItem[] {
	const snapshot = recordValue(session.snapshot);
	const snapshotMessages = Array.isArray(snapshot?.messages) ? snapshot.messages : null;
	const modeMessages = mode === 'create_agent' ? session.create_agent_messages : mode === 'chat' ? session.chat_messages : null;
	const messages = snapshotMessages ?? (Array.isArray(modeMessages) ? modeMessages : []);
	return messages
		.map((message, index) => transcriptItemFromMessage(message, index))
		.filter((item): item is TranscriptItem => Boolean(item));
}

function transcriptItemFromMessage(message: unknown, index: number): TranscriptItem | null {
	const record = recordValue(message);
	if (!record) {
		return null;
	}
	const role = stringValue(record.role) || roleFromMessageType(stringValue(record.type));
	const rawContent = contentToText(record.content);
	const normalizedRole: TranscriptRole = role === 'assistant' ? 'assistant' : role === 'tool' ? 'tool' : role === 'user' || role === 'human' ? 'user' : 'system';
	const content = normalizedRole === 'tool' ? toolMessageContent(record, rawContent) : rawContent;
	if (!content) {
		return null;
	}
	return {
		id: `session-message-${index}`,
		role: normalizedRole,
		timestamp: stringValue(record.created_at) || new Date(0).toISOString(),
		title: normalizedRole === 'user' ? 'You' : normalizedRole === 'assistant' ? 'Assistant' : normalizedRole === 'tool' ? `Tool / ${stringValue(record.name) || '-'}` : 'System',
		content,
		metadata: record
	};
}

function toolMessageContent(record: Record<string, unknown>, rawContent: string): string {
	const parsed = parseJsonLike(rawContent);
	const parsedRecord = recordValue(parsed);
	const observation = recordValue(parsedRecord?.type === 'tool_observation' ? parsedRecord : parsedRecord?.observation);
	const output = recordValue(observation?.output ?? parsedRecord?.output);
	const lines = [
		stringValue(observation?.status) ? `status: ${stringValue(observation?.status)}` : '',
		stringValue(observation?.message) ? `message: ${stringValue(observation?.message)}` : '',
		outputSummary(output) ? `output: ${outputSummary(output)}` : '',
		textPreview(output?.stdout, 360) ? `stdout: ${textPreview(output?.stdout, 360)}` : '',
		textPreview(output?.stderr, 360) ? `stderr: ${textPreview(output?.stderr, 360)}` : ''
	].filter(Boolean);
	if (lines.length) {
		return lines.join('\n');
	}
	const toolName = stringValue(record.name);
	if (rawContent.trim().startsWith('{') || rawContent.trim().startsWith('[')) {
		return toolName ? `structured observation from ${toolName}` : 'structured tool observation';
	}
	return rawContent;
}

function roleFromMessageType(type: string): string {
	if (type === 'HumanMessage') {
		return 'user';
	}
	if (type === 'AIMessage') {
		return 'assistant';
	}
	if (type === 'ToolMessage') {
		return 'tool';
	}
	return type || 'system';
}

function contentToText(value: unknown): string {
	if (typeof value === 'string') {
		return value;
	}
	if (Array.isArray(value)) {
		return value.map(item => {
			if (typeof item === 'string') {
				return item;
			}
			const record = recordValue(item);
			return stringValue(record?.text) || stringValue(record?.content);
		}).join('');
	}
	return value === undefined || value === null ? '' : String(value);
}

function outputSummary(value: Record<string, unknown> | undefined): string | null {
	if (!value) {
		return null;
	}
	const keys = ['status', 'path', 'process_id', 'exit_code', 'created', 'bytes_written', 'replacements'];
	const parts = keys
		.filter(key => value[key] !== undefined && value[key] !== null)
		.map(key => `${key}=${String(value[key])}`);
	return parts.length ? parts.join(' ') : null;
}

function sessionTitle(session: Record<string, unknown>): string | null {
	const displayTitle = stringValue(session.display_title);
	const firstUserInput = stringValue(session.first_user_input);
	return displayTitle || firstUserInput || null;
}

function stringValue(value: unknown): string {
	return typeof value === 'string' ? value.trim() : '';
}

function streamIdOf(event: FactoryEvent): string | null {
	const streamId = event.payload?.stream_id;
	return typeof streamId === 'string' && streamId ? streamId : null;
}
