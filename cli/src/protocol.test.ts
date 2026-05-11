import {describe, expect, it} from 'vitest';
import {commandSchema, eventSchema} from './protocol.js';

describe('frontend bridge protocol', () => {
	it('accepts runtime envelope events', () => {
		const parsed = eventSchema.parse({
			event_id: 'event-1',
			event_type: 'runtime_ready',
			sequence: 1,
			timestamp: '2026-05-11T00:00:00Z',
			payload: {}
		});
		expect(parsed.event_type).toBe('runtime_ready');
	});

	it('accepts send_message commands', () => {
		const parsed = commandSchema.parse({type: 'send_message', message: 'hello'});
		expect(parsed.message).toBe('hello');
	});
});
