import React from 'react';
import {Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Section} from './ui.js';

export function LiveStreamPanel({state}: {state: FactoryUiState}) {
	const streams = Object.values(state.modelStreams);
	const latest = streams.at(-1);
	if (!latest?.content) {
		return null;
	}
	return (
		<Section title={latest.active ? 'Live Model Stream' : 'Last Model Output'} color={latest.active ? 'green' : 'gray'}>
			<Text color="gray">node {latest.nodeId ?? '-'}</Text>
			<Text>{trimStream(latest.content)}</Text>
		</Section>
	);
}

function trimStream(value: string): string {
	const limit = 5000;
	if (value.length <= limit) {
		return value;
	}
	return `...${value.slice(value.length - limit)}`;
}
