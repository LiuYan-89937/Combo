import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {z} from 'zod';
import {randomUUID} from 'node:crypto';

type ProtocolCatalog = {
	version: string;
	modes: string[];
	command_types: string[];
	event_types: string[];
};

const protocolCatalog = loadProtocolCatalog();
const factoryModeValues = nonEmptyStringTuple(protocolCatalog.modes, 'modes');
const commandTypeValues = nonEmptyStringTuple(protocolCatalog.command_types, 'command_types');
const eventTypeValues = nonEmptyStringTuple(protocolCatalog.event_types, 'event_types');

export const factoryProtocolVersion = protocolCatalog.version;
export const factoryModeSchema = z.enum(factoryModeValues);
export type FactoryMode = z.infer<typeof factoryModeSchema>;

export const commandSchema = z.object({
	type: z.enum(commandTypeValues),
	request_id: z.string().nullable().optional(),
	session_id: z.string().nullable().optional(),
	resume_latest: z.boolean().optional(),
	mode: factoryModeSchema.nullable().optional(),
	message: z.string().nullable().optional(),
	payload: z.record(z.unknown()).optional(),
	options: z.record(z.unknown()).optional()
}).strict();

export type FactoryCommand = z.infer<typeof commandSchema>;

export const eventSchema = z.object({
	event_id: z.string(),
	event_type: z.enum(eventTypeValues),
	protocol_version: z.literal(factoryProtocolVersion),
	producer_type: z.string(),
	request_id: z.string().nullable(),
	run_id: z.string().nullable(),
	session_id: z.string().nullable(),
	thread_id: z.string().nullable(),
	mode: factoryModeSchema.nullable(),
	graph_id: z.string().nullable(),
	node_id: z.string().nullable(),
	node_label: z.string().nullable(),
	node_kind: z.string().nullable(),
	stage_id: z.string().nullable(),
	span_id: z.string().nullable(),
	parent_span_id: z.string().nullable(),
	sequence: z.number(),
	timestamp: z.string(),
	severity: z.string().nullable(),
	message: z.string().nullable(),
	payload: z.record(z.unknown())
}).strict();

export type FactoryEvent = z.infer<typeof eventSchema>;

export function command(type: FactoryCommand['type'], patch: Partial<FactoryCommand> = {}): FactoryCommand {
	return {
		type,
		request_id: patch.request_id ?? randomUUID(),
		...patch
	};
}

function loadProtocolCatalog(): ProtocolCatalog {
	const catalogPath = resolve(
		dirname(fileURLToPath(import.meta.url)),
		'../../agent_factory/factory_graph/frontend_bridge/protocol_catalog.json'
	);
	const parsed = JSON.parse(readFileSync(catalogPath, 'utf8')) as Partial<ProtocolCatalog>;
	if (
		typeof parsed.version !== 'string'
		|| !Array.isArray(parsed.modes)
		|| !Array.isArray(parsed.command_types)
		|| !Array.isArray(parsed.event_types)
	) {
		throw new Error(`Invalid frontend protocol catalog: ${catalogPath}`);
	}
	return {
		version: parsed.version,
		modes: parsed.modes,
		command_types: parsed.command_types,
		event_types: parsed.event_types
	};
}

function nonEmptyStringTuple(values: string[], label: string): [string, ...string[]] {
	if (values.length === 0 || values.some(value => typeof value !== 'string' || !value.trim())) {
		throw new Error(`Invalid frontend protocol ${label}`);
	}
	return values as [string, ...string[]];
}
