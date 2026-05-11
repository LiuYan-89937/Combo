import React from 'react';
import {Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Section} from './ui.js';

export function StagePanel({state}: {state: FactoryUiState}) {
	const latest = state.debugPatches.at(-1);
	if (!latest) {
		return null;
	}
	const patch = (latest.payload?.patch ?? latest.payload ?? {}) as Record<string, unknown>;
	return (
		<Section title="Latest Runtime Patch" color="cyan">
			<Text>
				<Text color="gray">node </Text>
				{latest.node_id ?? '-'}
				<Text color="gray">  stage </Text>
				{latest.stage_id ?? '-'}
			</Text>
			{summaryLines(patch).map(line => (
				<Text key={line}>{line}</Text>
			))}
		</Section>
	);
}

function summaryLines(patch: Record<string, unknown>): string[] {
	const lines: string[] = [];
	if (patch.current_stage) {
		lines.push(`current_stage: ${String(patch.current_stage)}`);
	}
	const stageLog = (patch.stage_log as Array<Record<string, unknown>> | undefined) ?? [];
	for (const item of stageLog.slice(-3)) {
		lines.push(`${String(item.stage_id ?? '-')}: ${String(item.status ?? '-')} ${String(item.message ?? '')}`);
	}
	const resourcePlan = patch.resource_condition_plan as Record<string, unknown> | undefined;
	if (resourcePlan) {
		lines.push(`resource status: ${String(resourcePlan.status ?? '-')}`);
		lines.push(`resource file: ${String(resourcePlan.resource_file_path ?? '-')}`);
	}
	if (!lines.length) {
		lines.push(JSON.stringify(patch).slice(0, 900));
	}
	return lines;
}
