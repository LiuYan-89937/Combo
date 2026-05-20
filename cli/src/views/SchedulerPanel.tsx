import React from 'react';
import {Box, Text} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Section} from './ui.js';

export function SchedulerPanel() {
	const activities = useStoreSelector(state => state.schedulerActivities).slice(-5);
	if (!activities.length) {
		return null;
	}
	return (
		<Section title="Scheduler" color="magenta">
			{activities.map((item, index) => (
				<Box key={`${item.timestamp}:${item.jobId ?? index}`} flexDirection="column">
					<Box>
						<Text color={colorForStatus(item.status)}>{label(item.eventType).padEnd(24)}</Text>
						<Text color="gray">{short(item.jobId)}</Text>
						<Text color="gray"> / </Text>
						<Text color="gray">{short(item.runId)}</Text>
						<Text>  {trim(item.detail, 100)}</Text>
					</Box>
					{item.reportPath && (
						<Text color="gray">  report: {trim(item.reportPath, 120)}</Text>
					)}
				</Box>
			))}
		</Section>
	);
}

function label(value: string): string {
	return value.replaceAll('_', ' ');
}

function short(value: string | null): string {
	if (!value) {
		return '-';
	}
	return value.length > 10 ? `${value.slice(0, 8)}...` : value;
}

function trim(value: string, limit: number): string {
	const normalized = value.replace(/\s+/g, ' ').trim();
	if (normalized.length <= limit) {
		return normalized;
	}
	return `${normalized.slice(0, limit)}...`;
}

function colorForStatus(value: string | null): string {
	if (value === 'failed' || value === 'cancelled') {
		return 'red';
	}
	if (value === 'completed') {
		return 'green';
	}
	if (value === 'running') {
		return 'cyan';
	}
	if (value === 'skipped') {
		return 'yellow';
	}
	return 'magenta';
}
