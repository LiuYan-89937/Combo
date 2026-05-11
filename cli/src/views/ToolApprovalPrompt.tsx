import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryEvent} from '../protocol.js';

export function ToolApprovalPrompt({event}: {event: FactoryEvent | null}) {
	if (!event || event.payload?.type !== 'tool_approval') {
		return null;
	}
	const requests = (event.payload.requests as Array<Record<string, unknown>>) ?? [];
	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold>Tool Approval Required</Text>
			{requests.map((item, index) => (
				<Text key={String(item.tool_call_id ?? index)}>
					{index + 1}. {String(item.tool_name ?? '-')} {String(item.summary ?? '')}
				</Text>
			))}
			<Text color="yellow">输入 -y 批准，-n 拒绝。</Text>
		</Box>
	);
}

