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

	it('accepts runtime request cancel commands', () => {
		const parsed = commandSchema.parse({type: 'cancel_runtime_request', payload: {reason: 'user_cancelled'}});
		expect(parsed.type).toBe('cancel_runtime_request');
	});

	it('accepts context prepare and skipped compression events', () => {
		for (const event_type of ['context_prepare_started', 'context_prepare_completed', 'context_compression_skipped'] as const) {
			const parsed = eventSchema.parse({
				event_id: `${event_type}-event`,
				protocol_version: 'factory_frontend.v1',
				event_type,
				producer_type: 'factory_bridge',
				request_id: null,
				run_id: null,
				session_id: null,
				thread_id: null,
				mode: 'chat',
				graph_id: 'factory_bridge',
				node_id: 'answer',
				node_label: null,
				node_kind: null,
				stage_id: null,
				span_id: null,
				parent_span_id: null,
				sequence: 1,
				timestamp: '2026-05-11T00:00:00Z',
				severity: null,
				message: null,
				payload: {node_id: 'answer'}
			});
			expect(parsed.event_type).toBe(event_type);
		}
	});

	it('accepts knowledge lifecycle events', () => {
		const parsed = eventSchema.parse({
			event_id: 'knowledge-event',
			protocol_version: 'factory_frontend.v1',
			event_type: 'knowledge_source_preview_available',
			producer_type: 'factory_bridge',
			request_id: null,
			run_id: null,
			session_id: null,
			thread_id: null,
			mode: 'chat',
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
			payload: {source_id: 'docs', status: 'completed'}
		});
		expect(parsed.event_type).toBe('knowledge_source_preview_available');
	});
});
