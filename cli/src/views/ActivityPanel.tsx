import React from 'react';
import {Box, Text} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Section} from './ui.js';

export function ActivityPanel() {
	const activities = useStoreSelector(state => state.recentActivities).slice(-8);
	if (!activities.length) {
		return null;
	}
	return (
		<Section title="Live Activity" color="magenta">
			{activities.map(activity => (
				<Box key={activity.activityKey}>
					<Text color={activity.color}>{activity.label.padEnd(18)}</Text>
					<Text color="gray">{activity.stageId ?? '-'}</Text>
					<Text color="gray"> / </Text>
					<Text color="gray">{activity.nodeId ?? '-'}</Text>
					<Text>  {trim(activity.detail, 120)}</Text>
				</Box>
			))}
		</Section>
	);
}

function trim(value: string, limit: number): string {
	const normalized = value.replace(/\s+/g, ' ').trim();
	if (normalized.length <= limit) {
		return normalized;
	}
	return `${normalized.slice(0, limit)}...`;
}
