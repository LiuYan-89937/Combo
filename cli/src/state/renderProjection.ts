import type {FactoryEvent} from '../protocol.js';
import type {
	ActivityColor,
	ContextActivity,
	KnowledgeActivity,
	MemoryActivity,
	RuntimeState,
	SchedulerActivity,
	TimelineItem,
	ToolActivity,
	TranscriptItem
} from './runtimeStore.js';

export function memoryActivityStatusLabel(activity: MemoryActivity): string {
	const eventType = activity.eventType;
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
		const status = stringValue(activity.payload.status);
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

export function contextActivityStatusLabel(activity: ContextActivity): string {
	const eventType = activity.eventType;
	if (eventType === 'context_prepare_started') {
		return '上下文准备中';
	}
	if (eventType === 'context_prepare_completed') {
		return '上下文已准备';
	}
	if (eventType === 'context_prepare_failed') {
		return '上下文准备失败';
	}
	if (eventType === 'context_compression_started') {
		return '上下文压缩中';
	}
	if (eventType === 'context_compression_completed') {
		return '上下文压缩完成';
	}
	if (eventType === 'context_compression_failed') {
		return '上下文压缩失败';
	}
	if (eventType === 'context_compression_skipped') {
		return '上下文压缩跳过';
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

export function withRenderProjection(state: RuntimeState): RuntimeState {
	const timelineItems = buildTimelineItems(state);
	if (timelineItemsEqual(state.timelineItems, timelineItems)) {
		return state;
	}
	return {...state, timelineItems};
}

export function buildTimelineItems(state: RuntimeState): TimelineItem[] {
	const transcriptItems = state.transcript
		.filter(item => item.role !== 'tool')
		.map((item, index) => transcriptTimelineItem(item, index));
	const eventProjectionItems = state.events
		.flatMap((event, index) => eventTimelineItems(event, index));
	const toolItems = state.toolActivities.slice(-30).map((item, index) => toolTimelineItem(item, index));
	const schedulerItems = state.schedulerActivities
		.filter(item => !richSchedulerEventTypes.has(item.eventType))
		.slice(-16)
		.map((item, index) => schedulerTimelineItem(item, index));
	const knowledgeItems = state.knowledgeActivities
		.filter(item => !richKnowledgeEventTypes.has(item.eventType))
		.slice(-16)
		.map((item, index) => knowledgeTimelineItem(item, index));
	const activityItems = state.mode === 'create_agent'
		? state.recentActivities
			.filter(item => !item.eventType.startsWith('tool_') && !item.eventType.startsWith('scheduler_') && !item.eventType.startsWith('knowledge_'))
			.slice(-18)
			.map((item, index) => runActivityTimelineItem(item, index))
		: [];
	const errorItems = state.errors.slice(-3).map((message, index) => ({
		id: `error:${index}:${message}`,
		timestamp: '',
		order: 90_000 + index,
		color: 'red' as const,
		title: 'Runtime error',
		body: message,
		kind: 'error' as const,
		role: null,
		source: 'runtime_error' as const,
		turnId: null,
		eventType: 'error' as const
	}));
	return [...transcriptItems, ...eventProjectionItems, ...toolItems, ...schedulerItems, ...knowledgeItems, ...activityItems, ...errorItems]
		.sort((left, right) => compareTimelineItems(left, right));
}

export function timelineItemsEqual(left: TimelineItem[], right: TimelineItem[]): boolean {
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
			&& item.kind === other.kind
			&& item.role === other.role
			&& item.source === other.source
			&& item.turnId === other.turnId
			&& item.eventType === other.eventType
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
		kind: 'message',
		role: item.role,
		source: 'transcript',
		turnId: turnIdForTranscript(item, index),
		eventType: item.eventType ?? null,
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
		body: toolTimelineBody(item),
		kind: 'tool',
		role: 'tool',
		source: 'tool',
		turnId: null,
		eventType: item.eventType
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
			schedulerActivityDetail(item.payload) || null,
			item.reportPath ? `report ${item.reportPath}` : null
		].filter((value): value is string => Boolean(value)).join('\n'),
		kind: 'scheduler',
		role: 'scheduler',
		source: 'scheduler',
		turnId: null,
		eventType: item.eventType
	};
}

function knowledgeTimelineItem(item: KnowledgeActivity, index: number): TimelineItem {
	return {
		id: `knowledge:${item.timestamp}:${item.eventType}:${item.sourceId ?? item.jobId ?? index}`,
		timestamp: item.timestamp,
		order: 35_000 + index,
		color: colorForKnowledgeStatus(item.status),
		title: `Knowledge ${item.eventType.replace(/^knowledge_/, '').replaceAll('_', ' ')}`,
		body: [
			item.sourceId ? `source ${shortTimelineValue(item.sourceId, 24)}` : null,
			item.jobId ? `job ${shortTimelineValue(item.jobId, 16)}` : null,
			item.mode ? `mode ${item.mode}` : null,
			item.phase ? `phase ${item.phase}` : null,
			item.status ? `status ${item.status}` : null,
			knowledgeActivityDetail(item.payload) || null,
			item.reportPath ? `report ${item.reportPath}` : null
		].filter((value): value is string => Boolean(value)).join('\n'),
		kind: 'knowledge',
		role: 'knowledge',
		source: 'knowledge',
		turnId: null,
		eventType: item.eventType
	};
}

function runActivityTimelineItem(item: RuntimeState['recentActivities'][number], index: number): TimelineItem {
	const projection = runActivityProjection(item);
	return {
		id: `activity:${item.activityKey}`,
		timestamp: item.timestamp,
		order: 40_000 + index,
		color: projection.color,
		title: projection.label,
		body: [item.stageId, item.nodeId, projection.detail].filter(Boolean).join('  '),
		kind: 'activity',
		role: null,
		source: 'runtime_activity',
		turnId: null,
		eventType: item.eventType
	};
}

function runActivityProjection(item: RuntimeState['recentActivities'][number]): {
	label: string;
	detail: string;
	color: ActivityColor;
} {
	const eventType = item.eventType;
	const payload = item.payload ?? {};
	const node = item.nodeId ?? item.stageId ?? '-';
	if (eventType.startsWith('tool_')) {
		const toolPayload = normalizeToolPayload(payload);
		return {
			label: labelForToolLifecycle(lifecycleForToolEvent(eventType)),
			detail: `${toolPayload.toolName}${toolPayload.argsPreview ? ` ${toolPayload.argsPreview}` : ''}`,
			color: colorForEvent(eventType)
		};
	}
	if (eventType.startsWith('model_')) {
		return {
			label: eventType === 'model_call_started' ? 'model thinking' : eventType === 'model_message_completed' ? 'model answered' : 'model update',
			detail: String(payload.prompt_id ?? node),
			color: colorForEvent(eventType)
		};
	}
	if (eventType.startsWith('scheduler_')) {
		return {
			label: readableEventType(eventType),
			detail: schedulerActivityDetail(payload),
			color: colorForEvent(eventType)
		};
	}
	return {
		label: readableEventType(eventType),
		detail: eventType.endsWith('failed') || eventType === 'run_failed'
			? firstLine(errorMessageFromPayload(item.message, payload, readableEventType(eventType)))
			: item.message ?? String(payload.type ?? payload.status ?? item.nodeLabel ?? node),
		color: colorForEvent(eventType)
	};
}

const richSchedulerEventTypes = new Set<FactoryEvent['event_type']>([
	'scheduler_jobs_listed',
	'scheduler_job_described',
	'scheduler_runs_listed',
	'scheduler_job_auto_paused',
	'scheduler_feedback_completed',
	'scheduler_feedback_failed'
]);

const richKnowledgeEventTypes = new Set<FactoryEvent['event_type']>([
	'knowledge_source_preview_available',
	'knowledge_source_ready',
	'knowledge_ingestion_completed',
	'knowledge_ingestion_failed',
	'knowledge_source_removed'
]);

function eventTimelineItems(event: FactoryEvent, index: number): TimelineItem[] {
	if (event.event_type === 'interrupt_requested') {
		const item = interruptTimelineItem(event, index);
		return item ? [item] : [];
	}
	if (richSchedulerEventTypes.has(event.event_type)) {
		const item = schedulerEventTimelineItem(event, index);
		return item ? [item] : [];
	}
	if (richKnowledgeEventTypes.has(event.event_type)) {
		const item = knowledgeEventTimelineItem(event, index);
		return item ? [item] : [];
	}
	return [];
}

function interruptTimelineItem(event: FactoryEvent, index: number): TimelineItem | null {
	const payload = event.payload ?? {};
	const interruptType = String(payload.type ?? event.event_type);
	if (interruptType === 'tool_approval') {
		return null;
	}
	if (payload.presentation === 'assistant_dialogue') {
		const summary = stringValue(payload.summary);
		const message = stringValue(payload.message);
		const body = [message, summary && summary !== message ? summary : null].filter((item): item is string => Boolean(item)).join('\n\n');
		return {
			id: `interrupt:${event.event_id}`,
			timestamp: event.timestamp,
			order: 10_000 + index,
			color: 'yellow',
			title: stringValue(payload.title) || 'Assistant question',
			body: body || compactValue(payload, 1200),
			kind: 'message',
			role: 'assistant',
			source: 'interrupt',
			turnId: null,
			eventType: event.event_type
		};
	}
	const requests = Array.isArray(payload.requests) ? payload.requests : [];
	const requestLines = requests.map((item, requestIndex) => {
		const record = recordValue(item) ?? {};
		const tool = String(record.tool_name ?? '-');
		const summary = String(record.summary ?? compactValue(record.args ?? record.arguments ?? {}, 360));
		return `${requestIndex + 1}. ${tool} ${summary}`.trim();
	});
	return {
		id: `interrupt:${event.event_id}`,
		timestamp: event.timestamp,
		order: 10_000 + index,
		color: 'yellow',
		title: `Interrupt ${interruptType}`,
		body: requestLines.length ? requestLines.join('\n') : compactValue(payload, 1200),
		kind: 'message',
		role: 'interrupt',
		source: 'interrupt',
		turnId: null,
		eventType: event.event_type
	};
}

function schedulerEventTimelineItem(event: FactoryEvent, index: number): TimelineItem | null {
	const body = schedulerEventBody(event);
	if (!body) {
		return null;
	}
	return {
		id: `scheduler-event:${event.event_id}`,
		timestamp: event.timestamp,
		order: 30_000 + index,
		color: event.event_type.endsWith('failed') ? 'red' : 'magenta',
		title: schedulerEventTitle(event),
		body,
		kind: 'scheduler',
		role: 'scheduler',
		source: 'scheduler',
		turnId: null,
		eventType: event.event_type
	};
}

function schedulerEventTitle(event: FactoryEvent): string {
	if (event.event_type === 'scheduler_jobs_listed') {
		return 'Scheduler jobs';
	}
	if (event.event_type === 'scheduler_job_described') {
		const payload = recordValue(event.payload?.payload) ?? {};
		const job = recordValue(payload.job);
		return `Scheduler ${stringValue(job?.job_id) || stringValue(event.payload?.job_id) || '-'}`;
	}
	if (event.event_type === 'scheduler_runs_listed') {
		return 'Scheduler runs';
	}
	if (event.event_type === 'scheduler_job_auto_paused') {
		return 'Scheduler auto paused';
	}
	return `Scheduler ${stringValue(event.payload?.job_id) || '-'}`;
}

function schedulerEventBody(event: FactoryEvent): string {
	if (event.event_type === 'scheduler_jobs_listed') {
		const payload = recordValue(event.payload?.payload) ?? {};
		const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
		return jobs.length ? jobs.slice(0, 20).map(item => schedulerJobLine(recordValue(item))).filter(Boolean).join('\n') : 'No scheduler jobs';
	}
	if (event.event_type === 'scheduler_job_described') {
		const payload = recordValue(event.payload?.payload) ?? {};
		const job = recordValue(payload.job);
		const runs = Array.isArray(payload.recent_runs) ? payload.recent_runs : [];
		return [
			schedulerJobLine(job),
			...runs.slice(0, 8).map(item => schedulerRunLine(recordValue(item))).filter(Boolean)
		].filter((item): item is string => Boolean(item)).join('\n') || compactValue(event.payload, 1200);
	}
	if (event.event_type === 'scheduler_runs_listed') {
		const payload = recordValue(event.payload?.payload) ?? {};
		const runs = Array.isArray(payload.runs) ? payload.runs : [];
		return runs.length ? runs.slice(0, 20).map(item => schedulerRunLine(recordValue(item))).filter(Boolean).join('\n') : 'No scheduler runs';
	}
	if (event.event_type === 'scheduler_job_auto_paused') {
		const payload = event.payload ?? {};
		const detail = recordValue(payload.payload) ?? {};
		return [
			`job ${stringValue(payload.job_id) || '-'}`,
			stringValue(detail.reason) ? `reason: ${stringValue(detail.reason)}` : null,
			typeof numberValue(detail.consecutive_failures) === 'number' ? `consecutive failures: ${numberValue(detail.consecutive_failures)}` : null,
			typeof numberValue(detail.threshold) === 'number' ? `threshold: ${numberValue(detail.threshold)}` : null,
			stringValue(payload.report_path) ? `report: ${stringValue(payload.report_path)}` : null
		].filter((item): item is string => Boolean(item)).join('\n');
	}
	const payload = event.payload ?? {};
	return [
		stringValue(payload.task_content) ? `task: ${stringValue(payload.task_content)}` : null,
		stringValue(payload.completed_at) ? `completed: ${stringValue(payload.completed_at)}` : null,
		typeof numberValue(payload.completed_count) === 'number' ? `completed count: ${numberValue(payload.completed_count)}` : null,
		stringValue(payload.summary) ? `summary: ${stringValue(payload.summary)}` : null,
		stringValue(payload.error_summary) ? `error: ${stringValue(payload.error_summary)}` : null
	].filter((item): item is string => Boolean(item)).join('\n') || compactValue(payload, 1200);
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
		shortTimelineValue(stringValue(job.job_id), 10),
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
		shortTimelineValue(stringValue(run.run_id), 10),
		stringValue(run.status),
		stringValue(run.target_type),
		stringValue(run.completed_at) || stringValue(run.started_at) || stringValue(run.scheduled_at),
		shortTimelineValue(stringValue(run.error_summary) || stringValue(run.output_summary), 80)
	].filter(Boolean).join(' | ');
}

