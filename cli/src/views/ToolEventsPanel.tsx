import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Section} from './ui.js';

export function ToolEventsPanel({state}: {state: FactoryUiState}) {
	if (!state.toolActivities.length) {
		return null;
	}
	const filtered = filterToolActivities(state.toolActivities, state.toolGrep);
	return (
		<Section title={state.toolGrep ? `Tool Activity / grep: ${state.toolGrep}` : 'Tool Activity'} color="yellow">
			{filtered.slice(-8).map(event => (
				<Box key={event.activityKey} flexDirection="column" marginBottom={1} borderStyle="single" borderColor={colorFor(event.status)} paddingX={1}>
					<Text>
						<Text color={colorFor(event.status)} bold>{labelFor(event.status).padEnd(10)}</Text>
						<Text color="gray"> node </Text>
						{event.nodeId ?? '-'}
						<Text color="gray"> stage </Text>
						{event.stageId ?? '-'}
						<Text color="gray"> tool </Text>
						<Text bold>{event.toolName}</Text>
					</Text>
					{detailLines(event).map(line => (
						<Text key={line.label + line.value} color={line.color ?? 'gray'}>
							<Text color="gray">  {line.label}: </Text>
							{line.value}
						</Text>
					))}
				</Box>
			))}
			{!filtered.length && <Text color="gray">No tool activity matched current grep.</Text>}
		</Section>
	);
}

function filterToolActivities(events: FactoryUiState['toolActivities'], query: string) {
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
	if (status === 'completed' || status === 'observed') {
		return 'done';
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

function detailLines(event: FactoryUiState['toolActivities'][number]): Array<{label: string; value: string; color?: string}> {
	const lines: Array<{label: string; value: string; color?: string}> = [];
	if (event.toolCallId) {
		lines.push({label: 'call', value: event.toolCallId});
	}
	if (event.approvalState) {
		lines.push({label: 'approval', value: event.approvalState, color: event.approvalState === 'rejected' ? 'red' : 'yellow'});
	}
	if (event.argsPreview) {
		lines.push({label: 'args', value: event.argsPreview});
	}
	if (event.exitCode !== null) {
		lines.push({label: 'exit', value: String(event.exitCode), color: event.exitCode === 0 ? 'green' : 'red'});
	}
	if (event.durationMs !== null) {
		lines.push({label: 'duration', value: `${event.durationMs}ms`});
	}
	if (event.stdoutPreview) {
		lines.push({label: 'stdout', value: event.stdoutPreview, color: 'white'});
	}
	if (event.stderrPreview) {
		lines.push({label: 'stderr', value: event.stderrPreview, color: 'red'});
	}
	if (event.resultPreview) {
		lines.push({label: 'result', value: event.resultPreview, color: event.status === 'failed' ? 'red' : 'gray'});
	}
	if (!lines.length) {
		lines.push({label: 'payload', value: compact(event.payload)});
	}
	return lines;
}

function compact(value: unknown): string {
	return JSON.stringify(value).replace(/\s+/g, ' ').slice(0, 320);
}
