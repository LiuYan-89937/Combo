import type {
	ActivityColor,
	KnowledgeActivity,
	RuntimeState,
	SchedulerActivity,
	TimelineItem,
	ToolActivity,
	TranscriptItem
} from './runtimeStore.js';

export function withTimelineItems(state: RuntimeState): RuntimeState {
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
	const toolItems = state.toolActivities.slice(-30).map((item, index) => toolTimelineItem(item, index));
	const schedulerItems = state.schedulerActivities
		.filter(item => !['scheduler_feedback_completed', 'scheduler_feedback_failed'].includes(item.eventType))
		.slice(-16)
		.map((item, index) => schedulerTimelineItem(item, index));
	const knowledgeItems = state.knowledgeActivities
		.slice(-16)
		.map((item, index) => knowledgeTimelineItem(item, index));
	const activityItems = state.mode === 'create_agent'
		? state.recentActivities
			.filter(item => !item.eventType.startsWith('tool_') && !item.eventType.startsWith('scheduler_') && !item.eventType.startsWith('knowledge_'))
			.slice(-18)
			.map((item, index) => ({
				id: `activity:${item.activityKey}`,
				timestamp: item.timestamp,
				order: 40_000 + index,
				color: item.color,
				title: item.label,
				body: [item.stageId, item.nodeId, item.detail].filter(Boolean).join('  '),
				kind: 'activity' as const,
				role: null,
				source: 'runtime_activity' as const,
				turnId: null,
				eventType: item.eventType
			}))
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
	return [...transcriptItems, ...toolItems, ...schedulerItems, ...knowledgeItems, ...activityItems, ...errorItems]
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
			item.detail || null,
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
			item.detail || null,
			item.reportPath ? `report ${item.reportPath}` : null
		].filter((value): value is string => Boolean(value)).join('\n'),
		kind: 'knowledge',
		role: 'knowledge',
		source: 'knowledge',
		turnId: null,
		eventType: item.eventType
	};
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
	if (item.role === 'knowledge') {
		return item.title.replace(/^Knowledge \/ /, 'Knowledge ');
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
