import {createInterface} from 'node:readline';
import {randomUUID} from 'node:crypto';
import {execa, type ResultPromise} from 'execa';
import {type FactoryCommand, type FactoryEvent, eventSchema} from '../protocol.js';

type EventHandler = (event: FactoryEvent) => void;

export class PythonBridge {
	private process?: ResultPromise;
	private readonly handlers = new Set<EventHandler>();

	start(): void {
		if (this.process) {
			return;
		}
		const python = process.env.AGENTFACTORY_PYTHON ?? 'python';
		this.process = execa(python, ['-m', 'agent_factory.factory_graph.frontend_bridge.stdio_server'], {
			cwd: process.cwd(),
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
			if (!line.trim()) {
				return;
			}
			const parsed = eventSchema.safeParse(JSON.parse(line));
			if (parsed.success) {
				this.emit(parsed.data);
			} else {
				this.emit(errorEvent(parsed.error.message));
			}
		});
		this.process.stderr?.on('data', chunk => {
			this.emit(errorEvent(String(chunk)));
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
