import {type FactoryEvent} from './protocol.js';

export type InterruptDescriptor = {
	type: string;
	title: string;
	resumeKind:
		| 'tool_approval'
		| 'plan_review'
		| 'requirement_clarification'
		| 'resource_collection'
		| 'resource_confirmation'
		| 'scheduler_seed_review'
		| 'generic';
};

export function describeInterrupt(event: FactoryEvent | null): InterruptDescriptor | null {
	if (!event) {
		return null;
	}
	const payload = event.payload ?? {};
	const type = String(payload.type ?? event.event_type);
	if (event.event_type === 'tool_approval_requested' || type === 'tool_approval') {
		return {type, title: 'Tool Approval Dock', resumeKind: 'tool_approval'};
	}
	if (type === 'plan_review') {
		return {type, title: 'Plan Review', resumeKind: 'plan_review'};
	}
	if (type === 'requirement_clarification') {
		return {type, title: 'Requirement Clarification', resumeKind: 'requirement_clarification'};
	}
	if (type === 'resource_collection') {
		return {type, title: String(payload.title ?? 'Resource Collection'), resumeKind: 'resource_collection'};
	}
	if (type === 'resource_confirmation') {
		return {type, title: String(payload.title ?? 'Resource Confirmation'), resumeKind: 'resource_confirmation'};
	}
	if (type === 'scheduler_seed_review') {
		return {type, title: String(payload.title ?? 'Scheduler Seed Review'), resumeKind: 'scheduler_seed_review'};
	}
	return {type, title: `Interrupt: ${type}`, resumeKind: 'generic'};
}

export function buildResumePayload(event: FactoryEvent, value: string): Record<string, unknown> {
	const payload = event.payload ?? {};
	const descriptor = describeInterrupt(event);
	switch (descriptor?.resumeKind) {
		case 'tool_approval': {
			const normalized = value.trim().toLowerCase();
			if (['-y', 'y', 'yes', 'approve', 'approved'].includes(normalized)) {
				return {action: 'approve', approved: true};
			}
			if (['-n', 'n', 'no', 'deny', 'denied', 'reject', 'rejected'].includes(normalized)) {
				return {action: 'deny', approved: false};
			}
			if (['-t', 't', 'trust', 'trust_tool', 'always_allow', 'no_approval', '无需审批'].includes(normalized)) {
				return buildToolTrustPayload();
			}
			return buildToolApprovalRevisionPayload(value);
		}
		case 'plan_review': {
			if (['继续', 'continue', 'c', 'yes', 'y'].includes(value.trim().toLowerCase())) {
				return {type: 'plan_review_result', decision: 'continue'};
			}
			return {type: 'plan_review_result', decision: 'revise', revision_instruction: value};
		}
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
		case 'resource_collection':
			return buildResourceCollectionPayload(value);
		case 'resource_confirmation': {
			const normalized = value.trim().toLowerCase();
			if (['继续', '确认', 'approve', 'approved', 'yes', 'y'].includes(normalized)) {
				return buildResourceConfirmationApprovePayload();
			}
			if (['暂不提供', 'skip', 'no', 'n'].includes(normalized)) {
				return buildResourceConfirmationSkipPayload(value);
			}
			return buildResourceConfirmationRevisePayload(value);
		}
		case 'scheduler_seed_review': {
			const normalized = value.trim().toLowerCase();
			if (['继续', '确认', 'approve', 'approved', 'yes', 'y'].includes(normalized)) {
				return buildSchedulerSeedReviewApprovePayload();
			}
			if (['暂不定时', '不启用', 'skip', 'no', 'n'].includes(normalized)) {
				return buildSchedulerSeedReviewSkipPayload(value);
			}
			return buildSchedulerSeedReviewRevisePayload(value);
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

export function buildToolTrustPayload(): Record<string, unknown> {
	return {action: 'trust_tool', approved: true, trust_scope: 'tool'};
}

export function buildToolApprovalRevisionPayload(revisionGuidance: string): Record<string, unknown> {
	return {action: 'revise', approved: false, revision_guidance: revisionGuidance};
}

export function buildResourceCollectionPayload(answer: string): Record<string, unknown> {
	return {type: 'resource_collection_answer', decision: 'submit', answer};
}

export function buildResourceCollectionSkipPayload(note = '暂不提供'): Record<string, unknown> {
	return {type: 'resource_collection_answer', decision: 'skip', note};
}

export function buildResourceConfirmationApprovePayload(): Record<string, unknown> {
	return {type: 'resource_confirmation_result', decision: 'approve'};
}

export function buildResourceConfirmationRevisePayload(revisionText: string): Record<string, unknown> {
	return {type: 'resource_confirmation_result', decision: 'revise', revision_text: revisionText};
}

export function buildResourceConfirmationSkipPayload(note = '暂不提供'): Record<string, unknown> {
	return {type: 'resource_confirmation_result', decision: 'skip', note};
}

export function buildSchedulerSeedReviewApprovePayload(): Record<string, unknown> {
	return {type: 'scheduler_seed_review_result', decision: 'approve'};
}

export function buildSchedulerSeedReviewRevisePayload(revisionText: string): Record<string, unknown> {
	return {type: 'scheduler_seed_review_result', decision: 'revise', revision_text: revisionText};
}

export function buildSchedulerSeedReviewSkipPayload(note = '暂不定时'): Record<string, unknown> {
	return {type: 'scheduler_seed_review_result', decision: 'skip', note};
}
