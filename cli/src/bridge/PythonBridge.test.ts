import {describe, expect, it} from 'vitest';
import {eventFromStdoutLine} from './PythonBridge.js';

describe('PythonBridge stdout parser', () => {
	it('turns non-json stdout into a diagnostic event', () => {
		const event = eventFromStdoutLine('Tavily MCP server running on stdio');

		expect(event?.event_type).toBe('debug_patch');
		expect(event?.payload.source).toBe('python_stdout_non_json');
		expect(event?.payload.stdout).toBe('Tavily MCP server running on stdio');
	});

	it('turns schema-invalid protocol json into an error event', () => {
		const event = eventFromStdoutLine('{"event_type":"run_started"}');

		expect(event?.event_type).toBe('error');
		expect(event?.message).toContain('event_id');
	});
});
