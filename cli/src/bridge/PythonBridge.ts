import {createInterface} from 'node:readline';
import {randomUUID} from 'node:crypto';
import {existsSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execa, type ResultPromise} from 'execa';
import {type FactoryCommand, type FactoryEvent, eventSchema} from '../protocol.js';

type EventHandler = (event: FactoryEvent) => void;
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const maxDiagnosticLineLength = 2000;

export class PythonBridge {
	private process?: ResultPromise;
	private readonly handlers = new Set<EventHandler>();

	start(): void {
		if (this.process) {
			return;
		}
		const python = resolvePythonExecutable();
		this.process = execa(python, ['-m', 'agent_factory.factory_graph.frontend_bridge.stdio_server'], {
			cwd: projectRoot,
			stdin: 'pipe',
			stdout: 'pipe',
			stderr: 'pipe',
			reject: false
		});
		const stdout = this.process.stdout;
		if (!stdout) {
			throw new Error('Python bridge stdout is unavailable');
		}
		const lines = createInterface({input: stdout});
		lines.on('line', line => {
			const event = eventFromStdoutLine(line);
			if (!event) {
				return;
			}
			this.emit(event);
		});
		this.process.stderr?.on('data', chunk => {
			const message = String(chunk);
			this.emit(isPythonWarning(message) ? diagnosticEvent(message) : errorEvent(message));
		});
	}

	onEvent(handler: EventHandler): () => void {
		this.handlers.add(handler);
		return () => {
			this.handlers.delete(handler);
		};
	}

	send(command: FactoryCommand): void {
		if (!this.process?.stdin) {
			throw new Error('Python bridge is not running');
		}
		this.process.stdin.write(`${JSON.stringify(command)}\n`);
	}

	stop(): void {
		if (!this.process) {
			return;
		}
		this.send({type: 'shutdown'});
		this.process.stdin?.end();
		this.process = undefined;
	}

	private emit(event: FactoryEvent): void {
		for (const handler of this.handlers) {
			handler(event);
		}
	}
}

export function eventFromStdoutLine(line: string): FactoryEvent | null {
	if (!line.trim()) {
		return null;
	}
	const parsedJson = safeJsonParse(line);
	if (!parsedJson.ok) {
		return stdoutDiagnosticEvent(line);
	}
	const parsed = eventSchema.safeParse(parsedJson.value);
	if (parsed.success) {
		return parsed.data;
	}
	return errorEvent(parsed.error.message);
}

function resolvePythonExecutable(): string {
	if (process.env.AGENTFACTORY_PYTHON) {
		return process.env.AGENTFACTORY_PYTHON;
	}
	const projectVenvPython = resolve(projectRoot, '.venv/bin/python');
	if (existsSync(projectVenvPython)) {
		return projectVenvPython;
	}
	return 'python';
}

function errorEvent(message: string): FactoryEvent {
	return {
		event_id: randomUUID(),
		protocol_version: 'factory_frontend.v1',
		event_type: 'error',
		producer_type: 'typescript_cli',
		request_id: null,
		run_id: null,
		session_id: null,
		thread_id: null,
		mode: null,
		graph_id: 'typescript_cli',
		node_id: null,
		node_label: null,
		node_kind: null,
		stage_id: null,
		span_id: null,
		parent_span_id: null,
		sequence: 0,
		timestamp: new Date().toISOString(),
		severity: 'error',
		message,
		payload: {}
	};
}

function diagnosticEvent(message: string): FactoryEvent {
	return {
		event_id: randomUUID(),
		protocol_version: 'factory_frontend.v1',
		event_type: 'debug_patch',
		producer_type: 'typescript_cli',
		request_id: null,
		run_id: null,
		session_id: null,
		thread_id: null,
		mode: null,
		graph_id: 'typescript_cli',
		node_id: null,
		node_label: null,
		node_kind: null,
		stage_id: null,
		span_id: null,
		parent_span_id: null,
		sequence: 0,
		timestamp: new Date().toISOString(),
		severity: 'warning',
		message: 'Python diagnostic',
		payload: {stderr: message}
	};
}

function stdoutDiagnosticEvent(line: string): FactoryEvent {
	const truncated = truncateDiagnosticLine(line);
	return {
		event_id: randomUUID(),
		protocol_version: 'factory_frontend.v1',
		event_type: 'debug_patch',
		producer_type: 'typescript_cli',
		request_id: null,
		run_id: null,
		session_id: null,
		thread_id: null,
		mode: null,
		graph_id: 'typescript_cli',
		node_id: null,
		node_label: null,
		node_kind: null,
		stage_id: null,
		span_id: null,
		parent_span_id: null,
		sequence: 0,
		timestamp: new Date().toISOString(),
		severity: 'warning',
		message: 'Python stdout diagnostic',
		payload: {
			source: 'python_stdout_non_json',
			stdout: truncated,
			truncated: truncated.length !== line.length
		}
	};
}

function safeJsonParse(line: string): {ok: true; value: unknown} | {ok: false} {
	try {
		return {ok: true, value: JSON.parse(line) as unknown};
	} catch {
		return {ok: false};
	}
}

function truncateDiagnosticLine(line: string): string {
	if (line.length <= maxDiagnosticLineLength) {
		return line;
	}
	return line.slice(0, maxDiagnosticLineLength);
}

function isPythonWarning(message: string): boolean {
	return /\b[A-Za-z_][A-Za-z0-9_]*Warning:/.test(message);
}
