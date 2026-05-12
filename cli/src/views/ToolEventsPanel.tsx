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
			{filtered.slice(-10).map((event, index) => (
				<Box key={`${event.eventType}-${index}`} flexDirection="column" marginBottom={1}>
					<Text>
						<Text color={colorFor(event.eventType)}>{labelFor(event.eventType).padEnd(11)}</Text>
						<Text color="gray"> node </Text>
						{event.nodeId ?? '-'}
						<Text color="gray"> tool </Text>
						{toolName(event.payload)}
					</Text>
					{detailLines(event.payload).map(line => (
						<Text key={line} color="gray">  {line}</Text>
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
	return events.filter(event => searchableText(event.payload).toLowerCase().includes(normalized));
}

function labelFor(eventType: string): string {
	if (eventType.endsWith('proposed')) {
		return 'proposed';
	}
	if (eventType.endsWith('started')) {
		return 'started';
	}
	if (eventType.endsWith('completed')) {
		return 'completed';
	}
	if (eventType.endsWith('failed')) {
		return 'failed';
	}
	if (eventType.includes('observation')) {
		return 'observation';
	}
	return eventType;
}

function colorFor(eventType: string): string {
	if (eventType.endsWith('failed')) {
		return 'red';
	}
	if (eventType.endsWith('completed') || eventType.includes('observation')) {
		return 'green';
	}
	return 'yellow';
}

function toolName(payload: Record<string, unknown>): string {
	if (payload.tool_name) {
		return String(payload.tool_name);
	}
	const resourceCheck = payload.resource_check as Record<string, unknown> | undefined;
	if (resourceCheck) {
		return String(resourceCheck.tool_name ?? '-');
	}
	if (payload.name) {
		return String(payload.name);
	}
	const message = payload.message as Record<string, unknown> | undefined;
	if (message) {
		return String(message.name ?? '-');
	}
	return '-';
}

function detailLines(payload: Record<string, unknown>): string[] {
	const lines: string[] = [];
	if (payload.arguments) {
		lines.push(`args: ${compact(payload.arguments)}`);
	}
	if (payload.summary) {
		lines.push(`summary: ${String(payload.summary)}`);
	}
	if (payload.revision_guidance) {
		lines.push(`revision: ${String(payload.revision_guidance)}`);
	}
	const resourceCheck = payload.resource_check as Record<string, unknown> | undefined;
	if (resourceCheck) {
		lines.push(`status: ${String(resourceCheck.status ?? '-')}`);
		lines.push(`result: ${String(resourceCheck.result_summary ?? '').slice(0, 260)}`);
	}
	const message = payload.message as Record<string, unknown> | undefined;
	if (message) {
		lines.push(`tool_call_id: ${String(message.tool_call_id ?? '-')}`);
		lines.push(`result: ${String(message.content ?? '').slice(0, 900)}`);
	}
	if (!lines.length) {
		lines.push(compact(payload));
	}
	return lines;
}

function compact(value: unknown): string {
	return JSON.stringify(value).replace(/\s+/g, ' ').slice(0, 320);
}

function searchableText(payload: Record<string, unknown>): string {
	return JSON.stringify(payload);
}
