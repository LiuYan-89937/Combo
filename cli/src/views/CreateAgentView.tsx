import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';
import {StageTimeline} from './StageTimeline.js';
import {StagePanel} from './StagePanel.js';
import {ActivityPanel} from './ActivityPanel.js';

export function CreateAgentView({state}: {state: FactoryUiState}) {
	return (
		<Box flexDirection="column">
			<StageTimeline state={state} />
			<ActivityPanel state={state} />
			<StagePanel state={state} />
		</Box>
	);
}
