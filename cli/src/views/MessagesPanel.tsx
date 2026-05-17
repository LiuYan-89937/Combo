import React from 'react';
import {Box, Text} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Section} from './ui.js';

export function MessagesPanel() {
	const transcript = useStoreSelector(state => state.transcript);
	if (!transcript.length) {
		return null;
	}
	const visible = transcript.slice(-30);
	return (
		<Section title={transcript.length > visible.length ? `Conversation (last ${visible.length}/${transcript.length})` : 'Conversation'} color="gray">
			{visible.map(item => (
				<Box key={item.id} flexDirection="column" marginBottom={1}>
					<Text color={colorForRole(item.role)} bold>
						{item.title}
						{item.active ? ' streaming' : ''}
					</Text>
					<Text>{trimContent(item.content)}</Text>
				</Box>
			))}
		</Section>
	);
}

function colorForRole(role: string): string {
	if (role === 'user') {
		return 'cyan';
	}
	if (role === 'assistant') {
		return 'green';
	}
	if (role === 'tool') {
		return 'yellow';
	}
	if (role === 'interrupt') {
		return 'magenta';
	}
	return 'gray';
}

function trimContent(value: string): string {
	const limit = 2400;
	return value.length > limit ? `...${value.slice(value.length - limit)}` : value;
}
