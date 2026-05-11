import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';

export function ShellLayout({state, children}: {state: FactoryUiState; children: React.ReactNode}) {
	return (
		<Box flexDirection="column">
			<Box borderStyle="round" borderColor="cyan" paddingX={1}>
				<Text bold>FastAgentFactory TS CLI</Text>
				<Text>  session: {state.sessionId ?? '-'}</Text>
				<Text>  mode: {state.mode ?? '-'}</Text>
				<Text>  stop: {state.stopAfterStage ?? 'off'}</Text>
			</Box>
			{children}
		</Box>
	);
}

