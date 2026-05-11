import React from 'react';
import {Box, Text} from 'ink';

export function ChatView({streamingText}: {streamingText: string}) {
	if (!streamingText) {
		return null;
	}
	return (
		<Box borderStyle="single" borderColor="green" paddingX={1} flexDirection="column">
			<Text bold>Model Stream</Text>
			<Text>{streamingText}</Text>
		</Box>
	);
}

