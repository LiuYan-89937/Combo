import React from 'react';
import {Box, Text} from 'ink';
import {type ToolActivity} from '../state/runtimeStore.js';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Section} from './ui.js';

type DisplayLine = {
	label: string;
	value: string;
	color?: string;
};

type ToolTab = {
	id: 'overview' | 'args' | 'output' | 'observation';
	label: string;
	lines: DisplayLine[];
	empty?: string;
};

export function ToolEventsPanel() {
	const toolActivities = useStoreSelector(state => state.toolActivities);
	const toolGrep = useStoreSelector(state => state.toolGrep);
	const pendingInterrupt = useStoreSelector(state => state.pendingInterrupt);
	if (!toolActivities.length) {
		return null;
	}
	const filtered = filterToolActivities(
		filterPendingApprovalActivities(toolActivities, pendingApprovalToolCallIds(pendingInterrupt)),
		toolGrep
	);
	const visible = filtered.slice(-6);
	return (
		<Section title={toolGrep ? `Tool Activity / grep: ${toolGrep}` : 'Tool Activity'} color="yellow">
			{filtered.length > visible.length && (
				<Text color="gray">{filtered.length - visible.length} older tool calls collapsed</Text>
			)}
			{visible.map((event, index) => (
				<ToolCard
					key={event.activityKey}
					event={event}
					expanded={shouldExpand(event, index, visible.length)}
				/>
			))}
			{!filtered.length && <Text color="gray">No tool activity matched current grep.</Text>}
		</Section>
	);
}

function pendingApprovalToolCallIds(event: {payload?: Record<string, unknown>; event_type?: string} | null): Set<string> {
	if (!event || String(event.payload?.type ?? event.event_type ?? '') !== 'tool_approval') {
		return new Set();
	}
	const requests = event.payload?.requests;
	if (!Array.isArray(requests)) {
		return new Set();
	}
	return new Set(
		requests
			.map(item => item && typeof item === 'object' && !Array.isArray(item) ? String((item as Record<string, unknown>).tool_call_id ?? '') : '')
			.filter(Boolean)
	);
}

function filterPendingApprovalActivities(events: ToolActivity[], pendingToolCallIds: Set<string>): ToolActivity[] {
	if (!pendingToolCallIds.size) {
		return events;
	}
	return events.filter(event => {
		if (event.status !== 'approval' || event.approvalState !== 'pending') {
			return true;
		}
		return !event.toolCallId || !pendingToolCallIds.has(event.toolCallId);
	});
}

function ToolCard({event, expanded}: {event: ToolActivity; expanded: boolean}) {
	const color = colorFor(event.status);
	const status = labelFor(event.status);
	const summary = cardSummary(event);
	return (
		<Box flexDirection="column" marginBottom={1} borderStyle="round" borderColor={color} paddingX={1}>
			<Box>
				<Text color={color} bold>{expanded ? '▾' : '▸'} {status}</Text>
				<Text color="gray">  </Text>
				<Text bold>{event.toolName}</Text>
				{event.approvalState && (
					<>
						<Text color="gray">  approval </Text>
						<Text color={approvalColor(event.approvalState)}>{approvalLabel(event.approvalState)}</Text>
					</>
				)}
				{event.exitCode !== null && (
					<>
						<Text color="gray">  exit </Text>
						<Text color={event.exitCode === 0 ? 'green' : 'red'}>{event.exitCode}</Text>
					</>
				)}
			</Box>
			<Text color="gray">
				{event.stageId ?? '-'} / {event.nodeId ?? '-'} {event.toolCallId ? ` call ${shortId(event.toolCallId)}` : ''}
			</Text>
			{summary && <Text color="gray">{summary}</Text>}
			{expanded ? <ExpandedTool event={event} /> : null}
		</Box>
	);
}

function ExpandedTool({event}: {event: ToolActivity}) {
	const tabs = tabsFor(event);
	const activeTab = preferredTab(event, tabs);
	return (
		<Box flexDirection="column" marginTop={1}>
			<Box>
				{tabs.map(tab => (
					<Text
						key={tab.id}
						color={tab.id === activeTab.id ? 'black' : 'yellow'}
						backgroundColor={tab.id === activeTab.id ? 'yellow' : undefined}
					>
						{` ${tab.label} `}
					</Text>
				))}
			</Box>
			<Box flexDirection="column" marginTop={1}>
				{activeTab.lines.length ? activeTab.lines.map(line => (
					<Text key={`${line.label}:${line.value}`} color={line.color ?? 'white'}>
						<Text color="gray">{line.label}: </Text>
						{line.value}
					</Text>
				)) : <Text color="gray">{activeTab.empty ?? 'No detail available.'}</Text>}
			</Box>
		</Box>
	);
}

