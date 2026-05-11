import React from 'react';
import {Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Section} from './ui.js';

export function SessionPanel({state}: {state: FactoryUiState}) {
	if (!state.sessions.length) {
		return null;
	}
	return (
		<Section title="Sessions" color="magenta">
			{state.sessions.slice(0, 8).map(session => (
				<Text key={String(session.session_id)}>
					<Text color="cyan">{shortId(String(session.session_id))}</Text>
					{' '}
					mode={String(session.current_mode ?? '-')} chat={String(session.chat_turn_count ?? 0)} create={String(session.create_agent_turn_count ?? 0)}
				</Text>
			))}
		</Section>
	);
}

function shortId(value: string): string {
	return value.length > 12 ? `${value.slice(0, 10)}...` : value;
}