function knowledgeEventTimelineItem(event: FactoryEvent, index: number): TimelineItem | null {
	const body = knowledgeEventBody(event);
	if (!body) {
		return null;
	}
	return {
		id: `knowledge-event:${event.event_id}`,
		timestamp: event.timestamp,
		order: 35_000 + index,
		color: event.event_type.endsWith('failed') ? 'red' : 'blue',
		title: `Knowledge ${event.event_type.replace(/^knowledge_/, '').replaceAll('_', ' ')}`,
		body,
		kind: 'knowledge',
		role: 'knowledge',
		source: 'knowledge',
		turnId: null,
		eventType: event.event_type
	};
}

function knowledgeEventBody(event: FactoryEvent): string {
	if (event.event_type === 'knowledge_source_preview_available') {
		const preview = recordValue(event.payload?.preview);
		return [
			`source: ${stringValue(preview?.display_name) || stringValue(preview?.source_id) || '-'}`,
			`type: ${stringValue(preview?.source_type) || '-'}`,
			`mode: ${stringValue(preview?.mount_mode) || '-'}`,
			`documents: ${numberValue(preview?.estimated_documents) ?? 0}`,
			`requires embedding: ${preview?.requires_embedding ? 'yes' : 'no'}`,
			stringValue(preview?.uri) ? `path: ${stringValue(preview?.uri)}` : null
		].filter((item): item is string => Boolean(item)).join('\n');
	}
	const payload = event.payload ?? {};
	const counts = recordValue(payload.counts) ?? {};
	const error = recordValue(payload.error);
	return [
		`source: ${stringValue(payload.source_id) || '-'}`,
		stringValue(payload.mode) ? `mode: ${stringValue(payload.mode)}` : null,
		stringValue(payload.status) ? `status: ${stringValue(payload.status)}` : null,
		typeof numberValue(counts.documents_loaded) === 'number' ? `documents: ${numberValue(counts.documents_loaded)}` : null,
		typeof numberValue(counts.chunks_created) === 'number' ? `chunks: ${numberValue(counts.chunks_created)}` : null,
		stringValue(payload.report_path) ? `report: ${stringValue(payload.report_path)}` : null,
		error ? `error: ${stringValue(error.message) || compactValue(error, 300)}` : null
	].filter((item): item is string => Boolean(item)).join('\n') || compactValue(payload, 1200);
}

