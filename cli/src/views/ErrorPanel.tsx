import React from 'react';
import {Box, Text} from 'ink';

export function ErrorPanel({message}: {message: string | null}) {
	if (!message) {
		return null;
	}
	return (
		<Box borderStyle="round" borderColor="red" paddingX={1}>
			<Text color="red">{message}</Text>
		</Box>
	);
}

