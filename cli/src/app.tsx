import React, {useEffect, useMemo, useReducer} from 'react';
import {Box, Text, useApp} from 'ink';
import {randomUUID} from 'node:crypto';
import {PythonBridge} from './bridge/PythonBridge.js';
import {routeFactoryEvent} from './bridge/eventRouter.js';
import {commandSuggestions, factoryStages, factoryToolGroups, shellCommands} from './commands.js';
import {buildResumePayload} from './interrupts.js';
import {command, type FactoryCommand, type FactoryEvent, type FactoryMode} from './protocol.js';
import {initialFactoryUiState} from './state/factoryStore.js';
import {CommandInput} from './views/CommandInput.js';
import {CreateAgentView} from './views/CreateAgentView.js';
import {ErrorPanel} from './views/ErrorPanel.js';
import {HelpPanel} from './views/HelpPanel.js';
import {InterruptPrompt} from './views/InterruptPrompt.js';
import {LiveStreamPanel} from './views/LiveStreamPanel.js';
import {MessagesPanel} from './views/MessagesPanel.js';
import {ResourceInputPrompt} from './views/ResourceInputPrompt.js';
import {SessionPanel} from './views/SessionPanel.js';
import {ShellLayout} from './views/ShellLayout.js';
import {ToolApprovalPrompt} from './views/ToolApprovalPrompt.js';
import {ToolEventsPanel} from './views/ToolEventsPanel.js';

export function App() {
	const {exit} = useApp();
	const [state, dispatch] = useReducer(routeFactoryEvent, initialFactoryUiState);
	const bridge = useMemo(() => new PythonBridge(), []);
	const inputDisabled = state.runStatus === 'running';

	useEffect(() => {
		const off = bridge.onEvent((event: FactoryEvent) => dispatch(event));
		bridge.start();
		bridge.send(command('start_session'));
		return () => {
			off();
			bridge.stop();
		};
	}, [bridge]);

	function send(payload: FactoryCommand): void {
		bridge.send(payload);
	}

	function onSubmit(value: string): void {
		if (!value) {
			return;
		}
		if (state.pendingInterrupt) {
			send(command('resume_interrupt', {payload: buildResumePayload(state.pendingInterrupt, value)}));
			return;
		}
		if (value === '/quit') {
			send(command('shutdown'));
			exit();
			return;
		}
		if (value === '/chat') {
			send(command('set_mode', {mode: 'chat'}));
			return;
		}
		if (value === '/create-agent' || value === '/create—agent') {
			send(command('set_mode', {mode: 'create_agent'}));
			return;
		}
		if (value === '/exit') {
			send(command('set_mode', {mode: null}));
			return;
		}
		if (value === '/sessions') {
			send(command('list_sessions'));
			return;
		}
		if (value === '/new-session') {
			send(command('new_session'));
			return;
		}
		if (value.startsWith('/resume ')) {
			send(command('switch_session', {session_id: value.slice('/resume '.length).trim()}));
			return;
		}
		if (value.startsWith('/stop ')) {
			const stop_after_stage = value.slice('/stop '.length).trim();
			send(command('set_options', {options: {stop_after_stage}}));
			return;
		}
		if (value.startsWith('/state ')) {
			send(command('set_options', {options: {show_state: value.endsWith('on')}}));
			return;
		}
		if (value.startsWith('/messages ')) {
			send(command('set_options', {options: {show_messages: value.endsWith('on')}}));
			return;
		}
		if (value === '/help') {
			dispatch(localEvent({
				event_type: 'debug_patch',
				node_id: 'help',
				payload: {
					patch: {
						commands: shellCommands.map(item => `${item.usage} - ${item.description}`)
					}
				}
			}));
			return;
		}
		if (value === '/session') {
			dispatch(localEvent({event_type: 'debug_patch', node_id: 'session', payload: {patch: {session_id: state.sessionId, mode: state.mode}}}));
			return;
		}
		if (value === '/tools') {
			dispatch(localEvent({event_type: 'debug_patch', node_id: 'tools', payload: {patch: {tools: factoryToolGroups}}}));
			return;
		}
		if (value === '/stages') {
			dispatch(localEvent({event_type: 'debug_patch', node_id: 'stages', payload: {patch: {stages: factoryStages}}}));
			return;
		}
		send(command('send_message', {message: value}));
	}

	return (
		<ShellLayout state={state}>
			<ErrorPanel message={state.lastError} />
			<SessionPanel state={state} />
			{state.helpVisible && <HelpPanel mode={state.mode} hasInterrupt={Boolean(state.pendingInterrupt)} />}
			{state.mode === 'create_agent' && <CreateAgentView state={state} />}
			<LiveStreamPanel state={state} />
			<ToolEventsPanel state={state} />
			<ToolApprovalPrompt event={state.pendingInterrupt} />
			<ResourceInputPrompt event={state.pendingInterrupt} />
			<InterruptPrompt event={state.pendingInterrupt} />
			<MessagesPanel state={state} />
			<Box marginTop={1}>
				<Text color={state.ready ? 'green' : 'yellow'}>{state.ready ? 'ready' : 'starting bridge'}</Text>
			</Box>
			<CommandInput
				prompt={`factory${state.mode ? `:${modeLabel(state.mode)}` : ''}`}
				onSubmit={onSubmit}
				getSuggestions={value => commandSuggestions(value, state.mode, state.pendingInterrupt?.event_type === 'tool_approval_requested')}
				disabled={inputDisabled}
				disabledText="runtime running; waiting for event, tool approval, or interrupt"
			/>
		</ShellLayout>
	);
}

function modeLabel(mode: FactoryMode): string {
	return mode === 'create_agent' ? 'create-agent' : mode;
}

function localEvent(patch: Partial<FactoryEvent> & Pick<FactoryEvent, 'event_type'>): FactoryEvent {
	return {
		event_id: randomUUID(),
		event_type: patch.event_type,
		request_id: null,
		run_id: patch.run_id ?? null,
		session_id: patch.session_id ?? null,
		mode: patch.mode ?? null,
		graph_id: patch.graph_id ?? 'typescript_cli',
		node_id: patch.node_id ?? null,
		stage_id: patch.stage_id ?? null,
		span_id: patch.span_id ?? randomUUID(),
		parent_span_id: patch.parent_span_id ?? null,
		sequence: patch.sequence ?? 0,
		timestamp: patch.timestamp ?? new Date().toISOString(),
		message: patch.message ?? null,
		payload: patch.payload ?? {}
	};
}
