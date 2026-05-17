import React from 'react';
import {Box} from 'ink';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {StageTimeline} from './StageTimeline.js';
import {StagePanel} from './StagePanel.js';
import {ActivityPanel} from './ActivityPanel.js';

export function CreateAgentView() {
	const mode = useStoreSelector(state => state.mode);
	if (mode !== 'create_agent') {
		return null;
	}
	return (
		<Box flexDirection="column">
			<StageTimeline />
			<ActivityPanel />
			<StagePanel />
		</Box>
	);
}
