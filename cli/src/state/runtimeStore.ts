import {type FactoryEvent, type FactoryMode} from '../protocol.js';
import {withRenderProjection} from './renderProjection.js';

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
	nodeLabel: string | null;
	message: string | null;
	payload: Record<string, unknown>;
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
	payload: Record<string, unknown>;
};

export type PlanStepStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped' | string;

export type RuntimePlanStepView = {
	stepId: string;
	title: string;
	objective: string;
	status: PlanStepStatus;
	dependsOn: string[];
	acceptanceCriteria: string[];
	toolHints: string[];
	resultSummary: string | null;
};

export type RuntimePlanView = {
	version: string;
	goal: string;
	status: string;
	currentStepId: string | null;
	steps: RuntimePlanStepView[];
	sourceNodeId: string | null;
	updatedAt: string;
};

export type MemoryActivityStatus = 'idle' | 'writing' | 'completed' | 'failed';

export type MemoryActivity = {
	status: MemoryActivityStatus;
	eventType: FactoryEvent['event_type'] | null;
	payload: Record<string, unknown>;
	jobId: string | null;
	namespace: string | null;
	updatedAt: string | null;
};

export type ContextActivityStatus = 'idle' | 'running' | 'completed' | 'failed' | 'skipped';

export type ContextActivity = {
	status: ContextActivityStatus;
	eventType: FactoryEvent['event_type'] | null;
	payload: Record<string, unknown>;
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
	reportPath: string | null;
	payload: Record<string, unknown>;
};

export type KnowledgeActivity = {
	eventType: FactoryEvent['event_type'];
	timestamp: string;
	sourceId: string | null;
	jobId: string | null;
	mode: string | null;
	phase: string | null;
	status: string | null;
	reportPath: string | null;
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

export type TranscriptRole = 'user' | 'assistant' | 'tool' | 'interrupt' | 'scheduler' | 'knowledge' | 'system';

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
	kind: 'message' | 'tool' | 'scheduler' | 'knowledge' | 'activity' | 'error';
	role: TranscriptRole | null;
	source: 'transcript' | 'tool' | 'scheduler' | 'knowledge' | 'interrupt' | 'runtime_activity' | 'runtime_error';
	turnId: string | null;
	eventType: FactoryEvent['event_type'] | null;
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
	agentPackagePickerPurpose: 'run' | 'evolution';
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
	currentPlan: RuntimePlanView | null;
	memoryActivity: MemoryActivity;
	contextActivity: ContextActivity;
	contextWindow: ContextWindow;
	schedulerActivities: SchedulerActivity[];
	knowledgeActivities: KnowledgeActivity[];
	debugEvents: FactoryEvent[];
	pendingInterrupt: FactoryEvent | null;
	currentRunId: string | null;
	activeRequestId: string | null;
	runStatus: 'idle' | 'running' | 'interrupted' | 'completed' | 'failed';
	helpVisible: boolean;
	showState: boolean;
	showMessages: boolean;
	toolGrep: string;
	lastError: string | null;
	errors: string[];
};

