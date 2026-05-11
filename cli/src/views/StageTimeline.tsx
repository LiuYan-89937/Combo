import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryUiState} from '../state/factoryStore.js';

const stages = [
	'requirement_capture',
	'runtime_pattern_selection',
	'graph_behavior_planning',
	'node_strategy_planning',
	'tool_capability_planning',
	'resource_and_condition_planning',
	'assembly_spec_generation',
	'package_generation',
	'harness_generation_and_test',
	'repair_or_finalize'
];

export function StageTimeline({state}: {state: FactoryUiState}) {
	const latestStage = state.stageDeltas.at(-1)?.stage_id;
	return (
		<Box borderStyle="single" borderColor="blue" paddingX={1} flexDirection="column">
			<Text bold>Factory Stages</Text>
			<Text>
				{stages.map(stage => (stage === latestStage ? `[${stage}]` : stage)).join(' -> ')}
			</Text>
		</Box>
	);
}

