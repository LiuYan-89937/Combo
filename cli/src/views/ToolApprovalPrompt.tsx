import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryEvent} from '../protocol.js';

export function ToolApprovalPrompt({event}: {event: FactoryEvent | null}) {
	if (!event || event.event_type !== 'tool_approval_requested') {
		return null;
	}
	const payload = event.payload ?? {};
	const requests = (payload.requests as Array<Record<string, unknown>>) ?? [];
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
