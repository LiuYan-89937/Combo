import React, {useEffect, useMemo, useReducer, useState} from 'react';
import {Box, Text, useApp} from 'ink';
import {PythonBridge} from './bridge/PythonBridge.js';
import {routeFactoryEvent} from './bridge/eventRouter.js';
import {commandSuggestions, factoryStages, factoryToolGroups} from './commands.js';
import {buildResumePayload} from './interrupts.js';
import {command, type FactoryCommand, type FactoryEvent, type FactoryMode} from './protocol.js';
import {initialFactoryUiState} from './state/factoryStore.js';
import {CommandInput} from './views/CommandInput.js';
import {CreateAgentView} from './views/CreateAgentView.js';
import {ErrorPanel} from './views/ErrorPanel.js';
import {HelpPanel} from './views/HelpPanel.js';
import {InterruptChoicePanel, isChoiceInterrupt} from './views/InterruptChoicePanel.js';
import {InterruptPrompt} from './views/InterruptPrompt.js';
import {LiveStreamPanel} from './views/LiveStreamPanel.js';
import {MessagesPanel} from './views/MessagesPanel.js';
import {SessionPanel} from './views/SessionPanel.js';
import {ShellLayout} from './views/ShellLayout.js';
import {ToolApprovalPrompt} from './views/ToolApprovalPrompt.js';
import {ToolEventsPanel} from './views/ToolEventsPanel.js';

export function App() {
	const {exit} = useApp();
	const [state, dispatch] = useReducer(routeFactoryEvent, initialFactoryUiState);
	const [sessionPickerOpen, setSessionPickerOpen] = useState(false);
	const bridge = useMemo(() => new PythonBridge(), []);
	const inputDisabled = state.runStatus === 'running' || sessionPickerOpen;
	const choiceInterrupt = isChoiceInterrupt(state.pendingInterrupt);

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

	function resumeInterrupt(payload: Record<string, unknown>): void {
		send(command('resume_interrupt', {payload}));
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
			setSessionPickerOpen(true);
			return;
		}
		if (value === '/new-session') {
			setSessionPickerOpen(false);
			send(command('new_session'));
			return;
		}
		if (value.startsWith('/resume ')) {
			setSessionPickerOpen(false);
			send(command('switch_session', {session_id: value.slice('/resume '.length).trim()}));
			return;
		}
		if (value.startsWith('/rerun ')) {
			send(command('rerun_from_stage', {payload: {stage_id: value.slice('/rerun '.length).trim()}}));
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
		if (value.startsWith('/tool-grep ')) {
			const query = value.slice('/tool-grep '.length).trim();
			dispatch({ui_type: 'set_tool_grep', query});
			return;
		}
		if (value === '/help') {
			dispatch({ui_type: 'show_help'});
			return;
		}
		if (value === '/session') {
			dispatch({ui_type: 'notice', message: `session ${state.sessionId ?? '-'}  mode ${state.mode ?? '-'}`});
			return;
		}
		if (value === '/tools') {
			dispatch({ui_type: 'notice', message: `tools ${factoryToolGroups.join(' | ')}`});
			return;
		}
		if (value === '/stages') {
			dispatch({ui_type: 'notice', message: `stages ${factoryStages.join(' -> ')}`});
			return;
		}
		send(command('send_message', {message: value}));
	}

	return (
		<ShellLayout state={state}>
			<ErrorPanel message={state.lastError} errors={state.errors} />
			<SessionPanel
				state={state}
				active={sessionPickerOpen}
				onClose={() => setSessionPickerOpen(false)}
				onSelect={sessionId => {
					setSessionPickerOpen(false);
					send(command('switch_session', {session_id: sessionId}));
				}}
			/>
			{state.helpVisible && <HelpPanel mode={state.mode} hasInterrupt={Boolean(state.pendingInterrupt)} />}
			{state.mode === 'create_agent' && <CreateAgentView state={state} />}
			<LiveStreamPanel state={state} />
			<ToolEventsPanel state={state} />
			<InterruptChoicePanel event={state.pendingInterrupt} onSubmit={resumeInterrupt} />
			{!choiceInterrupt && <ToolApprovalPrompt event={state.pendingInterrupt} />}
			{!choiceInterrupt && <InterruptPrompt event={state.pendingInterrupt} />}
			<MessagesPanel state={state} />
			<Box marginTop={1}>
				<Text color={state.ready ? 'green' : 'yellow'}>{state.ready ? 'ready' : 'starting bridge'}</Text>
			</Box>
			<CommandInput
				prompt={`factory${state.mode ? `:${modeLabel(state.mode)}` : ''}`}
				onSubmit={onSubmit}
				getSuggestions={value => commandSuggestions(value, state.mode, state.pendingInterrupt?.event_type === 'tool_approval_requested')}
				disabled={inputDisabled || choiceInterrupt}
				disabledText={sessionPickerOpen ? 'select a session above' : choiceInterrupt ? 'use the option panel above' : 'runtime running; waiting for event, tool approval, or interrupt'}
			/>
		</ShellLayout>
	);
}

function modeLabel(mode: FactoryMode): string {
	return mode === 'create_agent' ? 'create-agent' : mode;
}