function turnIdForTranscript(item: TranscriptItem, index: number): string | null {
	const value = item.metadata?.turn_id ?? item.metadata?.turnId;
	if (typeof value === 'string' && value.trim()) {
		return value;
	}
	if (item.role === 'user') {
		return `user:${item.id}`;
	}
	return index > 0 ? `near:${index}` : null;
}

function toolTimelineBody(item: ToolActivity): string {
	const toolPayload = normalizeToolPayload(item.payload);
	const lines = [
		item.toolCallId ? `call ${shortTimelineValue(item.toolCallId, 18)}` : null,
		item.stageId || item.nodeId ? `node ${[item.stageId, item.nodeId].filter(Boolean).join(' / ')}` : null,
		item.approvalState ? `approval ${item.approvalState}` : null,
		toolPayload.exitCode !== null ? `exit ${toolPayload.exitCode}` : null,
		toolPayload.durationMs !== null ? `duration ${toolPayload.durationMs}ms` : null,
		toolPayload.argsPreview ? `args ${toolPayload.argsPreview}` : null,
		toolPayload.stdoutPreview ? `stdout ${previewTimelineMultiline(toolPayload.stdoutPreview)}` : null,
		toolPayload.stderrPreview ? `stderr ${previewTimelineMultiline(toolPayload.stderrPreview)}` : null,
		toolPayload.resultPreview ? `result ${previewTimelineMultiline(toolPayload.resultPreview)}` : null
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
	if (item.role === 'knowledge') {
		return item.title.replace(/^Knowledge \/ /, 'Knowledge ');
	}
	if (item.role === 'interrupt') {
		return item.title.replace(/^Interrupt \/ /, 'Interrupt ');
	}
	return item.title;
}

type RenderToolLifecycle = 'proposed' | 'approval' | 'started' | 'completed' | 'failed' | 'observed';

function normalizeToolPayload(payload: Record<string, unknown>): {
	toolName: string;
	argsPreview: string | null;
	resultPreview: string | null;
	stdoutPreview: string | null;
	stderrPreview: string | null;
	exitCode: number | null;
	durationMs: number | null;
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
		durationMs
	};
}

