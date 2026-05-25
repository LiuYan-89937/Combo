import React from 'react';
import {Box, Text} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';

export function LiveStatusLine() {
	const ready = useStoreSelector(state => state.ready);
	const mode = useStoreSelector(state => state.mode);
	const sessionId = useStoreSelector(state => state.sessionId);
	const activeAgentPackage = useStoreSelector(state => state.activeAgentPackage);
	const activeAgentSessionId = useStoreSelector(state => state.activeAgentSessionId);
	const runStatus = useStoreSelector(state => state.runStatus);
	const currentStageId = useStoreSelector(state => state.currentStageId);
	const currentNodeId = useStoreSelector(state => state.currentNodeId);
	const contextWindow = useStoreSelector(state => state.contextWindow);
	const memoryActivity = useStoreSelector(state => state.memoryActivity);
	const contextActivity = useStoreSelector(state => state.contextActivity);
	const latestKnowledgeActivity = useStoreSelector(state => state.knowledgeActivities.at(-1) ?? null);
	const statusColor = runStatus === 'failed' ? 'red' : runStatus === 'running' ? 'green' : runStatus === 'interrupted' ? 'yellow' : 'gray';
	const parts = [
		ready ? 'online' : 'starting',
		mode ? modeLabel(mode) : 'home',
		`session ${shortId(sessionId)}`,
		mode === 'agent_package' ? `agent ${agentPackageLabel(activeAgentPackage)}` : null,
		mode === 'agent_package' ? `agent-session ${shortId(activeAgentSessionId)}` : null,
		`run ${runStatus}`,
		currentStageId ? `stage ${currentStageId}` : null,
		currentNodeId ? `node ${shortId(currentNodeId)}` : null
	].filter((item): item is string => Boolean(item));
	const activityParts = [
		memoryActivity.status !== 'idle' ? `memory ${memoryActivity.label}` : null,
		contextActivity.status !== 'idle' ? `context ${contextActivity.label}` : null,
		latestKnowledgeActivity ? `knowledge ${knowledgeStatusLabel(latestKnowledgeActivity)}` : null,
		contextWindow.updatedAt ? `ctx ${contextWindowSummary(contextWindow)}` : null
	].filter((item): item is string => Boolean(item));
	return (
		<Box flexDirection="column" marginBottom={1}>
			<Box>
				<Text color="cyan" bold>FastAgentFactory</Text>
				<Text color="gray">  </Text>
				<Text color={statusColor}>{parts.join('  ')}</Text>
			</Box>
			{activityParts.length > 0 && (
				<Box>
					<Text color="gray">{activityParts.join('  ')}</Text>
				</Box>
			)}
		</Box>
	);
}

function contextWindowSummary(contextWindow: {
	tokenCount: number | null;
	contextWindowTokens: number | null;
	compressionThresholdTokens: number | null;
	tokenCountMethod: string | null;
	error: string | null;
}): string {
	if (contextWindow.error) {
		return `unavailable ${truncate(contextWindow.error, 32)}`;
	}
	const count = contextWindow.tokenCount === null ? '?' : formatCompactNumber(contextWindow.tokenCount);
	const total = contextWindow.contextWindowTokens === null ? '?' : formatCompactNumber(contextWindow.contextWindowTokens);
	const threshold = contextWindow.compressionThresholdTokens === null ? '?' : formatCompactNumber(contextWindow.compressionThresholdTokens);
	return `${contextWindowBar(contextWindow)} ${count}/${total} compress@${threshold} ${tokenMethodLabel(contextWindow.tokenCountMethod)}`;
}

function contextWindowBar(contextWindow: {
	tokenCount: number | null;
	contextWindowTokens: number | null;
	compressionThresholdTokens: number | null;
}): string {
	const width = 14;
	if (contextWindow.tokenCount === null || !contextWindow.contextWindowTokens) {
		return `[${'?'.repeat(width)}]`;
	}
	const ratio = clamp(contextWindow.tokenCount / contextWindow.contextWindowTokens, 0, 1);
	const filled = Math.max(0, Math.min(width, Math.round(ratio * width)));
	const marker = thresholdMarker(contextWindow.compressionThresholdTokens, contextWindow.contextWindowTokens, width);
	const chars: string[] = Array.from({length: width}, (_, index) => index < filled ? '#' : '-');
	if (marker !== null) {
		chars[marker] = '|';
	}
	return `[${chars.join('')}]`;
}

function thresholdMarker(threshold: number | null, total: number | null, width: number): number | null {
	if (!threshold || !total || threshold <= 0 || total <= 0) {
		return null;
	}
	return Math.max(0, Math.min(width - 1, Math.round((threshold / total) * (width - 1))));
}

function modeLabel(value: string): string {
	return value === 'create_agent' ? 'create-agent' : value === 'agent_package' ? 'agent-package' : value;
}

function agentPackageLabel(value: Record<string, unknown> | null): string {
	const label = String(value?.agent_name ?? value?.agent_id ?? value?.package_id ?? '-');
	return truncate(label, 24);
}

function shortId(value: string | null): string {
	if (!value) {
		return '-';
	}
	return value.length > 12 ? `${value.slice(0, 10)}...` : value;
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

function tokenMethodLabel(method: string | null): string {
	if (method === 'provider_usage') {
		return 'usage';
	}
	if (method === 'model_tokenizer_messages_only') {
		return 'tokenizer';
	}
	return method ?? 'unknown';
}

function clamp(value: number, min: number, max: number): number {
	return Math.max(min, Math.min(max, value));
}

function truncate(value: string, limit: number): string {
	return value.length > limit ? `${value.slice(0, limit)}...` : value;
}

function knowledgeStatusLabel(activity: {
	sourceId: string | null;
	status: string | null;
	phase: string | null;
}): string {
	return [
		activity.sourceId ? truncate(activity.sourceId, 18) : null,
		activity.status ?? null,
		activity.phase ?? null
	].filter(Boolean).join(' ');
}
