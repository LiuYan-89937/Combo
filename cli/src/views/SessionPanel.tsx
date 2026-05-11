import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';

export function SessionPanel({state}: {state: FactoryUiState}) {
	if (!state.sessions.length) {
		return null;
	}
	return (
		<Box borderStyle="single" borderColor="magenta" paddingX={1} flexDirection="column">
			<Text bold>Sessions</Text>
			{state.sessions.slice(0, 8).map(session => (
				<Text key={String(session.session_id)}>
					{String(session.session_id)} mode={String(session.current_mode ?? '-')} updated={String(session.updated_at ?? '-')}
				</Text>
			))}
		</Box>
	);
}

