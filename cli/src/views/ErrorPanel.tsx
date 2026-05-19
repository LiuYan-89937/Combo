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
				<ErrorItem key={`${item}-${index}`} value={item} />
			)) : <ErrorItem value={message ?? ''} />}
		</Box>
	);
}

function ErrorItem({value}: {value: string}) {
	const lines = value.split('\n').filter(line => line.trim());
	return (
		<Box flexDirection="column" marginTop={1}>
			{lines.map((line, index) => (
				<Text key={`${line}-${index}`} color="red">{line}</Text>
			))}
		</Box>
	);
}
