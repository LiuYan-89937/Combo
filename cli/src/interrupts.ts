import {type FactoryEvent} from './protocol.js';

export type InterruptDescriptor = {
	type: string;
	title: string;
	resumeKind: 'tool_approval' | 'plan_review' | 'requirement_clarification' | 'generic';
};

export function describeInterrupt(event: FactoryEvent | null): InterruptDescriptor | null {
	if (!event) {
		return null;
	}
	const payload = event.payload ?? {};
	const type = String(payload.type ?? event.event_type);
	if (event.event_type === 'tool_approval_requested' || type === 'tool_approval') {
		return {type, title: 'Tool Approval Required', resumeKind: 'tool_approval'};
	}
	if (type === 'plan_review') {
		return {type, title: 'Plan Review', resumeKind: 'plan_review'};
	}
	if (type === 'requirement_clarification') {
		return {type, title: 'Requirement Clarification', resumeKind: 'requirement_clarification'};
	}
	return {type, title: `Interrupt: ${type}`, resumeKind: 'generic'};
}

export function buildResumePayload(event: FactoryEvent, value: string): Record<string, unknown> {
	const payload = event.payload ?? {};
	const descriptor = describeInterrupt(event);
	switch (descriptor?.resumeKind) {
		case 'tool_approval':
			return {approved: value.trim().toLowerCase() === '-y'};
		case 'plan_review':
			if (['继续', 'continue', 'c', 'yes', 'y'].includes(value.trim().toLowerCase())) {
				return {type: 'plan_review_result', decision: 'continue'};
			}
			return {type: 'plan_review_result', decision: 'revise', revision_instruction: value};
		case 'requirement_clarification': {
			const questions = (payload.questions as Array<Record<string, unknown>>) ?? [];
			const answers = questions.map((question, index) => ({
				question_id: String(question.id ?? `question_${index + 1}`),
				selected_option_id: 'custom',
				selected_label: '自定义输入',
				custom_text: value
			}));
			return {type: 'requirement_clarification_answer', answers};
		}
		default:
			return {input_text: value};
	}
}

export type RequirementClarificationAnswer = {
	question_id: string;
	selected_option_id: string;
	selected_label: string;
	custom_text?: string;
};

export function buildRequirementClarificationResumePayload(
	answers: RequirementClarificationAnswer[]
): Record<string, unknown> {
	return {type: 'requirement_clarification_answer', answers};
}

export function buildPlanReviewContinuePayload(): Record<string, unknown> {
	return {type: 'plan_review_result', decision: 'continue'};
}

export function buildPlanReviewRevisionPayload(revisionInstruction: string): Record<string, unknown> {
	return {type: 'plan_review_result', decision: 'revise', revision_instruction: revisionInstruction};
}

export function buildToolApprovalPayload(approved: boolean): Record<string, unknown> {
	return {action: approved ? 'approve' : 'deny', approved};
}

export function buildToolApprovalRevisionPayload(revisionGuidance: string): Record<string, unknown> {
	return {action: 'revise', approved: false, revision_guidance: revisionGuidance};
}
