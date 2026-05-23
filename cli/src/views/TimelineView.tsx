import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {type TimelineItem} from '../state/runtimeStore.js';
import {useStoreSelector} from '../state/useStoreSelector.js';

export function TimelineView() {
	const items = useStoreSelector(state => state.timelineItems);
	const [roundOffsetFromLatest, setRoundOffsetFromLatest] = useState(0);
	const windowModel = useMemo(() => conversationWindowModel(items), [items]);
	const maxOffset = Math.max(0, windowModel.windowCount - 1);

	useEffect(() => {
		setRoundOffsetFromLatest(current => Math.min(current, maxOffset));
	}, [maxOffset]);

	useInput((input, key) => {
		if (!items.length || maxOffset === 0) {
			return;
		}
		if ((key as {pageUp?: boolean}).pageUp || (key.ctrl && input === 'u')) {
			setRoundOffsetFromLatest(current => Math.min(maxOffset, current + 1));
			return;
		}
		if ((key as {pageDown?: boolean}).pageDown || (key.ctrl && input === 'd')) {
			setRoundOffsetFromLatest(current => Math.max(0, current - 1));
			return;
		}
		if ((key as {home?: boolean}).home) {
			setRoundOffsetFromLatest(maxOffset);
			return;
		}
		if ((key as {end?: boolean}).end) {
			setRoundOffsetFromLatest(0);
		}
	});

	if (!items.length) {
		return (
			<Box marginBottom={1}>
				<Text color="gray">Type /chat, /create-agent, or /run-agent-package to begin.</Text>
			</Box>
		);
	}
	const visible = visibleConversationItems(windowModel, roundOffsetFromLatest);
	const hiddenBefore = windowModel.items.indexOf(visible[0] ?? windowModel.items[0] ?? items[0]);
	const hiddenAfter = Math.max(0, windowModel.items.length - hiddenBefore - visible.length);
	return (
		<Box flexDirection="column">
			<TimelineScrollHint
				hiddenBefore={hiddenBefore}
				hiddenAfter={hiddenAfter}
				roundOffsetFromLatest={roundOffsetFromLatest}
				maxOffset={maxOffset}
			/>
			{visible.map(item => (
				<TimelineBlock key={item.id} item={item} />
			))}
		</Box>
	);
}

type ConversationWindowModel = {
	items: TimelineItem[];
	userIndexes: number[];
	windowCount: number;
};

function conversationWindowModel(items: TimelineItem[]): ConversationWindowModel {
	const userIndexes = items
		.map((item, index) => item.title === 'You' ? index : -1)
		.filter(index => index >= 0);
	if (userIndexes.length <= 2) {
		return {items, userIndexes, windowCount: 1};
	}
	return {
		items,
		userIndexes,
		windowCount: userIndexes.length - 1
	};
}

function visibleConversationItems(model: ConversationWindowModel, roundOffsetFromLatest: number): TimelineItem[] {
	if (model.userIndexes.length <= 2) {
		return model.items;
	}
	const latestStartWindow = model.userIndexes.length - 2;
	const startWindow = clamp(latestStartWindow - roundOffsetFromLatest, 0, latestStartWindow);
	const startIndex = model.userIndexes[startWindow] ?? 0;
	const endIndex = model.userIndexes[startWindow + 2] ?? model.items.length;
	return model.items.slice(startIndex, endIndex);
}

function TimelineScrollHint({
	hiddenBefore,
	hiddenAfter,
	roundOffsetFromLatest,
	maxOffset
}: {
	hiddenBefore: number;
	hiddenAfter: number;
	roundOffsetFromLatest: number;
	maxOffset: number;
}) {
	if (maxOffset === 0) {
		return null;
	}
	const position = roundOffsetFromLatest === 0
		? 'latest'
		: roundOffsetFromLatest === maxOffset
			? 'oldest'
			: `${maxOffset - roundOffsetFromLatest + 1}/${maxOffset + 1}`;
	return (
		<Box marginBottom={1}>
			<Text color="gray">
				history {position}  PageUp/PageDown or Ctrl+U/Ctrl+D scroll
				{hiddenBefore > 0 ? `  ${hiddenBefore} before` : ''}
				{hiddenAfter > 0 ? `  ${hiddenAfter} after` : ''}
			</Text>
		</Box>
	);
}

function TimelineBlock({item}: {item: TimelineItem}) {
	const body = trimContent(item.body);
	if (item.title === 'You') {
		return (
			<Box marginBottom={1}>
				<Text color="cyan" bold>{'> '}</Text>
				<Text>{body}</Text>
			</Box>
		);
	}
	return (
		<Box flexDirection="column" marginBottom={1}>
			<Text color={item.color} bold>
				{item.title}
				{item.active ? ' streaming' : ''}
			</Text>
			{body ? <Text>{indent(body)}</Text> : null}
		</Box>
	);
}

function trimContent(value: string): string {
	const limit = 3600;
	return value.length > limit ? `...${value.slice(value.length - limit)}` : value;
}

function indent(value: string): string {
	return value.split('\n').map(line => line ? `  ${line}` : '').join('\n');
}

function clamp(value: number, min: number, max: number): number {
	return Math.min(Math.max(value, min), max);
}
