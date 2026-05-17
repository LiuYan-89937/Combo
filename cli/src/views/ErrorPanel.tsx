import React from 'react';
import {Box, Text} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';

export function ErrorPanel() {
	const message = useStoreSelector(state => state.lastError);
	const errors = useStoreSelector(state => state.errors);
	if (!message && !errors.length) {
		return null;
	}
	return (
		<Box borderStyle="round" borderColor="red" paddingX={1} flexDirection="column">
			<Text color="red" bold>Runtime Errors</Text>
			{errors.length ? errors.slice(-5).map((item, index) => (
				<Text key={`${item}-${index}`} color="red">{item}</Text>
			)) : <Text color="red">{message}</Text>}
		</Box>
	);
}