function lifecycleForToolEvent(eventType: FactoryEvent['event_type']): RenderToolLifecycle {
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

function labelForToolLifecycle(status: RenderToolLifecycle): string {
	const labels: Record<RenderToolLifecycle, string> = {
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
		job ? `job=${shortTimelineValue(job, 10)}` : null,
		typeof listedCount === 'number' ? `items=${listedCount}` : null,
		typeof completedCount === 'number' ? `count=${completedCount}` : null,
		typeof consecutiveFailures === 'number' ? `failures=${consecutiveFailures}` : null,
		typeof threshold === 'number' ? `threshold=${threshold}` : null,
		summary ? `summary=${shortTimelineValue(summary, 80)}` : null,
		error ? `error=${shortTimelineValue(error, 80)}` : null,
		report ? `report=${shortTimelineValue(report, 48)}` : null
	].filter((item): item is string => Boolean(item));
	return parts.join(' ');
}

function knowledgeActivityDetail(payload: Record<string, unknown>): string {
	const status = stringValue(payload.status);
	const mode = stringValue(payload.mode);
	const phase = stringValue(payload.phase);
	const source = stringValue(payload.source_id);
	const message = stringValue(payload.message);
	const error = recordValue(payload.error);
	const progress = recordValue(payload.progress);
	const counts = recordValue(payload.counts);
	const current = numberValue(progress?.current);
	const total = numberValue(progress?.total);
	const percent = numberValue(progress?.percent);
	const documents = numberValue(counts?.documents_loaded) ?? numberValue(counts?.documents_discovered);
	const chunks = numberValue(counts?.chunks_created);
	const parts = [
		status ? `status=${status}` : null,
		mode ? `mode=${mode}` : null,
		phase ? `phase=${phase}` : null,
		source ? `source=${shortTimelineValue(source, 16)}` : null,
		typeof percent === 'number' ? `${percent}%` : null,
		typeof current === 'number' && typeof total === 'number' ? `${current}/${total}` : null,
		typeof documents === 'number' ? `docs=${documents}` : null,
		typeof chunks === 'number' ? `chunks=${chunks}` : null,
		error ? `error=${shortTimelineValue(stringValue(error.message) || compactValue(error, 120), 80)}` : null,
		message ? shortTimelineValue(message, 80) : null
	].filter((item): item is string => Boolean(item));
	return parts.join(' ');
}

function errorMessageFromPayload(message: string | null, payload: Record<string, unknown>, fallback: string): string {
	const payloadMessage = stringValue(payload.message) || stringValue(payload.error) || stringValue(payload.error_message);
	if (payloadMessage) {
		return payloadMessage;
	}
	if (message && !isGenericFailureText(message)) {
		return message;
	}
	return fallback;
}

function isGenericFailureText(value: string): boolean {
	const normalized = value.trim().toLowerCase();
	return ['failed', 'run failed', 'error', 'unknown error'].includes(normalized);
}

function firstLine(value: string): string {
	return value.split('\n').find(line => line.trim())?.trim() ?? value;
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
	if (role === 'knowledge') {
		return 'blue';
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

function colorForKnowledgeStatus(status: string | null): ActivityColor {
	if (status === 'failed' || status === 'cancelled' || status === 'removed') {
		return 'red';
	}
	if (status === 'ready' || status === 'completed') {
		return 'green';
	}
	if (status === 'running' || status === 'indexing' || status === 'queued') {
		return 'cyan';
	}
	return 'blue';
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

function recordValue(value: unknown): Record<string, unknown> | undefined {
	return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function stringValue(value: unknown): string {
	return typeof value === 'string' ? value.trim() : '';
}

function numberValue(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
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

function compactValue(value: unknown, limit = 360): string {
	try {
		return JSON.stringify(value).replace(/\s+/g, ' ').slice(0, limit);
	} catch {
		return String(value).replace(/\s+/g, ' ').slice(0, limit);
	}
}
