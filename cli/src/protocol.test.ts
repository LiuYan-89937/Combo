import {describe, expect, it} from 'vitest';
import {commandSchema, eventSchema} from './protocol.js';

describe('frontend bridge protocol', () => {
	it('accepts ready events', () => {
		expect(eventSchema.parse({type: 'ready', payload: {}}).type).toBe('ready');
	});

	it('accepts send_message commands', () => {
		const parsed = commandSchema.parse({type: 'send_message', message: 'hello'});
		expect(parsed.message).toBe('hello');
	});
});

