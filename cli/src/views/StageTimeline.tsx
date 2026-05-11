import React from 'react';
import {Box, Text} from 'ink';
import {factoryStages} from '../commands.js';
import {type FactoryUiState} from '../state/factoryStore.js';
import {Section} from './ui.js';

export function StageTimeline({state}: {state: FactoryUiState}) {
	const stageEvents = state.events.filter(event => event.event_type === 'stage_started' || event.event_type === 'stage_completed');
	const latestStage = stageEvents.at(-1)?.stage_id ?? state.debugPatches.at(-1)?.stage_id;
	const completed = new Set(
		state.events
			.filter(event => event.event_type === 'stage_completed' && event.stage_id)
			.map(event => event.stage_id as string)
	);
	return (
		<Section title="Factory Stages" color="blue">
			<Box>
				{factoryStages.map((stage, index) => (
					<Box key={stage} marginRight={1}>
						<Text color={completed.has(stage) ? 'green' : stage === latestStage ? 'blue' : 'gray'} inverse={stage === latestStage}>
							{` ${index + 1} `}
						</Text>
					</Box>
				))}
			</Box>
			<Text color="gray">{latestStage ?? 'waiting for stage updates'}</Text>
		</Section>
	);
}
