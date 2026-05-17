import {describe, expect, it} from 'vitest';
import {commandSchema, eventSchema} from './protocol.js';

describe('frontend bridge protocol', () => {
	it('accepts runtime envelope events', () => {
		const parsed = eventSchema.parse({
			event_id: 'event-1',
			protocol_version: 'factory_frontend.v1',
			event_type: 'runtime_ready',
			producer_type: 'factory_bridge',
			request_id: null,
			run_id: null,
			session_id: null,
			thread_id: null,
			mode: null,
			graph_id: 'factory_bridge',
			node_id: null,
			node_label: null,
			node_kind: null,
			stage_id: null,
			span_id: null,
			parent_span_id: null,
			sequence: 1,
			timestamp: '2026-05-11T00:00:00Z',
			severity: null,
			message: null,
			payload: {}
		});
		expect(parsed.event_type).toBe('runtime_ready');
	});

	it('accepts send_message commands', () => {
		const parsed = commandSchema.parse({type: 'send_message', message: 'hello'});
		expect(parsed.message).toBe('hello');
	});
});
