import {describe, expect, it} from 'vitest';
import {buildResumePayload} from './interrupts.js';
import {type FactoryEvent} from './protocol.js';

describe('interrupt resume payloads', () => {
	it('maps tool approval shortcuts to approve and deny', () => {
		const approval = toolApprovalEvent();
		expect(buildResumePayload(approval, '-y')).toEqual({action: 'approve', approved: true});
		expect(buildResumePayload(approval, '-n')).toEqual({action: 'deny', approved: false});
		expect(buildResumePayload(approval, '-t')).toEqual({action: 'trust_tool', approved: true, trust_scope: 'tool'});
	});

	it('maps freeform tool approval input to revision guidance', () => {
		expect(buildResumePayload(toolApprovalEvent(), 'cwd 参数不对，改到项目根目录')).toEqual({
			action: 'revise',
			approved: false,
			revision_guidance: 'cwd 参数不对，改到项目根目录'
		});
	});
});

function toolApprovalEvent(): FactoryEvent {
	return {
		event_id: 'tool-approval',
		event_type: 'tool_approval_requested',
		protocol_version: 'factory_frontend.v1',
		producer_type: 'test',
		request_id: null,
		run_id: 'run-1',
		session_id: 'session-1',
		thread_id: null,
		mode: 'chat',
		graph_id: 'test',
		node_id: null,
		node_label: null,
		node_kind: null,
		stage_id: null,
		span_id: null,
		parent_span_id: null,
		sequence: 1,
		timestamp: '2026-05-17T00:00:00Z',
		severity: null,
		message: null,
		payload: {type: 'tool_approval'}
	};
}
