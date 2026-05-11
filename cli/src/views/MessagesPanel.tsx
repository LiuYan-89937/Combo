import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';

export function MessagesPanel({state}: {state: FactoryUiState}) {
	if (!state.logs.length) {
		return null;
	}
	return (
		<Box borderStyle="single" borderColor="gray" paddingX={1} flexDirection="column">
			<Text bold>Events</Text>
			{state.logs.slice(-8).map((line, index) => (
				<Text key={`${line}-${index}`}>{line}</Text>
			))}
		</Box>
	);
}

