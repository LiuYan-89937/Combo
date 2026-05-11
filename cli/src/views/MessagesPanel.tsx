import React from 'react';
import {Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Section} from './ui.js';

export function MessagesPanel({state}: {state: FactoryUiState}) {
	if (!state.logs.length) {
		return null;
	}
	return (
		<Section title="Event Log" color="gray">
			{state.logs.slice(-8).map((line, index) => (
				<Text key={`${line}-${index}`} color="gray">{line}</Text>
			))}
		</Section>
	);
}
