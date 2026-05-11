import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';

export function StagePanel({state}: {state: FactoryUiState}) {
	const latest = state.stageDeltas.at(-1);
	if (!latest) {
		return null;
	}
	return (
		<Box borderStyle="single" borderColor="cyan" paddingX={1} flexDirection="column">
			<Text bold>Latest Stage Delta</Text>
			<Text>node: {latest.node_id ?? '-'}</Text>
			<Text>stage: {latest.stage_id ?? '-'}</Text>
			<Text>{JSON.stringify(latest.payload?.patch ?? latest.payload).slice(0, 1200)}</Text>
		</Box>
	);
}

