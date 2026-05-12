import React from 'react';
import {Box, Text} from 'ink';

export function ErrorPanel({message, errors = []}: {message: string | null; errors?: string[]}) {
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
