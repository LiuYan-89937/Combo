import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryEvent} from '../protocol.js';

export function ResourceInputPrompt({event}: {event: FactoryEvent | null}) {
	if (!event || event.type !== 'resource_input_requested') {
		return null;
	}
	const payload = event.payload ?? {};
	const requirements = (payload.requirements as Array<Record<string, unknown>>) ?? [];
	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold>Resource Input Required</Text>
			<Text>{String(payload.message ?? '')}</Text>
			{requirements.map((item, index) => (
				<Text key={String(item.requirement_id ?? index)}>
					{index + 1}. {String(item.requirement_id ?? '-')} {String(item.description ?? '')}
				</Text>
			))}
			<Text color="yellow">直接输入自然语言资源补充。</Text>
		</Box>
	);
}
