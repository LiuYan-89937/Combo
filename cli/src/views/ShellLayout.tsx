import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Pill} from './ui.js';

export function ShellLayout({state, children}: {state: FactoryUiState; children: React.ReactNode}) {
	const statusColor = state.runStatus === 'failed' ? 'red' : state.runStatus === 'running' ? 'green' : state.runStatus === 'interrupted' ? 'yellow' : 'gray';
	return (
		<Box flexDirection="column">
			<Box borderStyle="double" borderColor="cyan" paddingX={2} paddingY={1} flexDirection="column">
				<Box justifyContent="space-between">
					<Box>
						<Text bold color="cyan">FastAgentFactory</Text>
						<Text color="gray"> / TypeScript Frontend</Text>
					</Box>
					<Text color={state.ready ? 'green' : 'yellow'}>{state.ready ? 'ONLINE' : 'STARTING'}</Text>
				</Box>
				<Box marginTop={1}>
					<Pill label="session" value={shortId(state.sessionId)} />
					{state.sessionTitle && <Pill label="title" value={state.sessionTitle} color="white" />}
					<Pill label="mode" value={state.mode ?? '-'} color={state.mode ? 'cyan' : 'gray'} />
					<Pill label="run" value={state.runStatus} color={statusColor} />
					<Pill label="stop" value={state.stopAfterStage ?? 'off'} color="white" />
				</Box>
				<Box marginTop={1}>
					<Pill label="stage" value={state.currentStageId ?? '-'} color={state.currentStageId ? 'blue' : 'gray'} />
					<Pill label="node" value={state.currentNodeId ?? '-'} color={state.currentNodeId ? 'cyan' : 'gray'} />
					<Pill label="now" value={currentActivity(state)} color={statusColor} />
				</Box>
			</Box>
			{children}
		</Box>
	);
}

function shortId(value: string | null): string {
	if (!value) {
		return '-';
	}
	return value.length > 12 ? `${value.slice(0, 10)}...` : value;
}

function currentActivity(state: FactoryUiState): string {
	const latest = state.recentActivities.at(-1);
	if (!latest) {
		return state.ready ? 'ready' : 'starting';
	}
	const detail = latest.detail ? ` ${latest.detail}` : '';
	const value = `${latest.label}${detail}`;
	return value.length > 54 ? `${value.slice(0, 54)}...` : value;
}
