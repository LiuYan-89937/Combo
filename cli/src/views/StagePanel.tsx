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
	const assemblyReport = patch.assembly_validation_report as Record<string, unknown> | undefined;
	if (assemblyReport) {
		const attempts = (assemblyReport.attempts as Array<Record<string, unknown>> | undefined) ?? [];
		const latestAttempt = attempts.at(-1);
		lines.push(`assembly validation: ${String(assemblyReport.status ?? '-')}`);
		lines.push(`assembly attempts: ${String(attempts.length)}`);
		if (latestAttempt) {
			lines.push(`assembly latest: #${String(latestAttempt.attempt ?? '-')} ${String(latestAttempt.status ?? '-')}`);
			const errors = (latestAttempt.errors as string[] | undefined) ?? [];
			if (errors.length > 0) {
				lines.push(`assembly error: ${errors[0]}`);
			}
		}
	}
	if (patch.assembly_spec_draft_path) {
		lines.push(`assembly draft: ${String(patch.assembly_spec_draft_path)}`);
	}
	const errors = (patch.errors as Array<Record<string, unknown>> | undefined) ?? [];
	for (const item of errors.slice(-3)) {
		lines.push(`error: ${String(item.where ?? '-')} ${String(item.message ?? '')}`);
	}
	const modelActivity = (patch.model_activity as Array<Record<string, unknown>> | undefined) ?? [];
	for (const item of modelActivity.slice(-3)) {
		lines.push(`model: ${String(item.event_type ?? '-')} ${String(item.message ?? item.output_summary ?? '')}`);
	}
	if (!lines.length) {
		lines.push(JSON.stringify(patch).slice(0, 900));
	}
	return lines;
}
