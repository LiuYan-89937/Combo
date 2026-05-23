import React from 'react';
import {Box, Text} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Pill} from './ui.js';

export function ShellLayout({children}: {children: React.ReactNode}) {
	const ready = useStoreSelector(state => state.ready);
	const sessionId = useStoreSelector(state => state.sessionId);
	const sessionTitle = useStoreSelector(state => state.sessionTitle);
	const mode = useStoreSelector(state => state.mode);
	const activeAgentPackage = useStoreSelector(state => state.activeAgentPackage);
	const activeAgentSessionId = useStoreSelector(state => state.activeAgentSessionId);
	const runStatus = useStoreSelector(state => state.runStatus);
	const stopAfterStage = useStoreSelector(state => state.stopAfterStage);
	const currentStageId = useStoreSelector(state => state.currentStageId);
	const currentNodeId = useStoreSelector(state => state.currentNodeId);
	const currentNodeLabel = useStoreSelector(state => currentNodeLabelFromState(state.currentNodeId, state.nodeStatuses));
	const currentActivity = useStoreSelector(state => currentActivityFromState(state.ready, state.recentActivities));
	const memoryStatus = useStoreSelector(state => state.memoryActivity.status);
	const memoryLabel = useStoreSelector(state => state.memoryActivity.label);
	const memoryDetail = useStoreSelector(state => state.memoryActivity.detail);
	const contextStatus = useStoreSelector(state => state.contextActivity.status);
	const contextLabel = useStoreSelector(state => state.contextActivity.label);
	const contextDetail = useStoreSelector(state => state.contextActivity.detail);
	const statusColor = runStatus === 'failed' ? 'red' : runStatus === 'running' ? 'green' : runStatus === 'interrupted' ? 'yellow' : 'gray';
	return (
		<Box flexDirection="column">
			<Box borderStyle="double" borderColor="cyan" paddingX={2} paddingY={1} flexDirection="column">
				<Box justifyContent="space-between">
					<Box>
						<Text bold color="cyan">FastAgentFactory</Text>
						<Text color="gray"> / TypeScript Frontend</Text>
					</Box>
					<Text color={ready ? 'green' : 'yellow'}>{ready ? 'ONLINE' : 'STARTING'}</Text>
				</Box>
				<Box marginTop={1}>
					<Pill label="session" value={shortId(sessionId)} />
					{sessionTitle && <Pill label="title" value={sessionTitle} color="white" />}
					<Pill label="mode" value={mode ?? '-'} color={mode ? 'cyan' : 'gray'} />
					{mode === 'agent_package' && <Pill label="agent" value={agentPackageLabel(activeAgentPackage)} color="cyan" />}
					{mode === 'agent_package' && <Pill label="agent-session" value={shortId(activeAgentSessionId)} color="white" />}
					<Pill label="run" value={runStatus} color={statusColor} />
					<Pill label="stop" value={stopAfterStage ?? 'off'} color="white" />
					{memoryStatus !== 'idle' && <Pill label="memory" value={memoryHint(memoryLabel, memoryDetail)} color={memoryColor(memoryStatus)} />}
					{contextStatus !== 'idle' && <Pill label="context" value={contextHint(contextLabel, contextDetail)} color={contextColor(contextStatus)} />}
				</Box>
				<Box marginTop={1}>
					<Pill label="stage" value={currentStageId ?? '-'} color={currentStageId ? 'blue' : 'gray'} />
					<Pill label="node" value={currentNodeLabel} color={currentNodeId ? 'cyan' : 'gray'} />
					<Pill label="now" value={currentActivity} color={statusColor} />
				</Box>
			</Box>
			{children}
		</Box>
	);
}

function memoryHint(label: string, detail: string | null): string {
	const value = detail ? `${label} ${detail}` : label;
	return value.length > 38 ? `${value.slice(0, 38)}...` : value;
}

function memoryColor(status: string): string {
	if (status === 'failed') {
		return 'red';
	}
	if (status === 'completed') {
		return 'green';
	}
	return 'yellow';
}

function contextHint(label: string, detail: string | null): string {
	const value = detail ? `${label} ${detail}` : label;
	return value.length > 38 ? `${value.slice(0, 38)}...` : value;
}

function contextColor(status: string): string {
	if (status === 'failed') {
		return 'red';
	}
	if (status === 'completed') {
		return 'green';
	}
	return 'yellow';
}

function shortId(value: string | null): string {
	if (!value) {
		return '-';
	}
	return value.length > 12 ? `${value.slice(0, 10)}...` : value;
}

function agentPackageLabel(value: Record<string, unknown> | null): string {
	if (!value) {
		return '-';
	}
	const label = String(value.agent_name ?? value.agent_id ?? value.package_id ?? '-');
	return label.length > 24 ? `${label.slice(0, 22)}...` : label;
}

function currentNodeLabelFromState(currentNodeId: string | null, nodeStatuses: Record<string, {label: string | null}>): string {
	if (!currentNodeId) {
		return '-';
	}
	const node = nodeStatuses[currentNodeId];
	return node?.label ?? currentNodeId;
}

function currentActivityFromState(ready: boolean, recentActivities: Array<{label: string; detail: string}>): string {
	const latest = recentActivities.at(-1);
	if (!latest) {
		return ready ? 'ready' : 'starting';
	}
	const detail = latest.detail ? ` ${latest.detail}` : '';
	const value = `${latest.label}${detail}`;
	return value.length > 54 ? `${value.slice(0, 54)}...` : value;
}
