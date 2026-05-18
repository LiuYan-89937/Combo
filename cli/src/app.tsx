import React, {useEffect, useMemo} from 'react';
import {useApp} from 'ink';
import {PythonBridge} from './bridge/PythonBridge.js';
import {commandSuggestions, factoryStages, factoryToolGroups} from './commands.js';
import {buildResumePayload} from './interrupts.js';
import {command, type FactoryCommand, type FactoryEvent, type FactoryMode} from './protocol.js';
import {createRuntimeStore} from './state/runtimeStore.js';
import {RuntimeStoreProvider, useStoreSelector} from './state/useStoreSelector.js';
import {CommandInput} from './views/CommandInput.js';
import {CreateAgentView} from './views/CreateAgentView.js';
import {ErrorPanel} from './views/ErrorPanel.js';
import {HelpPanel} from './views/HelpPanel.js';
import {InterruptChoicePanel, isChoiceInterrupt} from './views/InterruptChoicePanel.js';
import {InterruptPrompt} from './views/InterruptPrompt.js';
import {MessagesPanel} from './views/MessagesPanel.js';
import {SessionPanel} from './views/SessionPanel.js';
import {ShellLayout} from './views/ShellLayout.js';
import {ToolEventsPanel} from './views/ToolEventsPanel.js';

export function App() {
	const {exit} = useApp();
	const store = useMemo(() => createRuntimeStore(), []);
	const bridge = useMemo(() => new PythonBridge(), []);

	useEffect(() => {
		const off = bridge.onEvent((event: FactoryEvent) => store.dispatch(event));
		bridge.start();
		bridge.send(command('start_session'));
		return () => {
			off();
			bridge.stop();
			store.destroy();
		};
	}, [bridge, store]);

	function send(payload: FactoryCommand): void {
		bridge.send(payload);
	}

	function resumeInterrupt(payload: Record<string, unknown>): void {
		send(command('resume_interrupt', {payload}));
	}

	function onSubmit(value: string): void {
		const state = store.getSnapshot();
		if (!value) {
			return;
		}
		if (state.pendingInterrupt) {
			store.dispatch({ui_type: 'interrupt_response_submitted', message: value});
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
			store.dispatch({ui_type: 'set_session_picker_open', open: true});
			return;
		}
		if (value === '/new-session') {
			store.dispatch({ui_type: 'set_session_picker_open', open: false});
			send(command('new_session'));
			return;
		}
		if (value.startsWith('/resume ')) {
			store.dispatch({ui_type: 'set_session_picker_open', open: false});
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
			store.dispatch({ui_type: 'set_tool_grep', query});
			return;
		}
		if (value === '/help') {
			store.dispatch({ui_type: 'show_help'});
			return;
		}
		if (value === '/session') {
			store.dispatch({ui_type: 'notice', message: `session ${state.sessionId ?? '-'}  mode ${state.mode ?? '-'}`});
			return;
		}
		if (value === '/tools') {
			store.dispatch({ui_type: 'notice', message: `tools ${factoryToolGroups.join(' | ')}`});
			return;
		}
		if (value === '/stages') {
			store.dispatch({ui_type: 'notice', message: `stages ${factoryStages.join(' -> ')}`});
			return;
		}
		store.dispatch({ui_type: 'local_user_message', message: value});
		send(command('send_message', {message: value}));
	}

	return (
		<RuntimeStoreProvider store={store}>
			<ShellLayout>
				<ErrorPanel />
				<SessionPanel
					onClose={() => store.dispatch({ui_type: 'set_session_picker_open', open: false})}
					onSelect={sessionId => {
						store.dispatch({ui_type: 'set_session_picker_open', open: false});
						send(command('switch_session', {session_id: sessionId}));
					}}
				/>
				<ConnectedHelpPanel />
				<CreateAgentView />
				<ToolEventsPanel />
				<MessagesPanel />
				<InterruptChoicePanel onSubmit={resumeInterrupt} />
				<InterruptPrompt />
				<ConnectedCommandInput onSubmit={onSubmit} />
			</ShellLayout>
		</RuntimeStoreProvider>
	);
}

function ConnectedHelpPanel() {
	const helpVisible = useStoreSelector(state => state.helpVisible);
	const mode = useStoreSelector(state => state.mode);
	const hasInterrupt = useStoreSelector(state => Boolean(state.pendingInterrupt));
	return helpVisible ? <HelpPanel mode={mode} hasInterrupt={hasInterrupt} /> : null;
}

function ConnectedCommandInput({onSubmit}: {onSubmit: (value: string) => void}) {
	const mode = useStoreSelector(state => state.mode);
	const pendingInterrupt = useStoreSelector(state => state.pendingInterrupt);
	const runStatus = useStoreSelector(state => state.runStatus);
	const sessionPickerOpen = useStoreSelector(state => state.sessionPickerOpen);
	const choiceInterrupt = isChoiceInterrupt(pendingInterrupt);
	const inputDisabled = runStatus === 'running' || sessionPickerOpen;
	return (
		<CommandInput
			prompt={`factory${mode ? `:${modeLabel(mode)}` : ''}`}
			onSubmit={onSubmit}
			getSuggestions={value => commandSuggestions(value, mode, pendingInterrupt?.event_type === 'tool_approval_requested')}
			disabled={inputDisabled || choiceInterrupt}
			disabledText={sessionPickerOpen ? 'select a session above' : choiceInterrupt ? 'use the option panel above' : 'runtime running; waiting for event, tool approval, or interrupt'}
		/>
	);
}

function modeLabel(mode: FactoryMode): string {
	return mode === 'create_agent' ? 'create-agent' : mode;
}
