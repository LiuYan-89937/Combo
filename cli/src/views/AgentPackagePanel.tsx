import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Muted, Section} from './ui.js';

const PAGE_SIZE = 8;

export function AgentPackagePanel({
	onClose,
	onRefresh,
	onSelect,
	onDelete
}: {
	onClose?: () => void;
	onRefresh?: () => void;
	onSelect?: (packageId: string) => void;
	onDelete?: (packageId: string) => void;
}) {
	const active = useStoreSelector(state => state.agentPackagePickerOpen);
	const packages = useStoreSelector(state => state.agentPackages);
	const purpose = useStoreSelector(state => state.agentPackagePickerPurpose);
	const [selectedIndex, setSelectedIndex] = useState(0);
	const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
	const pageStart = Math.floor(selectedIndex / PAGE_SIZE) * PAGE_SIZE;
	const visiblePackages = useMemo(() => packages.slice(pageStart, pageStart + PAGE_SIZE), [packages, pageStart]);
	const pageCount = Math.max(1, Math.ceil(packages.length / PAGE_SIZE));
	const pageNumber = Math.floor(selectedIndex / PAGE_SIZE) + 1;

	useEffect(() => {
		setSelectedIndex(current => clamp(current, 0, Math.max(0, packages.length - 1)));
	}, [packages.length]);

	useInput((input, key) => {
		if (!active) {
			return;
		}
		if (key.escape || input === 'q') {
			if (deleteTarget) {
				setDeleteTarget(null);
			} else {
				onClose?.();
			}
			return;
		}
		const selectedPackageId = packageId(packages[selectedIndex]);
		if (purpose === 'run' && deleteTarget && (key.return || input === 'd')) {
			if (selectedPackageId && selectedPackageId === deleteTarget) {
				onDelete?.(selectedPackageId);
			}
			setDeleteTarget(null);
			return;
		}
		if (input === 'r') {
			onRefresh?.();
			return;
		}
		if (purpose === 'run' && input === 'd') {
			if (selectedPackageId) {
				setDeleteTarget(selectedPackageId);
			}
			return;
		}
		if (key.return) {
			if (selectedPackageId) {
				onSelect?.(selectedPackageId);
			}
			return;
		}
		if (key.upArrow || input === 'k') {
			setSelectedIndex(current => clamp(current - 1, 0, Math.max(0, packages.length - 1)));
			return;
		}
		if (key.downArrow || input === 'j') {
			setSelectedIndex(current => clamp(current + 1, 0, Math.max(0, packages.length - 1)));
			return;
		}
		if ((key as {pageUp?: boolean}).pageUp || input === 'b') {
			setSelectedIndex(current => clamp(current - PAGE_SIZE, 0, Math.max(0, packages.length - 1)));
			return;
		}
		if ((key as {pageDown?: boolean}).pageDown || input === 'f') {
			setSelectedIndex(current => clamp(current + PAGE_SIZE, 0, Math.max(0, packages.length - 1)));
		}
	});

	if (!active) {
		return null;
	}

	return (
		<Section title={`${purpose === 'evolution' ? 'Select Agent To Evolve' : 'Agent Packages'} (${packages.length})`} color="cyan">
			{packages.length === 0 ? (
				<Muted>没有发现 `.agentfactory/packages/*/agent_package.json`。</Muted>
			) : (
				<>
					<Muted>{purpose === 'evolution' ? 'Enter 选择 / ↑↓ 或 j k 移动 / r 刷新 / Esc 或 q 关闭' : 'Enter 进入 / ↑↓ 或 j k 移动 / d 删除 / r 刷新 / Esc 或 q 关闭'}</Muted>
					{deleteTarget && <Text color="red">再次按 Enter 或 d 删除 {deleteTarget}；Esc 取消。</Text>}
					<Box flexDirection="column" marginTop={1}>
						{visiblePackages.map((item, offset) => {
							const index = pageStart + offset;
							const selected = index === selectedIndex;
							const id = packageId(item);
							return (
								<Box key={id || index}>
									<Text color={selected ? 'cyan' : 'gray'}>{selected ? '› ' : '  '}</Text>
									<Text color={selected ? 'white' : 'cyan'} bold={selected}>{shortId(id).padEnd(15)}</Text>
									<Text color="gray"> {String(item.status ?? '-').padEnd(10)} </Text>
									<Text color="gray"> tools={String(item.tool_count ?? 0).padEnd(3)} </Text>
									<Text color="gray"> sessions={String(item.session_count ?? 0).padEnd(3)} </Text>
									<Text color="gray"> sandbox={sandboxStatus(item).padEnd(14)} </Text>
									<Text color={selected ? 'white' : 'gray'}>{agentTitle(item)}</Text>
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

export function AgentSessionPanel({
	onClose,
	onSelect
}: {
	onClose?: () => void;
	onSelect?: (sessionId: string | null) => void;
}) {
	const active = useStoreSelector(state => state.agentSessionPickerOpen);
	const sessions = useStoreSelector(state => state.agentPackageSessions);
	const activePackage = useStoreSelector(state => state.activeAgentPackage);
	const [selectedIndex, setSelectedIndex] = useState(0);
	const entries = useMemo(() => [{session_id: null, display_title: '创建新会话', turn_count: 0}, ...sessions], [sessions]);

	useEffect(() => {
		setSelectedIndex(current => clamp(current, 0, Math.max(0, entries.length - 1)));
	}, [entries.length]);

	useInput((input, key) => {
		if (!active) {
			return;
		}
		if (key.escape || input === 'q') {
			onClose?.();
			return;
		}
		if (key.return) {
			const value = entries[selectedIndex]?.session_id;
			onSelect?.(typeof value === 'string' ? value : null);
			return;
		}
		if (key.upArrow || input === 'k') {
			setSelectedIndex(current => clamp(current - 1, 0, Math.max(0, entries.length - 1)));
			return;
		}
		if (key.downArrow || input === 'j') {
			setSelectedIndex(current => clamp(current + 1, 0, Math.max(0, entries.length - 1)));
		}
	});

	if (!active) {
		return null;
	}

	return (
		<Section title={`Agent Sessions / ${String(activePackage?.agent_name ?? activePackage?.agent_id ?? '-')}`} color="magenta">
			<Muted>Enter 选择 / ↑↓ 或 j k 移动 / Esc 或 q 关闭</Muted>
			<Box flexDirection="column" marginTop={1}>
				{entries.map((item, index) => {
					const selected = index === selectedIndex;
					const id = typeof item.session_id === 'string' ? item.session_id : '';
					return (
						<Box key={id || 'new-session'}>
							<Text color={selected ? 'magenta' : 'gray'}>{selected ? '› ' : '  '}</Text>
							<Text color={selected ? 'white' : 'cyan'} bold={selected}>{id ? shortId(id).padEnd(15) : 'new'.padEnd(15)}</Text>
							<Text color="gray"> turns={String(item.turn_count ?? 0).padEnd(3)} </Text>
							<Text color={selected ? 'white' : 'gray'}>{sessionTitle(item)}</Text>
						</Box>
					);
				})}
			</Box>
		</Section>
	);
}

function packageId(item: Record<string, unknown> | undefined): string {
	return typeof item?.package_id === 'string' ? item.package_id : '';
}

function agentTitle(item: Record<string, unknown>): string {
	return stringValue(item.agent_name) || stringValue(item.agent_id) || stringValue(item.error) || 'unnamed agent package';
}

function sessionTitle(item: Record<string, unknown>): string {
	return stringValue(item.display_title) || stringValue(item.first_user_input) || 'empty session';
}

function sandboxStatus(item: Record<string, unknown>): string {
	const sandbox = item.sandbox;
	if (!sandbox || typeof sandbox !== 'object' || Array.isArray(sandbox)) {
		return '-';
	}
	return stringValue((sandbox as Record<string, unknown>).status) || '-';
}

function stringValue(value: unknown): string {
	return typeof value === 'string' ? value.trim() : '';
}

function shortId(value: string): string {
	return value.length > 14 ? `${value.slice(0, 12)}...` : value || '-';
}

function clamp(value: number, min: number, max: number): number {
	return Math.min(Math.max(value, min), max);
}
