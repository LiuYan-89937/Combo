import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState, type NodeStatus} from '../state/factoryStore.js';
import {Section} from './ui.js';

export function StagePanel({state}: {state: FactoryUiState}) {
	const node = currentNode(state);
	if (!node) {
		return null;
	}
	return (
		<Section title="Current Node" color="cyan">
			<Box flexDirection="column">
				<Text>
					<Text color="gray">node </Text>
					<Text bold>{node.label ?? node.nodeId}</Text>
					<Text color="gray">  kind </Text>
					{node.kind ?? '-'}
					<Text color="gray">  status </Text>
					<Text color={statusColor(node.status)}>{node.status}</Text>
				</Text>
				<Text color="gray">
					stage {node.stageId ?? '-'}  started {node.startedAt ?? '-'}
				</Text>
				{node.message && <Text>{node.message}</Text>}
				{summaryLines(node).map(line => (
					<Text key={line} color="gray">{line}</Text>
				))}
			</Box>
		</Section>
	);
}

function currentNode(state: FactoryUiState): NodeStatus | null {
	if (state.currentNodeId && state.nodeStatuses[state.currentNodeId]) {
		return state.nodeStatuses[state.currentNodeId];
	}
	const nodes = Object.values(state.nodeStatuses);
	return nodes.at(-1) ?? null;
}

function summaryLines(node: NodeStatus): string[] {
	const lines: string[] = [];
	const outputSummary = stringValue(node.payload.output_summary);
	if (outputSummary) {
		lines.push(`output: ${trim(outputSummary, 240)}`);
	}
	const error = stringValue(node.payload.error) || stringValue(node.payload.message);
	if (node.status === 'failed' && error) {
		lines.push(`error: ${trim(error, 240)}`);
	}
	return lines;
}

function statusColor(status: string): string {
	if (status === 'failed') {
		return 'red';
	}
	if (status === 'completed') {
		return 'green';
	}
	return 'cyan';
}

function stringValue(value: unknown): string {
	return typeof value === 'string' ? value.trim() : '';
}

function trim(value: string, limit: number): string {
	const normalized = value.replace(/\s+/g, ' ').trim();
	return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}
