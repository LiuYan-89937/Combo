import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Muted, Section} from './ui.js';

const PAGE_SIZE = 8;

export function SessionPanel({
	state,
	active = false,
	onSelect,
	onClose
}: {
	state: FactoryUiState;
	active?: boolean;
	onSelect?: (sessionId: string) => void;
	onClose?: () => void;
}) {
	const [selectedIndex, setSelectedIndex] = useState(0);
	const sessions = state.sessions;
	const pageStart = Math.floor(selectedIndex / PAGE_SIZE) * PAGE_SIZE;
	const visibleSessions = useMemo(() => sessions.slice(pageStart, pageStart + PAGE_SIZE), [sessions, pageStart]);
	const pageCount = Math.max(1, Math.ceil(sessions.length / PAGE_SIZE));
	const pageNumber = Math.floor(selectedIndex / PAGE_SIZE) + 1;

	useEffect(() => {
		setSelectedIndex(current => clamp(current, 0, Math.max(0, sessions.length - 1)));
	}, [sessions.length]);

	useInput((input, key) => {
		if (!active) {
			return;
		}
		if (key.escape || input === 'q') {
			onClose?.();
			return;
		}
		if (key.return) {
			const selected = sessions[selectedIndex];
			const sessionId = typeof selected?.session_id === 'string' ? selected.session_id : null;
			if (sessionId) {
				onSelect?.(sessionId);
			}
			return;
		}
		if (key.upArrow || input === 'k') {
			setSelectedIndex(current => clamp(current - 1, 0, Math.max(0, sessions.length - 1)));
			return;
		}
		if (key.downArrow || input === 'j') {
			setSelectedIndex(current => clamp(current + 1, 0, Math.max(0, sessions.length - 1)));
			return;
		}
		if ((key as {pageUp?: boolean}).pageUp || input === 'b') {
			setSelectedIndex(current => clamp(current - PAGE_SIZE, 0, Math.max(0, sessions.length - 1)));
			return;
		}
		if ((key as {pageDown?: boolean}).pageDown || input === 'f') {
			setSelectedIndex(current => clamp(current + PAGE_SIZE, 0, Math.max(0, sessions.length - 1)));
		}
	});

	if (!active) {
		return null;
	}

	return (
		<Section title={`Sessions (${sessions.length})`} color="magenta">
			{sessions.length === 0 ? (
				<Muted>No saved sessions found.</Muted>
			) : (
				<>
					<Muted>Enter 选择 / ↑↓ 或 j k 移动 / PageUp PageDown 或 b f 翻页 / Esc 或 q 关闭</Muted>
					<Box flexDirection="column" marginTop={1}>
						{visibleSessions.map((session, offset) => {
							const index = pageStart + offset;
							const selected = index === selectedIndex;
							const sessionId = String(session.session_id ?? '');
							const title = sessionTitle(session);
							const mode = String(session.current_mode ?? '-');
							const updatedAt = formatTime(String(session.updated_at ?? ''));
							return (
								<Box key={sessionId}>
									<Text color={selected ? 'magenta' : 'gray'}>{selected ? '› ' : '  '}</Text>
									<Text color={selected ? 'white' : 'cyan'} bold={selected}>{shortId(sessionId).padEnd(13)}</Text>
									<Text color="gray"> {mode.padEnd(12)} </Text>
									<Text color={selected ? 'white' : 'gray'}>{updatedAt.padEnd(19)} </Text>
									<Text color={selected ? 'white' : 'gray'}>{title}</Text>
								</Box>
							);
						})}
					</Box>
					<Muted>page {pageNumber}/{pageCount}</Muted>
				</>
			)}
		</Section>
	);
}

function shortId(value: string): string {
	return value.length > 12 ? `${value.slice(0, 10)}...` : value;
}

function sessionTitle(session: Record<string, unknown>): string {
	const displayTitle = stringValue(session.display_title);
	const firstUserInput = stringValue(session.first_user_input);
	if (displayTitle) {
		return displayTitle;
	}
	if (firstUserInput) {
		return firstUserInput;
	}
	const createCount = Number(session.create_agent_turn_count ?? 0);
	const chatCount = Number(session.chat_turn_count ?? 0);
	if (createCount || chatCount) {
		return `create=${createCount} chat=${chatCount}`;
	}
	return 'empty session';
}

function stringValue(value: unknown): string {
	return typeof value === 'string' ? value.trim() : '';
}

function formatTime(value: string): string {
	if (!value) {
		return '-';
	}
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return value.slice(0, 19);
	}
	return date.toLocaleString('zh-CN', {
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
}

function clamp(value: number, min: number, max: number): number {
	return Math.min(Math.max(value, min), max);
}
