import {type FactoryEvent} from './protocol.js';

export type InterruptDescriptor = {
	type: string;
	title: string;
	resumeKind: 'tool_approval' | 'plan_review' | 'requirement_clarification' | 'resource_form' | 'generic';
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
	if (type === 'resource_form') {
		return {type, title: String(payload.title ?? 'Resource Form'), resumeKind: 'resource_form'};
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
			case 'resource_form':
				return buildResourceFormPayload(parseKeyValueInput(value));
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

export function buildResourceFormPayload(values: Record<string, unknown>): Record<string, unknown> {
	return {type: 'resource_form_result', decision: 'submit', values};
}

export function buildResourceFormSkipPayload(note = '暂不提供'): Record<string, unknown> {
	return {type: 'resource_form_result', decision: 'skip', note};
}

function parseKeyValueInput(value: string): Record<string, unknown> {
	const result: Record<string, unknown> = {};
	for (const line of value.split(/\r?\n|;/)) {
		const trimmed = line.trim();
		if (!trimmed) {
			continue;
		}
		const separator = trimmed.includes('=') ? '=' : trimmed.includes(':') ? ':' : '';
		if (!separator) {
			continue;
		}
		const [rawKey, ...rest] = trimmed.split(separator);
		const key = rawKey.trim();
		const rawValue = rest.join(separator).trim();
		if (!key) {
			continue;
		}
		result[key] = parseScalarValue(rawValue);
	}
	return result;
}

function parseScalarValue(value: string): unknown {
	if (!value) {
		return '';
	}
	const normalized = value.toLowerCase();
	if (['true', 'yes', 'y', 'on', '允许', '是'].includes(normalized)) {
		return true;
	}
	if (['false', 'no', 'n', 'off', '不允许', '否'].includes(normalized)) {
		return false;
	}
	if ((value.startsWith('{') && value.endsWith('}')) || (value.startsWith('[') && value.endsWith(']'))) {
		try {
			return JSON.parse(value);
		} catch {
			return value;
		}
	}
	if (value.includes(',')) {
		return value.split(',').map(item => item.trim()).filter(Boolean);
	}
	return value;
}
