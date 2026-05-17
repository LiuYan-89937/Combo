import React from 'react';
import {Box, Text} from 'ink';
import {factoryStages} from '../commands.js';
import {type RuntimeState} from '../state/runtimeStore.js';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Section} from './ui.js';

export function StageTimeline() {
	const stageStatuses = useStoreSelector(state => state.stageStatuses);
	const latestStage = useStoreSelector(state => state.currentStageId);
	const currentNodeId = useStoreSelector(state => state.currentNodeId);
	return (
		<Section title="Factory Stages" color="blue">
			<Box>
				{factoryStages.map((stage, index) => (
					<Box key={stage} marginRight={1}>
						<Text color={stageColor(stageStatuses[stage]?.status, stage === latestStage)} inverse={stage === latestStage}>
							{` ${index + 1} `}
						</Text>
					</Box>
				))}
			</Box>
			<Box marginTop={1} flexDirection="column">
				<Text color={latestStage ? 'cyan' : 'gray'}>
					{latestStage ? `active stage: ${latestStage}` : 'waiting for stage updates'}
				</Text>
				{latestStage && (
					<Text color="gray">
						{stageDetail(stageStatuses, currentNodeId, latestStage)}
					</Text>
				)}
			</Box>
		</Section>
	);
}

function stageColor(status: string | undefined, active: boolean): string {
	if (status === 'failed') {
		return 'red';
	}
	if (status === 'completed') {
		return 'green';
	}
	if (status === 'running' || active) {
		return 'blue';
	}
	return 'gray';
}

function stageDetail(stageStatuses: RuntimeState['stageStatuses'], currentNodeId: string | null, stageId: string): string {
	const status = stageStatuses[stageId];
	const node = currentNodeId ?? status?.nodeId;
	const message = status?.lastMessage;
	return [`status=${status?.status ?? 'running'}`, node ? `node=${node}` : null, message ? `note=${message}` : null]
		.filter(Boolean)
		.join('  ');
}
