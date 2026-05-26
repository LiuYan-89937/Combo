import React from 'react';
import {Box, Text} from 'ink';
import {describeInterrupt} from '../interrupts.js';
import {useStoreSelector} from '../state/useStoreSelector.js';

export function InterruptPrompt() {
	const event = useStoreSelector(state => state.pendingInterrupt);
	if (!event || event.event_type !== 'interrupt_requested') {
		return null;
	}
	const payload = event.payload ?? {};
	const descriptor = describeInterrupt(event);
	if (payload.type === 'tool_approval' || payload.type === 'resource_form') {
		return null;
	}
	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">{descriptor?.title ?? title(payload)}</Text>
			{payload.type === 'requirement_clarification' && <RequirementClarification payload={payload} />}
			{payload.type === 'plan_review' && <PlanReview payload={payload} />}
			{payload.type !== 'requirement_clarification' && payload.type !== 'plan_review' && (
				<Text>{JSON.stringify(payload, null, 2).slice(0, 1600)}</Text>
			)}
			<Text color="yellow">输入你的回复后回车继续。</Text>
		</Box>
	);
}

function RequirementClarification({payload}: {payload: Record<string, unknown>}) {
	const questions = (payload.questions as Array<Record<string, unknown>>) ?? [];
	return (
		<>
			{questions.map((question, index) => (
				<Box key={String(question.id ?? index)} flexDirection="column" marginTop={index ? 1 : 0}>
					<Text>{index + 1}. {String(question.question ?? question.id ?? '-')}</Text>
					{((question.options as Array<Record<string, unknown>>) ?? []).map(option => (
						<Text key={String(option.id ?? option.label)} color="gray">
							{'  - '}
							{String(option.label ?? option.id ?? '-')}
							{option.description ? `：${String(option.description)}` : ''}
						</Text>
					))}
				</Box>
			))}
		</>
	);
}

function PlanReview({payload}: {payload: Record<string, unknown>}) {
	return (
		<>
			<Text>{String(payload.plan_text ?? '').slice(0, 2200)}</Text>
			<Text color="gray">输入 continue/y/继续 继续；或直接输入修改意见。</Text>
		</>
	);
}

function title(payload: Record<string, unknown>): string {
	if (payload.type === 'requirement_clarification') {
		return 'Requirement Clarification';
	}
	if (payload.type === 'plan_review') {
		return 'Plan Review';
	}
	return `Interrupt: ${String(payload.type ?? 'unknown')}`;
}
