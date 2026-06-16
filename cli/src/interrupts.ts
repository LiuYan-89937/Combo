import {type FactoryEvent} from './protocol.js';

export type InterruptDescriptor = {
	type: string;
	title: string;
	resumeKind:
		| 'tool_approval'
		| 'plan_review'
		| 'requirement_clarification'
		| 'publish_confirmation'
		| 'assistant_dialogue'
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
	if (type === 'create_agent_publish_confirmation') {
		return {type, title: String(payload.title ?? '发布前确认'), resumeKind: 'publish_confirmation'};
	}
	if (payload.presentation === 'assistant_dialogue') {
		return {type, title: String(payload.title ?? 'Assistant'), resumeKind: 'assistant_dialogue'};
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
		case 'publish_confirmation': {
			const normalized = value.trim().toLowerCase();
			if (['继续', '确认', '确认发布', '发布', 'approve', 'approved', 'yes', 'y', 'ok'].includes(normalized)) {
				return buildPublishConfirmationPayload('publish', value || '发布');
			}
			if (['保存草稿', '草稿', 'draft', 'save', 'save_draft'].includes(normalized)) {
				return buildPublishConfirmationPayload('save_draft', value || '保存草稿');
			}
			return buildPublishConfirmationPayload('message', value);
		}
		case 'assistant_dialogue': {
			return buildAssistantDialoguePayload(payload, value);
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

export function buildPublishConfirmationPayload(
	decision: 'publish' | 'save_draft' | 'message',
	inputText: string
): Record<string, unknown> {
	return {
		type: 'create_agent_publish_confirmation_result',
		decision,
		answer: inputText,
		input_text: inputText
	};
}

export function buildAssistantDialoguePayload(payload: Record<string, unknown>, value: string): Record<string, unknown> {
	const normalized = value.trim().toLowerCase();
	const resumeKind = String(payload.resume_kind ?? 'answer');
	if (resumeKind === 'confirmation') {
		if (['继续', '确认', '确认发布', '发布', 'approve', 'approved', 'yes', 'y', 'ok'].includes(normalized)) {
			return {decision: 'approve', answer: value, input_text: value};
		}
		if (['暂不提供', '跳过', 'skip', 'no', 'n'].includes(normalized)) {
			return {decision: 'pending', answer: value, input_text: value};
		}
		return {decision: 'pending', answer: value, input_text: value};
	}
	return {decision: 'revise', answer: value, input_text: value};
}
