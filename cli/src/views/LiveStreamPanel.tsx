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
	const activeCount = streams.filter(stream => stream.active).length;
	return (
		<Section title={latest.active ? `Live Model Stream${activeCount > 1 ? ` (${activeCount})` : ''}` : 'Last Model Output'} color={latest.active ? 'green' : 'gray'}>
			<Text color="gray">
				node {latest.nodeId ?? '-'}  stream {shortId(latest.streamId)}  {latest.active ? 'receiving tokens' : `completed ${latest.completedAt ?? ''}`}
			</Text>
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

function shortId(value: string): string {
	return value.length > 12 ? `${value.slice(0, 10)}...` : value;
}