function tabsFor(event: ToolActivity): ToolTab[] {
	const tabs: ToolTab[] = [
		{ id: 'overview', label: 'Overview', lines: overviewLines(event), empty: 'Waiting for tool lifecycle updates.' },
		{ id: 'args', label: 'Args', lines: argumentLines(event), empty: 'This tool call has no visible arguments.' },
		{ id: 'output', label: 'Output', lines: outputLines(event), empty: 'The tool has not produced output yet.' },
		{ id: 'observation', label: 'Observation', lines: observationLines(event), empty: 'No model-facing observation yet.' }
	];
	return tabs.filter(tab => tab.id === 'overview' || tab.lines.length > 0);
}

function preferredTab(event: ToolActivity, tabs: ToolTab[]): ToolTab {
	const order: ToolTab['id'][] = event.status === 'failed'
		? ['output', 'observation', 'overview', 'args']
		: event.status === 'observed' || event.status === 'completed'
			? ['output', 'observation', 'overview', 'args']
			: event.status === 'approval'
				? ['args', 'overview', 'observation', 'output']
				: ['overview', 'args', 'output', 'observation'];
	for (const id of order) {
		const tab = tabs.find(item => item.id === id && (item.id === 'overview' || item.lines.length > 0));
		if (tab) {
			return tab;
		}
	}
	return tabs[0] ?? {id: 'overview', label: 'Overview', lines: []};
}

function overviewLines(event: ToolActivity): DisplayLine[] {
	const lines: DisplayLine[] = [];
	if (event.toolCallId) {
		lines.push({label: 'call', value: event.toolCallId});
	}
	lines.push({label: 'status', value: labelFor(event.status), color: colorFor(event.status)});
	if (event.approvalState) {
		lines.push({label: 'approval', value: approvalLabel(event.approvalState), color: approvalColor(event.approvalState)});
	}
	if (event.exitCode !== null) {
		lines.push({label: 'exit', value: String(event.exitCode), color: event.exitCode === 0 ? 'green' : 'red'});
	}
	if (event.durationMs !== null) {
		lines.push({label: 'duration', value: `${event.durationMs}ms`});
	}
	const summary = cardSummary(event);
	if (summary) {
		lines.push({label: 'summary', value: summary, color: event.status === 'failed' ? 'red' : 'gray'});
	}
	return lines;
}

function argumentLines(event: ToolActivity): DisplayLine[] {
	const args = payloadArguments(event.payload);
	return fieldLines(args, {fallbackLabel: 'arguments', maxLines: 12});
}

function outputLines(event: ToolActivity): DisplayLine[] {
	const lines: DisplayLine[] = [];
	if (event.stdoutPreview) {
		lines.push({label: 'stdout', value: multilinePreview(event.stdoutPreview), color: 'white'});
	}
	if (event.stderrPreview) {
		lines.push({label: 'stderr', value: multilinePreview(event.stderrPreview), color: 'red'});
	}
	if (event.resultPreview) {
		lines.push({label: 'result', value: multilinePreview(event.resultPreview), color: event.status === 'failed' ? 'red' : 'white'});
	}
	if (event.exitCode !== null) {
		lines.push({label: 'exit', value: String(event.exitCode), color: event.exitCode === 0 ? 'green' : 'red'});
	}
	return lines;
}

function observationLines(event: ToolActivity): DisplayLine[] {
	const observation = recordValue(event.payload.observation);
	const result = parseMaybeJson(event.payload.result ?? event.payload.output ?? event.payload.content);
	const resultRecord = recordValue(result);
	const nestedObservation = recordValue(resultRecord?.type === 'tool_observation' ? resultRecord : resultRecord?.observation);
	const source = observation ?? nestedObservation;
	const lines = fieldLines(source, {fallbackLabel: 'observation', maxLines: 10});
	if (event.approvalState) {
		return [{label: 'approval', value: approvalLabel(event.approvalState), color: approvalColor(event.approvalState)}, ...lines];
	}
	return lines;
}

