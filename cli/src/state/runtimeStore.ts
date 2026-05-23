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

export type ActivityColor = 'gray' | 'blue' | 'cyan' | 'green' | 'yellow' | 'red' | 'magenta';

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

export type MemoryActivityStatus = 'idle' | 'writing' | 'completed' | 'failed';

export type MemoryActivity = {
	status: MemoryActivityStatus;
	label: string;
	detail: string | null;
	jobId: string | null;
	namespace: string | null;
	updatedAt: string | null;
};

export type ContextActivityStatus = 'idle' | 'running' | 'completed' | 'failed';

export type ContextActivity = {
	status: ContextActivityStatus;
	label: string;
	detail: string | null;
	nodeId: string | null;
	updatedAt: string | null;
};

export type ContextWindow = {
	tokenCount: number | null;
	contextWindowTokens: number | null;
	compressionThresholdTokens: number | null;
	tokenCountMethod: string | null;
	source: string | null;
	error: string | null;
	updatedAt: string | null;
};

export type SchedulerActivity = {
	eventType: FactoryEvent['event_type'];
	timestamp: string;
	jobId: string | null;
	runId: string | null;
	targetType: string | null;
	status: string | null;
	detail: string;
	reportPath: string | null;
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

export type TranscriptRole = 'user' | 'assistant' | 'tool' | 'interrupt' | 'scheduler' | 'system';

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

export type TimelineItem = {
	id: string;
	timestamp: string;
	order: number;
	color: ActivityColor | 'white';
	title: string;
	body: string;
	active?: boolean;
};

export type RuntimeState = {
	ready: boolean;
	mode: FactoryMode | null;
	sessionId: string | null;
	sessionTitle: string | null;
	sessions: Array<Record<string, unknown>>;
	sessionPickerOpen: boolean;
	agentPackages: Array<Record<string, unknown>>;
	agentPackagePickerOpen: boolean;
	activeAgentPackage: Record<string, unknown> | null;
	agentPackageSessions: Array<Record<string, unknown>>;
	agentSessionPickerOpen: boolean;
	activeAgentSessionId: string | null;
	logs: string[];
	transcript: TranscriptItem[];
	timelineItems: TimelineItem[];
	events: Array<FactoryEvent>;
	spans: Record<string, SpanRecord>;
	stageStatuses: Record<string, StageStatus>;
	nodeStatuses: Record<string, NodeStatus>;
	currentStageId: string | null;
	currentNodeId: string | null;
	recentActivities: RunActivity[];
	modelStreams: Record<string, ModelStream>;
	toolActivities: ToolActivity[];
	memoryActivity: MemoryActivity;
	contextActivity: ContextActivity;
	contextWindow: ContextWindow;
	schedulerActivities: SchedulerActivity[];
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
	| {ui_type: 'set_agent_package_picker_open'; open: boolean}
	| {ui_type: 'set_agent_session_picker_open'; open: boolean}
	| {ui_type: 'select_agent_session'; sessionId: string | null}
	| {ui_type: 'clear_agent_package_selection'}
	| {ui_type: 'local_user_message'; message: string}
	| {ui_type: 'interrupt_response_submitted'; message: string}
	| {ui_type: 'clear_memory_activity'; updatedAt: string | null}
	| {ui_type: 'clear_context_activity'; updatedAt: string | null}
	| {ui_type: 'show_help'}
	| {ui_type: 'notice'; message: string};

const STREAM_FLUSH_MS = 33;
const ACTIVE_MEMORY_HINT_MS = 8000;
const TERMINAL_MEMORY_HINT_MS = 3000;
const ACTIVE_CONTEXT_HINT_MS = 5000;
const TERMINAL_CONTEXT_HINT_MS = 2500;

export function createInitialRuntimeState(): RuntimeState {
	return {
		ready: false,
		mode: null,
		sessionId: null,
		sessionTitle: null,
		sessions: [],
		sessionPickerOpen: false,
		agentPackages: [],
		agentPackagePickerOpen: false,
		activeAgentPackage: null,
		agentPackageSessions: [],
		agentSessionPickerOpen: false,
		activeAgentSessionId: null,
		logs: [],
		transcript: [],
		timelineItems: [],
		events: [],
		spans: {},
		stageStatuses: {},
		nodeStatuses: {},
		currentStageId: null,
		currentNodeId: null,
		recentActivities: [],
		modelStreams: {},
		toolActivities: [],
		memoryActivity: idleMemoryActivity(),
		contextActivity: idleContextActivity(),
		contextWindow: emptyContextWindow(),
		schedulerActivities: [],
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
	private memoryActivityTimer: ReturnType<typeof setTimeout> | null = null;
	private contextActivityTimer: ReturnType<typeof setTimeout> | null = null;

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
		this.state = withTimelineItems(reduceRuntimeAction(this.state, action));
		if ('event_type' in action && isMemoryWriteEvent(action.event_type)) {
			this.scheduleMemoryActivityClear(
				this.state.memoryActivity.updatedAt,
				isTerminalMemoryEvent(action.event_type) ? TERMINAL_MEMORY_HINT_MS : ACTIVE_MEMORY_HINT_MS
			);
		}
		if ('event_type' in action && isContextEvent(action.event_type)) {
			this.scheduleContextActivityClear(
				this.state.contextActivity.updatedAt,
				isTerminalContextEvent(action.event_type) ? TERMINAL_CONTEXT_HINT_MS : ACTIVE_CONTEXT_HINT_MS
			);
		}
		this.notify();
	};

	destroy(): void {
		if (this.streamTimer) {
			clearTimeout(this.streamTimer);
			this.streamTimer = null;
		}
		if (this.memoryActivityTimer) {
			clearTimeout(this.memoryActivityTimer);
			this.memoryActivityTimer = null;
		}
		if (this.contextActivityTimer) {
			clearTimeout(this.contextActivityTimer);
			this.contextActivityTimer = null;
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
		this.state = withTimelineItems(next);
		this.notify();
	}

	private notify(): void {
		for (const listener of this.listeners) {
			listener();
		}
	}

	private scheduleMemoryActivityClear(updatedAt: string | null, delayMs: number): void {
		if (this.memoryActivityTimer) {
			clearTimeout(this.memoryActivityTimer);
		}
		this.memoryActivityTimer = setTimeout(() => {
			this.memoryActivityTimer = null;
			this.dispatch({ui_type: 'clear_memory_activity', updatedAt});
		}, delayMs);
	}

	private scheduleContextActivityClear(updatedAt: string | null, delayMs: number): void {
		if (this.contextActivityTimer) {
			clearTimeout(this.contextActivityTimer);
		}
		this.contextActivityTimer = setTimeout(() => {
			this.contextActivityTimer = null;
			this.dispatch({ui_type: 'clear_context_activity', updatedAt});
		}, delayMs);
	}
}

export function createRuntimeStore(): RuntimeStore {
	return new RuntimeStore();
}

function withTimelineItems(state: RuntimeState): RuntimeState {
	const timelineItems = buildTimelineItems(state);
	if (timelineItemsEqual(state.timelineItems, timelineItems)) {
		return state;
	}
	return {...state, timelineItems};
}

function buildTimelineItems(state: RuntimeState): TimelineItem[] {
	const transcriptItems = state.transcript
		.filter(item => item.role !== 'tool')
		.map((item, index) => transcriptTimelineItem(item, index));
	const toolItems = state.toolActivities.slice(-30).map((item, index) => toolTimelineItem(item, index));
	const schedulerItems = state.schedulerActivities
		.filter(item => !['scheduler_feedback_completed', 'scheduler_feedback_failed'].includes(item.eventType))
		.slice(-16)
		.map((item, index) => schedulerTimelineItem(item, index));
	const activityItems = state.mode === 'create_agent'
		? state.recentActivities
			.filter(item => !item.eventType.startsWith('tool_') && !item.eventType.startsWith('scheduler_'))
			.slice(-18)
			.map((item, index) => ({
				id: `activity:${item.activityKey}`,
				timestamp: item.timestamp,
				order: 40_000 + index,
				color: item.color,
				title: item.label,
				body: [item.stageId, item.nodeId, item.detail].filter(Boolean).join('  ')
			}))
		: [];
	const errorItems = state.errors.slice(-3).map((message, index) => ({
		id: `error:${index}:${message}`,
		timestamp: '',
		order: 90_000 + index,
		color: 'red' as const,
		title: 'Runtime error',
		body: message
	}));
	return [...transcriptItems, ...toolItems, ...schedulerItems, ...activityItems, ...errorItems]
		.sort((left, right) => compareTimelineItems(left, right));
}

function timelineItemsEqual(left: TimelineItem[], right: TimelineItem[]): boolean {
	if (left === right) {
		return true;
	}
	if (left.length !== right.length) {
		return false;
	}
	return left.every((item, index) => {
		const other = right[index];
		return Boolean(other)
			&& item.id === other.id
			&& item.timestamp === other.timestamp
			&& item.order === other.order
			&& item.color === other.color
			&& item.title === other.title
			&& item.body === other.body
			&& item.active === other.active;
	});
}

function transcriptTimelineItem(item: TranscriptItem, index: number): TimelineItem {
	return {
		id: `message:${item.id}`,
		timestamp: item.timestamp,
		order: index,
		color: colorForTranscriptRole(item.role),
		title: titleForTranscript(item),
		body: item.content,
		active: item.active
	};
}

function toolTimelineItem(item: ToolActivity, index: number): TimelineItem {
	return {
		id: `tool:${item.activityKey}`,
		timestamp: item.timestamp,
		order: 20_000 + index,
		color: colorForToolStatus(item.status),
		title: `Tool ${toolStatusLabel(item.status)} ${item.toolName}`,
		body: toolTimelineBody(item)
	};
}

function schedulerTimelineItem(item: SchedulerActivity, index: number): TimelineItem {
	return {
		id: `scheduler:${item.timestamp}:${item.eventType}:${item.jobId ?? index}`,
		timestamp: item.timestamp,
		order: 30_000 + index,
		color: colorForSchedulerStatus(item.status),
		title: `Scheduler ${item.eventType.replaceAll('_', ' ')}`,
		body: [
			item.jobId ? `job ${shortTimelineValue(item.jobId, 16)}` : null,
			item.runId ? `run ${shortTimelineValue(item.runId, 16)}` : null,
			item.targetType ? `target ${item.targetType}` : null,
			item.status ? `status ${item.status}` : null,
			item.detail || null,
			item.reportPath ? `report ${item.reportPath}` : null
		].filter((value): value is string => Boolean(value)).join('\n')
	};
}

function toolTimelineBody(item: ToolActivity): string {
	const lines = [
		item.toolCallId ? `call ${shortTimelineValue(item.toolCallId, 18)}` : null,
		item.stageId || item.nodeId ? `node ${[item.stageId, item.nodeId].filter(Boolean).join(' / ')}` : null,
		item.approvalState ? `approval ${item.approvalState}` : null,
		item.exitCode !== null ? `exit ${item.exitCode}` : null,
		item.durationMs !== null ? `duration ${item.durationMs}ms` : null,
		item.argsPreview ? `args ${item.argsPreview}` : null,
		item.stdoutPreview ? `stdout ${previewTimelineMultiline(item.stdoutPreview)}` : null,
		item.stderrPreview ? `stderr ${previewTimelineMultiline(item.stderrPreview)}` : null,
		item.resultPreview ? `result ${previewTimelineMultiline(item.resultPreview)}` : null
	];
	return lines.filter((line): line is string => Boolean(line)).join('\n');
}

function compareTimelineItems(left: TimelineItem, right: TimelineItem): number {
	const leftTime = Date.parse(left.timestamp);
	const rightTime = Date.parse(right.timestamp);
	const timeDelta = (Number.isNaN(leftTime) ? 0 : leftTime) - (Number.isNaN(rightTime) ? 0 : rightTime);
	return timeDelta || left.order - right.order;
}

function titleForTranscript(item: TranscriptItem): string {
	if (item.role === 'user') {
		return 'You';
	}
	if (item.role === 'assistant') {
		return item.title.replace(/^Assistant \/ /, 'Assistant ');
	}
	if (item.role === 'scheduler') {
		return item.title.replace(/^Scheduler \/ /, 'Scheduler ');
	}
	if (item.role === 'interrupt') {
		return item.title.replace(/^Interrupt \/ /, 'Interrupt ');
	}
	return item.title;
}

function colorForTranscriptRole(role: string): ActivityColor | 'white' {
	if (role === 'user') {
		return 'cyan';
	}
	if (role === 'assistant') {
		return 'green';
	}
	if (role === 'scheduler') {
		return 'magenta';
	}
	if (role === 'interrupt') {
		return 'yellow';
	}
	if (role === 'system') {
		return 'gray';
	}
	return 'white';
}

function colorForToolStatus(status: string): ActivityColor {
	if (status === 'failed') {
		return 'red';
	}
	if (status === 'completed' || status === 'observed') {
		return 'green';
	}
	if (status === 'started') {
		return 'cyan';
	}
	return 'yellow';
}

function colorForSchedulerStatus(status: string | null): ActivityColor {
	if (status === 'failed' || status === 'cancelled') {
		return 'red';
	}
	if (status === 'completed') {
		return 'green';
	}
	if (status === 'running') {
		return 'cyan';
	}
	if (status === 'skipped') {
		return 'yellow';
	}
	return 'magenta';
}

function toolStatusLabel(status: string): string {
	return status === 'started' ? 'running' : status;
}

function previewTimelineMultiline(value: string): string {
	const normalized = value.replace(/\r/g, '').trim();
	const lines = normalized.split('\n');
	if (lines.length <= 6) {
		return trimTimelineContent(normalized);
	}
	return `${lines.slice(0, 6).join('\n')}\n... ${lines.length - 6} more lines`;
}

function trimTimelineContent(value: string): string {
	const limit = 3600;
	return value.length > limit ? `...${value.slice(value.length - limit)}` : value;
}

function shortTimelineValue(value: string, limit: number): string {
	return value.length > limit ? `${value.slice(0, Math.max(1, limit - 3))}...` : value;
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
	if (action.ui_type === 'set_agent_package_picker_open') {
		return {...state, agentPackagePickerOpen: action.open};
	}
	if (action.ui_type === 'set_agent_session_picker_open') {
		return {...state, agentSessionPickerOpen: action.open};
	}
	if (action.ui_type === 'select_agent_session') {
		return {...state, activeAgentSessionId: action.sessionId, agentSessionPickerOpen: false};
	}
	if (action.ui_type === 'clear_agent_package_selection') {
		return {
			...state,
			mode: null,
			activeAgentPackage: null,
			agentPackageSessions: [],
			activeAgentSessionId: null,
			agentPackagePickerOpen: false,
			agentSessionPickerOpen: false
		};
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
	if (action.ui_type === 'clear_memory_activity') {
		return state.memoryActivity.updatedAt === action.updatedAt ? {...state, memoryActivity: idleMemoryActivity()} : state;
	}
	if (action.ui_type === 'clear_context_activity') {
		return state.contextActivity.updatedAt === action.updatedAt ? {...state, contextActivity: idleContextActivity()} : state;
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
		case 'agent_packages_listed':
			return {
				...base,
				agentPackages: (event.payload?.packages as Array<Record<string, unknown>>) ?? [],
				logs: [...base.logs, 'agent packages listed']
			};
		case 'agent_package_selected': {
			const selectedPackage = (event.payload?.package ?? null) as Record<string, unknown> | null;
			const sessions = (event.payload?.sessions as Array<Record<string, unknown>>) ?? [];
			return {
				...base,
				mode: 'agent_package',
				activeAgentPackage: selectedPackage,
				agentPackageSessions: sessions,
				activeAgentSessionId: null,
				agentPackagePickerOpen: false,
				agentSessionPickerOpen: true,
				helpVisible: false,
				logs: [...base.logs, `agent package selected: ${String(selectedPackage?.package_id ?? '-')}`]
			};
		}
		case 'agent_package_deleted':
			return {
				...base,
				agentPackages: (event.payload?.packages as Array<Record<string, unknown>>) ?? base.agentPackages,
				activeAgentPackage: String(base.activeAgentPackage?.package_id ?? '') === String(event.payload?.package_id ?? '') ? null : base.activeAgentPackage,
				activeAgentSessionId: String(base.activeAgentPackage?.package_id ?? '') === String(event.payload?.package_id ?? '') ? null : base.activeAgentSessionId,
				logs: [...base.logs, `agent package deleted: ${String(event.payload?.package_id ?? '-')}`]
			};
		case 'agent_package_sessions_listed':
			return {
				...base,
				agentPackageSessions: (event.payload?.sessions as Array<Record<string, unknown>>) ?? [],
				agentSessionPickerOpen: true,
				logs: [...base.logs, 'agent package sessions listed']
			};
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
				contextWindow: emptyContextWindow(),
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
				errorMessageFromEvent(event, 'model failed')
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
		case 'memory_write_queued':
		case 'memory_write_queued_failed':
		case 'memory_segment_prepared':
		case 'memory_extraction_completed':
		case 'memory_write_completed':
		case 'memory_write_failed':
			return {...base, memoryActivity: memoryActivityForEvent(event)};
		case 'context_compression_started':
		case 'context_compression_completed':
		case 'context_compression_failed':
		case 'context_retrieval_completed':
		case 'context_assembly_completed':
		case 'context_injection_completed':
			return {
				...base,
				contextActivity: contextActivityForEvent(event),
				recentActivities: appendRunActivity(base.recentActivities, event)
			};
		case 'context_window_updated':
			return {
				...base,
				contextWindow: contextWindowForEvent(event),
				recentActivities: appendRunActivity(base.recentActivities, event)
			};
		case 'scheduler_job_created':
		case 'scheduler_job_updated':
		case 'scheduler_job_deleted':
		case 'scheduler_job_auto_paused':
		case 'scheduler_jobs_listed':
		case 'scheduler_job_described':
		case 'scheduler_runs_listed':
		case 'scheduler_run_scheduled':
		case 'scheduler_run_started':
		case 'scheduler_run_completed':
		case 'scheduler_run_failed':
		case 'scheduler_run_skipped':
		case 'scheduler_run_cancelled':
		case 'scheduler_feedback_completed':
		case 'scheduler_feedback_failed':
			return {
				...appendSchedulerTranscript(base, event),
				schedulerActivities: [...base.schedulerActivities.slice(-19), schedulerActivityForEvent(event)],
				recentActivities: appendRunActivity(base.recentActivities, event)
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
				errorMessageFromEvent(event, `node failed: ${event.node_label ?? event.node_id ?? '-'}`)
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
				errorMessageFromEvent(event, `stage failed: ${event.stage_id ?? '-'}`)
			);
		case 'run_completed':
			return {
				...base,
				runStatus: 'completed',
				currentStageId: null,
				currentNodeId: null,
				pendingInterrupt: null,
				recentActivities: appendRunActivity(base.recentActivities, event),
				activeAgentSessionId: agentSessionIdFromEvent(event) ?? base.activeAgentSessionId,
				logs: [...base.logs, `run completed: ${String(event.payload?.status ?? '-')}`]
			};
		case 'run_failed':
			return recordError(
				{...base, runStatus: 'failed', pendingInterrupt: null, recentActivities: appendRunActivity(base.recentActivities, event)},
				errorMessageFromEvent(event, 'run failed')
			);
		case 'error':
			return recordError(base, errorMessageFromEvent(event, 'unknown error'));
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

function errorMessageFromEvent(event: FactoryEvent, fallback: string): string {
	const payload = recordValue(event.payload) ?? {};
	const lines = [
		primaryErrorMessage(event, payload, fallback),
		labeledValue('where', payload.where),
		labeledValue('why', payload.why),
		labeledValue('error_type', payload.error_type ?? payload.errorType),
		labeledValue('suggested_action', payload.suggested_action ?? payload.suggestedAction),
		errorListSummary(payload.errors),
		labeledValue('evidence', payload.evidence)
	].filter((line): line is string => Boolean(line));
	const unique: string[] = [];
	for (const line of lines) {
		if (!unique.includes(line)) {
			unique.push(line);
		}
	}
	return unique.join('\n');
}

function primaryErrorMessage(event: FactoryEvent, payload: Record<string, unknown>, fallback: string): string {
	const payloadMessage = stringValue(payload.message) || stringValue(payload.error) || stringValue(payload.error_message);
	if (payloadMessage) {
		return payloadMessage;
	}
	if (event.message && !isGenericFailureText(event.message)) {
		return event.message;
	}
	return fallback;
}

function labeledValue(label: string, value: unknown): string | null {
	const text = typeof value === 'string' ? value.trim() : value === undefined || value === null ? '' : compactValue(value, 900);
	return text ? `${label}: ${text}` : null;
}

function errorListSummary(value: unknown): string | null {
	if (!Array.isArray(value) || value.length === 0) {
		return null;
	}
	const items = value
		.slice(0, 3)
		.map(item => {
			const record = recordValue(item);
			if (!record) {
				return compactValue(item, 300);
			}
			const parts = [
				stringValue(record.where),
				stringValue(record.why),
				stringValue(record.message) || stringValue(record.error)
			].filter(Boolean);
			return parts.length ? parts.join(' / ') : compactValue(record, 300);
		});
	const suffix = value.length > items.length ? `; +${value.length - items.length} more` : '';
	return `errors: ${items.join('; ')}${suffix}`;
}

function isGenericFailureText(value: string): boolean {
	const normalized = value.trim().toLowerCase();
	return ['failed', 'run failed', 'error', 'unknown error'].includes(normalized);
}

function firstLine(value: string): string {
	return value.split('\n').find(line => line.trim())?.trim() ?? value;
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
	if (eventType.startsWith('scheduler_')) {
		return {
			activityKey: `${event.event_id}:activity`,
			eventType,
			timestamp: event.timestamp,
			stageId: event.stage_id ?? null,
			nodeId: event.node_id ?? null,
			label: readableEventType(eventType),
			detail: schedulerActivityDetail(event.payload ?? {}),
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
			detail: eventType.endsWith('failed') || eventType === 'run_failed'
				? firstLine(errorMessageFromEvent(event, readableEventType(eventType)))
				: event.message ?? String(payload.type ?? payload.status ?? event.node_label ?? node),
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
	if (eventType.includes('scheduler')) {
		return 'magenta';
	}
	return 'blue';
}

function schedulerActivityForEvent(event: FactoryEvent): SchedulerActivity {
	const payload = event.payload ?? {};
	return {
		eventType: event.event_type,
		timestamp: event.timestamp,
		jobId: stringValue(payload.job_id) || null,
		runId: stringValue(payload.run_id) || null,
		targetType: stringValue(payload.target_type) || null,
		status: stringValue(payload.status) || null,
		detail: schedulerActivityDetail(payload),
		reportPath: stringValue(payload.report_path) || null
	};
}

function schedulerActivityDetail(payload: Record<string, unknown>): string {
	const target = stringValue(payload.target_type);
	const status = stringValue(payload.status);
	const job = stringValue(payload.job_id);
	const error = stringValue(payload.error_summary);
	const report = stringValue(payload.report_path);
	const summary = stringValue(payload.summary);
	const completedCount = numberValue(payload.completed_count);
	const nested = recordValue(payload.payload) ?? {};
	const listedCount = numberValue(nested.count);
	const consecutiveFailures = numberValue(nested.consecutive_failures);
	const threshold = numberValue(nested.threshold);
	const parts = [
		status ? `status=${status}` : null,
		target ? `target=${target}` : null,
		job ? `job=${shortValue(job, 10)}` : null,
		typeof listedCount === 'number' ? `items=${listedCount}` : null,
		typeof completedCount === 'number' ? `count=${completedCount}` : null,
		typeof consecutiveFailures === 'number' ? `failures=${consecutiveFailures}` : null,
		typeof threshold === 'number' ? `threshold=${threshold}` : null,
		summary ? `summary=${shortValue(summary, 80)}` : null,
		error ? `error=${shortValue(error, 80)}` : null,
		report ? `report=${shortValue(report, 48)}` : null
	].filter((item): item is string => Boolean(item));
	return parts.join(' ');
}

function idleMemoryActivity(): MemoryActivity {
	return {
		status: 'idle',
		label: '',
		detail: null,
		jobId: null,
		namespace: null,
		updatedAt: null
	};
}

function idleContextActivity(): ContextActivity {
	return {
		status: 'idle',
		label: '',
		detail: null,
		nodeId: null,
		updatedAt: null
	};
}

function emptyContextWindow(): ContextWindow {
	return {
		tokenCount: null,
		contextWindowTokens: null,
		compressionThresholdTokens: null,
		tokenCountMethod: null,
		source: null,
		error: null,
		updatedAt: null
	};
}

function memoryActivityForEvent(event: FactoryEvent): MemoryActivity {
	const payload = event.payload ?? {};
	const jobId = stringValue(payload.job_id) || null;
	const namespace = memoryNamespaceLabel(payload.namespace);
	const status = memoryActivityStatusForEvent(event.event_type);
	const label = memoryActivityLabelForEvent(event.event_type, payload);
	const detail = memoryActivityDetail(payload);
	return {
		status,
		label,
		detail,
		jobId,
		namespace,
		updatedAt: event.timestamp
	};
}

function memoryActivityStatusForEvent(eventType: FactoryEvent['event_type']): MemoryActivityStatus {
	if (eventType === 'memory_write_queued_failed' || eventType === 'memory_write_failed') {
		return 'failed';
	}
	if (eventType === 'memory_write_completed') {
		return 'completed';
	}
	return 'writing';
}

function memoryActivityLabelForEvent(eventType: FactoryEvent['event_type'], payload: Record<string, unknown>): string {
	if (eventType === 'memory_write_queued') {
		return '跨会话记忆后台写入中';
	}
	if (eventType === 'memory_segment_prepared') {
		return '跨会话记忆片段整理中';
	}
	if (eventType === 'memory_extraction_completed') {
		return '跨会话记忆整理中';
	}
	if (eventType === 'memory_write_completed') {
		const status = stringValue(payload.status);
		return status === 'noop' ? '跨会话记忆无需更新' : '跨会话记忆已更新';
	}
	if (eventType === 'memory_write_queued_failed') {
		return '跨会话记忆未入队';
	}
	if (eventType === 'memory_write_failed') {
		return '跨会话记忆写入失败';
	}
	return '跨会话记忆处理中';
}

function memoryActivityDetail(payload: Record<string, unknown>): string | null {
	const error = stringValue(payload.error);
	if (error) {
		return error;
	}
	const intent = stringValue(payload.intent);
	if (intent) {
		return `intent=${intent}`;
	}
	const actionCount = numberValue(payload.action_count);
	if (actionCount !== null) {
		return `actions=${actionCount}`;
	}
	const reportStatus = stringValue(payload.status);
	if (reportStatus && reportStatus !== 'queued') {
		return reportStatus;
	}
	const jobId = stringValue(payload.job_id);
	return jobId ? shortValue(jobId, 10) : null;
}

function memoryNamespaceLabel(value: unknown): string | null {
	if (Array.isArray(value)) {
		const text = value.map(item => String(item)).filter(Boolean).join('/');
		return text ? shortValue(text, 42) : null;
	}
	const text = stringValue(value);
	return text ? shortValue(text, 42) : null;
}

function contextActivityForEvent(event: FactoryEvent): ContextActivity {
	const payload = event.payload ?? {};
	return {
		status: contextActivityStatusForEvent(event.event_type),
		label: contextActivityLabelForEvent(event.event_type),
		detail: contextActivityDetail(payload),
		nodeId: stringValue(payload.node_id) || event.node_id || null,
		updatedAt: event.timestamp
	};
}

function contextWindowForEvent(event: FactoryEvent): ContextWindow {
	const payload = event.payload ?? {};
	return {
		tokenCount: numberValue(payload.token_count),
		contextWindowTokens: numberValue(payload.context_window_tokens),
		compressionThresholdTokens: numberValue(payload.compression_threshold_tokens),
		tokenCountMethod: stringValue(payload.token_count_method),
		source: stringValue(payload.source),
		error: stringValue(payload.error),
		updatedAt: event.timestamp
	};
}

function contextActivityStatusForEvent(eventType: FactoryEvent['event_type']): ContextActivityStatus {
	if (eventType === 'context_compression_failed') {
		return 'failed';
	}
	if (eventType === 'context_compression_started') {
		return 'running';
	}
	if (eventType === 'context_window_updated') {
		return 'completed';
	}
	return 'completed';
}

function contextActivityLabelForEvent(eventType: FactoryEvent['event_type']): string {
	if (eventType === 'context_compression_started') {
		return '上下文压缩中';
	}
	if (eventType === 'context_compression_completed') {
		return '上下文压缩完成';
	}
	if (eventType === 'context_compression_failed') {
		return '上下文压缩失败';
	}
	if (eventType === 'context_window_updated') {
		return '上下文窗口更新';
	}
	if (eventType === 'context_retrieval_completed') {
		return '上下文检索完成';
	}
	if (eventType === 'context_assembly_completed') {
		return '上下文组装完成';
	}
	return '上下文已注入';
}

function contextActivityDetail(payload: Record<string, unknown>): string | null {
	const error = stringValue(payload.error);
	if (error) {
		return shortValue(error, 42);
	}
	const itemCount = numberValue(payload.item_count);
	if (itemCount !== null) {
		return `${itemCount} items`;
	}
	const tokenCount = numberValue(payload.token_count);
	const windowTokens = numberValue(payload.context_window_tokens);
	const thresholdTokens = numberValue(payload.compression_threshold_tokens);
	if (tokenCount !== null && windowTokens !== null) {
		return `${formatCompactNumber(tokenCount)}/${formatCompactNumber(windowTokens)}`;
	}
	if (tokenCount !== null && thresholdTokens !== null) {
		return `${formatCompactNumber(tokenCount)} tokens @${formatCompactNumber(thresholdTokens)}`;
	}
	const selectedCount = numberValue(payload.selected_count);
	if (selectedCount !== null) {
		return `${selectedCount} selected`;
	}
	const tokenEstimate = numberValue(payload.token_estimate_after) ?? numberValue(payload.token_estimate);
	if (tokenEstimate !== null) {
		return `${tokenEstimate} tokens`;
	}
	return null;
}

function isMemoryWriteEvent(eventType: FactoryEvent['event_type']): boolean {
	return [
		'memory_write_queued',
		'memory_write_queued_failed',
		'memory_segment_prepared',
		'memory_extraction_completed',
		'memory_write_completed',
		'memory_write_failed'
	].includes(eventType);
}

function isTerminalMemoryEvent(eventType: FactoryEvent['event_type']): boolean {
	return ['memory_write_queued_failed', 'memory_write_completed', 'memory_write_failed'].includes(eventType);
}

function isContextEvent(eventType: FactoryEvent['event_type']): boolean {
	return [
		'context_compression_started',
		'context_compression_completed',
		'context_compression_failed',
		'context_retrieval_completed',
		'context_assembly_completed',
		'context_injection_completed'
	].includes(eventType);
}

function isTerminalContextEvent(eventType: FactoryEvent['event_type']): boolean {
	return [
		'context_compression_completed',
		'context_compression_failed',
		'context_injection_completed'
	].includes(eventType);
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

function formatCompactNumber(value: number): string {
	const absolute = Math.abs(value);
	if (absolute >= 1_000_000) {
		return `${trimNumber(value / 1_000_000)}M`;
	}
	if (absolute >= 1_000) {
		return `${trimNumber(value / 1_000)}k`;
	}
	return String(Math.round(value));
}

function trimNumber(value: number): string {
	return value.toFixed(value >= 10 ? 0 : 1).replace(/\.0$/, '');
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
		'scheduler_feedback_completed',
		'scheduler_feedback_failed',
		'context_compression_failed',
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

function appendSchedulerTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	if (event.event_type === 'scheduler_jobs_listed') {
		return appendSchedulerJobsTranscript(state, event);
	}
	if (event.event_type === 'scheduler_job_described') {
		return appendSchedulerJobDescriptionTranscript(state, event);
	}
	if (event.event_type === 'scheduler_runs_listed') {
		return appendSchedulerRunsTranscript(state, event);
	}
	if (event.event_type === 'scheduler_job_auto_paused') {
		return appendSchedulerAutoPausedTranscript(state, event);
	}
	return appendSchedulerFeedbackTranscript(state, event);
}

function appendSchedulerFeedbackTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	if (event.event_type !== 'scheduler_feedback_completed' && event.event_type !== 'scheduler_feedback_failed') {
		return state;
	}
	const payload = event.payload ?? {};
	const summary = stringValue(payload.summary);
	const error = stringValue(payload.error_summary);
	const task = stringValue(payload.task_content);
	const completedAt = stringValue(payload.completed_at);
	const count = numberValue(payload.completed_count);
	const lines = [
		task ? `任务：${task}` : null,
		completedAt ? `完成时间：${completedAt}` : null,
		typeof count === 'number' ? `完成次数：${count}` : null,
		summary ? `总结：${summary}` : null,
		error ? `错误：${error}` : null
	].filter((item): item is string => Boolean(item));
	return appendTranscript(state, {
		id: `scheduler-feedback-${event.event_id}`,
		role: 'scheduler',
		timestamp: event.timestamp,
		title: `Scheduler / ${stringValue(payload.job_id) || '-'}`,
		content: lines.join('\n') || compactValue(payload, 1200),
		eventType: event.event_type,
		metadata: payload
	});
}

function appendSchedulerJobsTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	const payload = recordValue(event.payload?.payload) ?? {};
	const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
	const lines = jobs.length
		? jobs.slice(0, 20).map(item => schedulerJobLine(recordValue(item))).filter(Boolean)
		: ['暂无定时任务'];
	return appendTranscript(state, {
		id: `scheduler-jobs-${event.event_id}`,
		role: 'scheduler',
		timestamp: event.timestamp,
		title: 'Scheduler / jobs',
		content: lines.join('\n'),
		eventType: event.event_type,
		metadata: event.payload ?? {}
	});
}

function appendSchedulerJobDescriptionTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	const payload = recordValue(event.payload?.payload) ?? {};
	const job = recordValue(payload.job);
	const runs = Array.isArray(payload.recent_runs) ? payload.recent_runs : [];
	const lines = [
		schedulerJobLine(job),
		...runs.slice(0, 8).map(item => schedulerRunLine(recordValue(item))).filter(Boolean)
	].filter((item): item is string => Boolean(item));
	return appendTranscript(state, {
		id: `scheduler-job-${event.event_id}`,
		role: 'scheduler',
		timestamp: event.timestamp,
		title: `Scheduler / ${stringValue(job?.job_id) || stringValue(event.payload?.job_id) || '-'}`,
		content: lines.join('\n') || compactValue(event.payload, 1200),
		eventType: event.event_type,
		metadata: event.payload ?? {}
	});
}

function appendSchedulerRunsTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	const payload = recordValue(event.payload?.payload) ?? {};
	const runs = Array.isArray(payload.runs) ? payload.runs : [];
	const lines = runs.length
		? runs.slice(0, 20).map(item => schedulerRunLine(recordValue(item))).filter(Boolean)
		: ['暂无执行记录'];
	return appendTranscript(state, {
		id: `scheduler-runs-${event.event_id}`,
		role: 'scheduler',
		timestamp: event.timestamp,
		title: 'Scheduler / runs',
		content: lines.join('\n'),
		eventType: event.event_type,
		metadata: event.payload ?? {}
	});
}

function appendSchedulerAutoPausedTranscript(state: RuntimeState, event: FactoryEvent): RuntimeState {
	const payload = event.payload ?? {};
	const detail = recordValue(payload.payload) ?? {};
	const lines = [
		`任务 ${stringValue(payload.job_id) || '-'} 已自动暂停`,
		stringValue(detail.reason) ? `原因：${stringValue(detail.reason)}` : null,
		typeof numberValue(detail.consecutive_failures) === 'number' ? `连续失败：${numberValue(detail.consecutive_failures)}` : null,
		typeof numberValue(detail.threshold) === 'number' ? `阈值：${numberValue(detail.threshold)}` : null,
		stringValue(payload.report_path) ? `report：${stringValue(payload.report_path)}` : null
	].filter((item): item is string => Boolean(item));
	return appendTranscript(state, {
		id: `scheduler-auto-paused-${event.event_id}`,
		role: 'scheduler',
		timestamp: event.timestamp,
		title: `Scheduler / auto paused`,
		content: lines.join('\n'),
		eventType: event.event_type,
		metadata: payload
	});
}

function schedulerJobLine(job: Record<string, unknown> | null | undefined): string | null {
	if (!job) {
		return null;
	}
	const target = recordValue(job.target);
	const enabled = job.enabled === false ? 'paused' : 'enabled';
	const task = stringValue(job.task_content) || stringValue(job.job_id) || '-';
	const schedule = [stringValue(job.schedule_type), stringValue(job.schedule_expr)].filter(Boolean).join(' ');
	const failurePolicy = recordValue(job.failure_policy);
	const threshold = numberValue(failurePolicy?.max_consecutive_failures);
	const failureText = failurePolicy?.enabled === false
		? 'auto-pause=off'
		: typeof threshold === 'number'
			? `auto-pause=${threshold} failures`
			: null;
	return [
		shortValue(stringValue(job.job_id), 10),
		enabled,
		stringValue(target?.target_type),
		schedule,
		failureText,
		task
	].filter(Boolean).join(' | ');
}

function schedulerRunLine(run: Record<string, unknown> | null | undefined): string | null {
	if (!run) {
		return null;
	}
	return [
		shortValue(stringValue(run.run_id), 10),
		stringValue(run.status),
		stringValue(run.target_type),
		stringValue(run.completed_at) || stringValue(run.started_at) || stringValue(run.scheduled_at),
		shortValue(stringValue(run.error_summary) || stringValue(run.output_summary), 80)
	].filter(Boolean).join(' | ');
}

function transcriptFromSession(session: Record<string, unknown>, mode: FactoryMode | null): TranscriptItem[] {
	const snapshot = recordValue(session.snapshot);
	const snapshotMessages = Array.isArray(snapshot?.messages) ? snapshot.messages : null;
	const messages = snapshotMessages ?? [];
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

function agentSessionIdFromEvent(event: FactoryEvent): string | null {
	if (event.mode !== 'agent_package') {
		return null;
	}
	const session = recordValue(event.payload?.agent_session);
	const sessionId = stringValue(session?.session_id);
	return sessionId || stringValue(event.session_id) || null;
}

function shortValue(value: string, limit: number): string {
	return value.length > limit ? `${value.slice(0, limit)}...` : value;
}

function stringValue(value: unknown): string {
	return typeof value === 'string' ? value.trim() : '';
}

function streamIdOf(event: FactoryEvent): string | null {
	const streamId = event.payload?.stream_id;
	return typeof streamId === 'string' && streamId ? streamId : null;
}
