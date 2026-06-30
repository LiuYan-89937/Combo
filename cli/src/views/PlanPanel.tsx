import React from 'react';
import {Box, Text} from 'ink';
import {type RuntimePlanStepView} from '../state/runtimeStore.js';
import {useStoreSelector} from '../state/useStoreSelector.js';
import {Section} from './ui.js';

export function PlanPanel() {
	const plan = useStoreSelector(state => state.currentPlan);
	if (!plan || plan.steps.length === 0) {
		return null;
	}
	const currentStep = currentPlanStep(plan.steps, plan.currentStepId);
	const currentIndex = currentStep ? plan.steps.indexOf(currentStep) + 1 : null;
	return (
		<Section title={`Plan / ${plan.status}`} color={colorForPlanStatus(plan.status)}>
			{plan.goal ? <Text color="gray">{truncate(plan.goal, 180)}</Text> : null}
			<Text>{plan.steps.map((step, index) => planStepLabel(step, index)).join(' -> ')}</Text>
			{currentStep ? (
				<Box>
					<Text color="cyan">
						current Plan{currentIndex}: {truncate(currentStep.objective || currentStep.title, 180)}
					</Text>
				</Box>
			) : null}
		</Section>
	);
}

function currentPlanStep(steps: RuntimePlanStepView[], currentStepId: string | null): RuntimePlanStepView | null {
	if (currentStepId) {
		return steps.find(step => step.stepId === currentStepId) ?? null;
	}
	return steps.find(step => step.status === 'in_progress') ?? null;
}

function planStepLabel(step: RuntimePlanStepView, index: number): string {
	return `Plan${index + 1}[${statusLabel(step.status)}]: ${truncate(step.title, 52)}`;
}

function statusLabel(status: string): string {
	if (status === 'in_progress') {
		return 'run';
	}
	if (status === 'completed') {
		return 'done';
	}
	if (status === 'failed') {
		return 'fail';
	}
	if (status === 'skipped') {
		return 'skip';
	}
	return 'todo';
}

function colorForPlanStatus(status: string): string {
	if (status === 'completed') {
		return 'green';
	}
	if (status === 'failed' || status === 'cancelled') {
		return 'red';
	}
	return 'blue';
}

function truncate(value: string, limit: number): string {
	return value.length > limit ? `${value.slice(0, limit)}...` : value;
}