function shouldExpand(event: ToolActivity, index: number, visibleLength: number): boolean {
	return index >= visibleLength - 2 || event.status === 'approval' || event.status === 'started' || event.status === 'failed';
}

function cardSummary(event: ToolActivity): string {
	return trimOneLine(event.resultPreview ?? event.stdoutPreview ?? event.stderrPreview ?? event.argsPreview ?? '', 180);
}

function filterToolActivities(events: ToolActivity[], query: string) {
	const normalized = query.trim().toLowerCase();
	if (!normalized) {
		return events;
	}
	return events.filter(event => event.searchText.toLowerCase().includes(normalized));
}

function labelFor(status: string): string {
	if (status === 'proposed') {
		return 'proposed';
	}
	if (status === 'approval') {
		return 'approval';
	}
	if (status === 'started') {
		return 'running';
	}
	if (status === 'completed') {
		return 'completed';
	}
	if (status === 'observed') {
		return 'observed';
	}
	if (status === 'failed') {
		return 'failed';
	}
	return status;
}

function colorFor(status: string): string {
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

function approvalLabel(state: string): string {
	if (state === 'approved') {
		return 'approved';
	}
	if (state === 'rejected') {
		return 'denied';
	}
	if (state === 'custom') {
		return 'revision requested';
	}
	if (state === 'trusted') {
		return 'trusted';
	}
	return 'pending';
}

function approvalColor(state: string): string {
	if (state === 'approved') {
		return 'green';
	}
	if (state === 'rejected') {
		return 'red';
	}
	if (state === 'custom') {
		return 'cyan';
	}
	if (state === 'trusted') {
		return 'green';
	}
	return 'yellow';
}

function fieldLines(value: unknown, {fallbackLabel, maxLines}: {fallbackLabel: string; maxLines: number}): DisplayLine[] {
	if (value === undefined || value === null || value === '') {
		return [];
	}
	if (typeof value !== 'object' || Array.isArray(value)) {
		return [{label: fallbackLabel, value: formatValue(value, 360)}];
	}
	const entries = Object.entries(value as Record<string, unknown>)
		.filter(([, item]) => item !== undefined)
		.slice(0, maxLines);
	const lines = entries.map(([key, item]) => ({label: key, value: formatValue(item, 360)}));
	if (Object.keys(value as Record<string, unknown>).length > maxLines) {
		lines.push({label: 'more', value: `${Object.keys(value as Record<string, unknown>).length - maxLines} fields collapsed`});
	}
	return lines;
}

function payloadArguments(payload: Record<string, unknown>): unknown {
	return payload.arguments ?? payload.args ?? payload.tool_args ?? recordValue(payload.message)?.args;
}

function formatValue(value: unknown, limit: number): string {
	if (typeof value === 'string') {
		return trimOneLine(value, limit);
	}
	if (typeof value === 'number' || typeof value === 'boolean') {
		return String(value);
	}
	if (value === null) {
		return 'null';
	}
	if (Array.isArray(value)) {
		if (value.every(item => typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean')) {
			return trimOneLine(value.join(', '), limit);
		}
		return `${value.length} item${value.length === 1 ? '' : 's'}`;
	}
	const record = recordValue(value);
	if (record) {
		const keys = Object.keys(record);
		const preview = keys.slice(0, 4).map(key => `${key}=${formatValue(record[key], 80)}`).join(', ');
		return trimOneLine(preview ? `{ ${preview}${keys.length > 4 ? ', ...' : ''} }` : '{}', limit);
	}
	return trimOneLine(String(value), limit);
}

function multilinePreview(value: string): string {
	const trimmed = value.replace(/\r/g, '').trim();
	const lines = trimmed.split('\n');
	if (lines.length <= 8) {
		return trimmed.length > 900 ? `${trimmed.slice(0, 900)}...` : trimmed;
	}
	return `${lines.slice(0, 8).join('\n')}\n... ${lines.length - 8} more lines`;
}

function trimOneLine(value: string, limit: number): string {
	const normalized = value.replace(/\s+/g, ' ').trim();
	return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
	return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function parseMaybeJson(value: unknown): unknown {
	if (typeof value !== 'string') {
		return value;
	}
	const trimmed = value.trim();
	if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
		return value;
	}
	try {
		return JSON.parse(trimmed);
	} catch {
		return value;
	}
}

function shortId(value: string): string {
	return value.length > 16 ? `${value.slice(0, 14)}...` : value;
}