export type RuntimeAction =
	| FactoryEvent
	| {ui_type: 'set_tool_grep'; query: string}
	| {ui_type: 'set_session_picker_open'; open: boolean}
	| {ui_type: 'set_agent_package_picker_open'; open: boolean}
	| {ui_type: 'set_agent_package_picker_purpose'; purpose: 'run' | 'evolution'}
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
		agentPackagePickerPurpose: 'run',
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
		currentPlan: null,
		memoryActivity: idleMemoryActivity(),
		contextActivity: idleContextActivity(),
		contextWindow: emptyContextWindow(),
		schedulerActivities: [],
		knowledgeActivities: [],
		debugEvents: [],
		pendingInterrupt: null,
		currentRunId: null,
		activeRequestId: null,
		runStatus: 'idle',
		helpVisible: true,
		showState: false,
		showMessages: true,
		toolGrep: '',
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
		this.state = withRenderProjection(reduceRuntimeAction(this.state, action));
		if ('event_type' in action && isMemoryWriteEvent(action.event_type)) {
			this.scheduleMemoryActivityClear(
				this.state.memoryActivity.updatedAt,
				isTerminalMemoryEvent(action.event_type) ? TERMINAL_MEMORY_HINT_MS : ACTIVE_MEMORY_HINT_MS
			);
		}
		if ('event_type' in action && isContextEvent(action.event_type)) {
			if (isTerminalContextEvent(action.event_type)) {
				this.scheduleContextActivityClear(this.state.contextActivity.updatedAt, TERMINAL_CONTEXT_HINT_MS);
			} else {
				this.cancelContextActivityClear();
			}
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
		this.state = withRenderProjection(next);
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

	private cancelContextActivityClear(): void {
		if (!this.contextActivityTimer) {
			return;
		}
		clearTimeout(this.contextActivityTimer);
		this.contextActivityTimer = null;
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
	if (action.ui_type === 'set_agent_package_picker_open') {
		return {...state, agentPackagePickerOpen: action.open};
	}
	if (action.ui_type === 'set_agent_package_picker_purpose') {
		return {...state, agentPackagePickerPurpose: action.purpose};
	}
	if (action.ui_type === 'set_agent_session_picker_open') {
		return {...state, agentSessionPickerOpen: action.open};
	}
	if (action.ui_type === 'select_agent_session') {
		return resetSessionScopedProjection({
			...state,
			activeAgentSessionId: action.sessionId,
			agentSessionPickerOpen: false
		}, []);
	}
	if (action.ui_type === 'clear_agent_package_selection') {
		return resetSessionScopedProjection({
			...state,
			mode: null,
			activeAgentPackage: null,
			agentPackageSessions: [],
			activeAgentSessionId: null,
			agentPackagePickerOpen: false,
			agentPackagePickerPurpose: 'run',
			agentSessionPickerOpen: false
		}, []);
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
	if (!shouldApplyRequestScopedRuntimeEvent(state, event)) {
		return base;
	}
	switch (event.event_type) {
		case 'runtime_ready':
			return {...base, ready: true, logs: [...base.logs, 'runtime bridge ready']};
		case 'session_started':
		case 'session_switched': {
			const session = (event.payload?.session ?? {}) as Record<string, unknown>;
			const transcript = transcriptFromSession(session, event.mode ?? null);
			return resetSessionScopedProjection({
				...base,
				sessionId: String(session.session_id ?? event.session_id ?? ''),
				sessionTitle: sessionTitle(session),
				mode: (session.current_mode as FactoryMode | null) ?? event.mode ?? null,
				logs: [...base.logs, `session: ${String(session.session_id ?? event.session_id ?? '-')}`]
			}, transcript);
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
			const mode = event.mode === 'evolve_agent' ? 'evolve_agent' : 'agent_package';
			return resetSessionScopedProjection({
				...base,
				mode,
				activeAgentPackage: selectedPackage,
				agentPackageSessions: sessions,
				activeAgentSessionId: null,
				agentPackagePickerOpen: false,
				agentPackagePickerPurpose: 'run',
				agentSessionPickerOpen: mode === 'agent_package',
				helpVisible: false,
				logs: [...base.logs, `agent package selected: ${String(selectedPackage?.package_id ?? '-')}`]
			}, []);
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
				currentPlan: null,
				debugEvents: [],
				contextWindow: emptyContextWindow(),
				knowledgeActivities: [],
				currentRunId: event.run_id ?? null,
				activeRequestId: event.request_id ?? null,
				runStatus: 'running',
				pendingInterrupt: null,
				helpVisible: false,
				logs: [...base.logs, runStartedLog(event)]
			};
		case 'runtime_options_changed': {
			const options = (event.payload?.options ?? {}) as Record<string, unknown>;
			return {
				...base,
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
		case 'tool_contract_invalid':
		case 'tool_call_failed':
		case 'tool_observation_available':
			return {
				...base,
				recentActivities: appendRunActivity(base.recentActivities, event),
				toolActivities: upsertToolActivities(base.toolActivities, toolActivitiesForEvent(event))
			};
		case 'tool_approval_resolved':
			return {
				...base,
				runStatus: 'running',
				activeRequestId: event.request_id ?? base.activeRequestId,
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
		case 'context_prepare_started':
		case 'context_prepare_completed':
		case 'context_prepare_failed':
		case 'context_compression_started':
		case 'context_compression_completed':
		case 'context_compression_failed':
		case 'context_compression_skipped':
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
			case 'knowledge_source_prepare_started':
			case 'knowledge_source_preview_available':
			case 'knowledge_source_approval_requested':
			case 'knowledge_source_registered':
			case 'knowledge_ingestion_queued':
			case 'knowledge_ingestion_started':
			case 'knowledge_ingestion_progress':
			case 'knowledge_ingestion_completed':
			case 'knowledge_ingestion_failed':
			case 'knowledge_ingestion_cancelled':
			case 'knowledge_source_ready':
			case 'knowledge_source_removed':
			case 'knowledge_source_reindex_requested':
				return appendOptionalTranscript({
					...base,
					knowledgeActivities: [...base.knowledgeActivities.slice(-19), knowledgeActivityForEvent(event)],
					recentActivities: appendRunActivity(base.recentActivities, event)
				}, transcriptItemForKnowledgeEvent(event));
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
		case 'scheduler_seed_detected':
		case 'scheduler_seed_applied':
		case 'scheduler_seed_unchanged':
		case 'scheduler_seed_failed':
			return {
				...base,
				schedulerActivities: [...base.schedulerActivities.slice(-19), schedulerActivityForEvent(event)],
				recentActivities: appendRunActivity(base.recentActivities, event)
			};
		case 'plan_updated':
			return {
				...base,
				currentPlan: planViewForEvent(event),
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
			if (isRuntimeRequestHeartbeat(event)) {
				return updateNodeStatus(base, event, 'running');
			}
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
				{...updateNodeStatus(base, event, 'failed'), recentActivities: appendRunActivity(base.recentActivities, event)},
				errorMessageFromEvent(event, `node failed: ${event.node_label ?? event.node_id ?? '-'}`)
			);
		case 'interrupt_requested':
			return appendOptionalTranscript({
				...base,
				runStatus: 'interrupted',
				activeRequestId: null,
				pendingInterrupt: base.pendingInterrupt ?? event,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `interrupt: ${String(event.payload?.type ?? event.event_type)}`]
			}, transcriptItemForInterrupt(event));
		case 'tool_approval_requested':
			return {
				...base,
				toolActivities: upsertToolActivities(base.toolActivities, toolActivitiesForEvent(event)),
				runStatus: 'interrupted',
				activeRequestId: null,
				pendingInterrupt: event,
				recentActivities: appendRunActivity(base.recentActivities, event),
				logs: [...base.logs, `interrupt: ${String(event.payload?.type ?? event.event_type)}`]
			};
		case 'runtime_resumed':
			return {
				...base,
				runStatus: 'running',
				activeRequestId: event.request_id ?? base.activeRequestId,
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
					recentActivities: appendRunActivity(base.recentActivities, event)
				},
				errorMessageFromEvent(event, `stage failed: ${event.stage_id ?? '-'}`)
			);
		case 'run_completed':
			return {
				...base,
				runStatus: 'completed',
				activeRequestId: null,
				currentStageId: null,
				currentNodeId: null,
				pendingInterrupt: null,
				recentActivities: appendRunActivity(base.recentActivities, event),
				activeAgentSessionId: agentSessionIdFromEvent(event) ?? base.activeAgentSessionId,
				logs: [...base.logs, `run completed: ${String(event.payload?.status ?? '-')}`]
			};
		case 'run_failed':
			return recordError(
				{...base, runStatus: 'failed', activeRequestId: null, pendingInterrupt: null, recentActivities: appendRunActivity(base.recentActivities, event)},
				errorMessageFromEvent(event, 'run failed')
			);
		case 'error':
			return recordError(
				isActiveRequestEvent(base, event)
					? {...base, runStatus: 'failed', activeRequestId: null, pendingInterrupt: null}
					: base,
				errorMessageFromEvent(event, 'unknown error')
			);
		default:
			return base;
	}
}

function resetSessionScopedProjection(state: RuntimeState, transcript: TranscriptItem[]): RuntimeState {
	return {
		...state,
		transcript,
		stageStatuses: {},
		nodeStatuses: {},
		currentStageId: null,
		currentNodeId: null,
		recentActivities: [],
		modelStreams: {},
		toolActivities: [],
		currentPlan: null,
		memoryActivity: idleMemoryActivity(),
		contextActivity: idleContextActivity(),
		contextWindow: emptyContextWindow(),
		schedulerActivities: [],
		knowledgeActivities: [],
		debugEvents: [],
		pendingInterrupt: null,
		currentRunId: null,
		activeRequestId: null,
		runStatus: 'idle',
		lastError: null,
		errors: []
	};
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

function shouldApplyRequestScopedRuntimeEvent(state: RuntimeState, event: FactoryEvent): boolean {
	if (!isRequestScopedRuntimeEvent(event)) {
		return true;
	}
	const requestId = event.request_id ?? null;
	if (!requestId) {
		return false;
	}
	if (event.event_type === 'run_started') {
		return true;
	}
	if (state.activeRequestId === requestId) {
		return true;
	}
	if (state.activeRequestId === null && state.runStatus === 'interrupted' && isResumeRuntimeEvent(event)) {
		return true;
	}
	return false;
}

function isActiveRequestEvent(state: RuntimeState, event: FactoryEvent): boolean {
	const requestId = event.request_id ?? null;
	return Boolean(requestId && state.activeRequestId === requestId);
}

function isRequestScopedRuntimeEvent(event: FactoryEvent): boolean {
	const eventType = event.event_type;
	return (
		eventType === 'run_started'
		|| eventType === 'run_completed'
		|| eventType === 'run_failed'
		|| eventType === 'runtime_paused'
		|| eventType === 'runtime_resumed'
		|| eventType.startsWith('node_')
		|| eventType.startsWith('stage_')
		|| eventType.startsWith('model_')
		|| eventType.startsWith('tool_')
		|| eventType.startsWith('plan_')
		|| eventType.startsWith('context_')
	);
}

function isResumeRuntimeEvent(event: FactoryEvent): boolean {
	return event.event_type === 'runtime_resumed' || event.event_type === 'tool_approval_resolved';
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
				content: mergeModelStreamDelta(current.content, String(event.payload?.delta ?? ''), String(event.payload?.content_mode ?? 'delta')),
				active: true
			}
		}
	};
	if (event.payload?.visible_to_user === false) {
		return next;
	}
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
	const completedContent = String(event.payload?.content ?? '');
	const current = state.modelStreams[streamId] ?? {
		streamId,
		nodeId: event.node_id ?? null,
		content: completedContent,
		active: false,
		completedAt: event.timestamp
	};
	const content = completedContent || current.content;
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
	if (event.payload?.visible_to_user === false) {
		return next;
	}
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
	return {
		activityKey: toolActivityKey(event, payload),
		eventType: event.event_type,
		timestamp: event.timestamp,
		createdAt: event.timestamp,
		stageId: event.stage_id ?? null,
		nodeId: event.node_id ?? null,
		toolCallId: payloadToolCallId(payload) || null,
		toolName: toolNameFromPayload(payload),
		status: lifecycleForToolEvent(event.event_type),
		approvalState: approvalState(payload),
		payload
	};
}

function planViewForEvent(event: FactoryEvent): RuntimePlanView {
	const payload = event.payload ?? {};
	const rawSteps = Array.isArray(payload.steps) ? payload.steps : [];
	return {
		version: stringValue(payload.version) || 'plan_state.v0',
		goal: stringValue(payload.goal),
		status: stringValue(payload.status) || 'active',
		currentStepId: stringValue(payload.current_step_id) || null,
		steps: rawSteps
			.map(planStepView)
			.filter((step): step is RuntimePlanStepView => step !== null),
		sourceNodeId: stringValue(payload.source_node_id) || (event.node_id ?? null),
		updatedAt: event.timestamp
	};
}

function planStepView(value: unknown): RuntimePlanStepView | null {
	const record = recordValue(value);
	if (!record) {
		return null;
	}
	const stepId = stringValue(record.step_id);
	if (!stepId) {
		return null;
	}
	const title = stringValue(record.title) || stepId;
	return {
		stepId,
		title,
		objective: stringValue(record.objective),
		status: stringValue(record.status) || 'pending',
		dependsOn: stringList(record.depends_on),
		acceptanceCriteria: stringList(record.acceptance_criteria),
		toolHints: stringList(record.tool_hints),
		resultSummary: stringValue(record.result_summary) || null
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
	const payload = unwrapApprovalResolutionPayload(event.payload ?? {});
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

function unwrapApprovalResolutionPayload(payload: Record<string, unknown>): Record<string, unknown> {
	if (approvalState(payload)) {
		return payload;
	}
	for (const value of Object.values(payload)) {
		if (value && typeof value === 'object' && !Array.isArray(value)) {
			const nested = value as Record<string, unknown>;
			if (approvalState(nested)) {
				return nested;
			}
		}
	}
	return payload;
}

function mergeToolActivity(existing: ToolActivity, incoming: ToolActivity): ToolActivity {
	const mergedPayload = {...existing.payload, ...incoming.payload};
	return {
		...incoming,
		createdAt: existing.createdAt,
		stageId: incoming.stageId ?? existing.stageId,
		nodeId: incoming.nodeId ?? existing.nodeId,
		toolCallId: incoming.toolCallId ?? existing.toolCallId,
		toolName: incoming.toolName === '-' ? existing.toolName : incoming.toolName,
		status: nextToolStatus(existing.status, incoming.status),
		approvalState: incoming.approvalState ?? existing.approvalState,
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
	if (isRuntimeRequestHeartbeat(event)) {
		return current;
	}
	const activity = runActivity(event);
	if (!activity) {
		return current;
	}
	return [...current.slice(-39), activity];
}

function runStartedLog(event: FactoryEvent): string {
	const selectedPattern = stringValue(
		event.payload?.selected_runtime_pattern_id
			?? (event.payload?.selected_runtime_pattern as Record<string, unknown> | undefined)?.pattern_id
	);
	return selectedPattern ? `run started: selected runtime pattern ${selectedPattern}` : 'run started';
}

function isRuntimeRequestHeartbeat(event: FactoryEvent): boolean {
	return event.event_type === 'node_progress' && event.node_id === 'runtime_request';
}

function runActivity(event: FactoryEvent): RunActivity | null {
	const eventType = event.event_type;
	if (
		eventType.startsWith('tool_')
		|| eventType.startsWith('model_')
		|| eventType.startsWith('scheduler_')
		|| eventType.startsWith('stage_')
		|| eventType.startsWith('node_')
		|| eventType.startsWith('run_')
		|| eventType.includes('interrupt')
		|| eventType.startsWith('runtime_')
	) {
		return {
			activityKey: `${event.event_id}:activity`,
			eventType,
			timestamp: event.timestamp,
			stageId: event.stage_id ?? null,
			nodeId: event.node_id ?? null,
			nodeLabel: event.node_label ?? null,
			message: event.message ?? null,
			payload: event.payload ?? {}
		};
	}
	return null;
}

function resourceLikeActivityDetail(payload: Record<string, unknown>, fallback: string): string {
	const error = stringValue(payload.error);
	const status = stringValue(payload.status);
	const toolId = stringValue(payload.tool_id);
	const question = stringValue(payload.question);
	const query = stringValue(payload.query);
	const count = numberValue(payload.facts_count) ?? numberValue(payload.answer_length);
	if (error) {
		return firstLine(error);
	}
	if (toolId) {
		return query ? `${toolId}: ${firstLine(query)}` : toolId;
	}
	if (question) {
		return firstLine(question);
	}
	if (count !== null) {
		return `${count}`;
	}
	if (status) {
		return status;
	}
	return fallback;
}

function lifecycleForToolEvent(eventType: FactoryEvent['event_type']): ToolLifecycle {
	if (eventType === 'tool_call_failed' || eventType === 'tool_contract_invalid') {
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

function schedulerActivityForEvent(event: FactoryEvent): SchedulerActivity {
	const payload = event.payload ?? {};
	return {
		eventType: event.event_type,
		timestamp: event.timestamp,
		jobId: stringValue(payload.job_id) || null,
		runId: stringValue(payload.run_id) || null,
		targetType: stringValue(payload.target_type) || null,
		status: stringValue(payload.status) || null,
		reportPath: stringValue(payload.report_path) || null,
		payload
	};
}

function knowledgeActivityForEvent(event: FactoryEvent): KnowledgeActivity {
	const payload = event.payload ?? {};
	return {
		eventType: event.event_type,
		timestamp: event.timestamp,
		sourceId: stringValue(payload.source_id) || null,
		jobId: stringValue(payload.job_id) || null,
		mode: stringValue(payload.mode) || null,
		phase: stringValue(payload.phase) || null,
		status: stringValue(payload.status) || null,
		reportPath: stringValue(payload.report_path) || null,
		payload
	};
}

function idleMemoryActivity(): MemoryActivity {
	return {
		status: 'idle',
		eventType: null,
		payload: {},
		jobId: null,
		namespace: null,
		updatedAt: null
	};
}

function idleContextActivity(): ContextActivity {
	return {
		status: 'idle',
		eventType: null,
		payload: {},
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
	return {
		status,
		eventType: event.event_type,
		payload,
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
		eventType: event.event_type,
		payload,
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
	if (eventType === 'context_prepare_failed' || eventType === 'context_compression_failed') {
		return 'failed';
	}
	if (eventType === 'context_prepare_started' || eventType === 'context_compression_started') {
		return 'running';
	}
	if (eventType === 'context_compression_skipped') {
		return 'skipped';
	}
	if (eventType === 'context_window_updated') {
		return 'completed';
	}
	return 'completed';
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
		'context_prepare_started',
		'context_prepare_completed',
		'context_prepare_failed',
		'context_compression_started',
		'context_compression_completed',
		'context_compression_failed',
		'context_compression_skipped',
		'context_retrieval_completed',
		'context_assembly_completed',
		'context_injection_completed'
	].includes(eventType);
}

function isTerminalContextEvent(eventType: FactoryEvent['event_type']): boolean {
	return [
		'context_prepare_completed',
		'context_prepare_failed',
		'context_compression_completed',
		'context_compression_failed',
		'context_compression_skipped',
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

function toolNameFromPayload(payload: Record<string, unknown>): string {
	const message = recordValue(payload.message);
	const resourceCheck = recordValue(payload.resource_check);
	const result = parseJsonLike(payload.result ?? payload.output ?? payload.content ?? message?.content ?? resourceCheck?.raw_result ?? resourceCheck?.result_summary);
	const resultRecord = recordValue(result);
	const observation = recordValue(resultRecord?.type === 'tool_observation' ? resultRecord : resultRecord?.observation);
	return stringValue(payload.tool_name)
		|| stringValue(payload.name)
		|| stringValue(observation?.tool_id)
		|| stringValue(message?.name)
		|| stringValue(resourceCheck?.tool_name)
		|| '-';
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

function stringList(value: unknown): string[] {
	if (!Array.isArray(value)) {
		return [];
	}
	return value
		.map(item => typeof item === 'string' ? item.trim() : '')
		.filter(Boolean);
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
		'context_prepare_failed',
		'context_compression_failed',
		'runtime_resumed',
		'run_completed',
		'error'
	].includes(eventType);
}

function appendTranscript(state: RuntimeState, item: TranscriptItem): RuntimeState {
	return {...state, transcript: [...state.transcript.slice(-199), item]};
}

function appendOptionalTranscript(state: RuntimeState, item: TranscriptItem | null): RuntimeState {
	return item ? appendTranscript(state, item) : state;
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
		return appendOrMergeAssistantTranscript(state, item);
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

function appendOrMergeAssistantTranscript(state: RuntimeState, item: TranscriptItem): RuntimeState {
	const previous = state.transcript.at(-1);
	if (previous?.role !== 'assistant') {
		return appendTranscript(state, item);
	}
	if (!sameAssistantContent(previous.content, item.content)) {
		return appendTranscript(state, item);
	}
	return {
		...state,
		transcript: [
			...state.transcript.slice(0, -1),
			{
				...previous,
				timestamp: item.timestamp,
				content: item.content,
				eventType: item.eventType,
				active: item.active,
				metadata: {
					...(previous.metadata ?? {}),
					duplicate_stream_id: item.streamId,
					duplicate_event_type: item.eventType
				}
			}
		]
	};
}

function mergeModelStreamDelta(current: string, incoming: string, contentMode: string): string {
	if (!incoming) {
		return current;
	}
	if (contentMode === 'snapshot') {
		return incoming;
	}
	if (!current) {
		return incoming;
	}
	if (incoming === current) {
		return current;
	}
	if (incoming.startsWith(current)) {
		return incoming;
	}
	const overlap = suffixPrefixOverlap(current, incoming);
	if (overlap >= 20) {
		return current + incoming.slice(overlap);
	}
	if (incoming.length >= 20 && current.endsWith(incoming)) {
		return current;
	}
	return current + incoming;
}

function suffixPrefixOverlap(left: string, right: string): number {
	const limit = Math.min(left.length, right.length);
	for (let size = limit; size >= 20; size -= 1) {
		if (left.endsWith(right.slice(0, size))) {
			return size;
		}
	}
	return 0;
}

function sameAssistantContent(left: string, right: string): boolean {
	const normalizedLeft = normalizeTranscriptContent(left);
	const normalizedRight = normalizeTranscriptContent(right);
	return Boolean(normalizedLeft) && normalizedLeft === normalizedRight;
}

function normalizeTranscriptContent(value: string): string {
	return value.trim().replace(/\s+/g, ' ');
}

function transcriptItemForInterrupt(event: FactoryEvent): TranscriptItem | null {
	const payload = event.payload ?? {};
	if (stringValue(payload.presentation) !== 'assistant_dialogue') {
		return null;
	}
	const message = stringValue(payload.message);
	const summary = stringValue(payload.summary);
	const content = [message, summary].filter(Boolean).join('\n\n');
	if (!content) {
		return null;
	}
	return {
		id: `interrupt-${event.event_id}`,
		role: 'assistant',
		timestamp: event.timestamp,
		title: stringValue(payload.title) || '补充信息',
		content,
		eventType: event.event_type,
		metadata: payload
	};
}

function transcriptItemForKnowledgeEvent(event: FactoryEvent): TranscriptItem | null {
	if (event.event_type !== 'knowledge_source_preview_available') {
		return null;
	}
	const payload = event.payload ?? {};
	const preview = recordValue(payload.preview) ?? payload;
	const displayName = stringValue(preview.display_name) || stringValue(payload.source_id) || 'knowledge source';
	const mode = stringValue(payload.mode);
	const status = stringValue(payload.status);
	const estimatedDocuments = preview.estimated_documents;
	const requiresEmbedding = preview.requires_embedding;
	const lines = [
		`来源：${displayName}`,
		mode ? `模式：${mode}` : '',
		status ? `状态：${status}` : '',
		typeof estimatedDocuments === 'number' ? `预计文档数：${estimatedDocuments}` : '',
		typeof requiresEmbedding === 'boolean' ? `需要向量化：${requiresEmbedding ? '是' : '否'}` : ''
	].filter(Boolean);
	return {
		id: `knowledge-${event.event_id}`,
		role: 'knowledge',
		timestamp: event.timestamp,
		title: 'Knowledge / preview',
		content: lines.join('\n'),
		eventType: event.event_type,
		metadata: payload
	};
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
