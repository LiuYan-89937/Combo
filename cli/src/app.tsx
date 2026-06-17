import React, {useEffect, useMemo} from 'react';
import {useApp} from 'ink';
import {PythonBridge} from './bridge/PythonBridge.js';
import {commandSuggestions, factoryToolGroups} from './commands.js';
import {buildResumePayload} from './interrupts.js';
import {command, type FactoryCommand, type FactoryEvent, type FactoryMode} from './protocol.js';
import {contextActivityStatusLabel} from './state/renderProjection.js';
import {createRuntimeStore} from './state/runtimeStore.js';
import {RuntimeStoreProvider, useStoreSelector} from './state/useStoreSelector.js';
import {Composer} from './views/Composer.js';
import {HelpPanel} from './views/HelpPanel.js';
import {InterruptChoicePanel, isChoiceInterrupt} from './views/InterruptChoicePanel.js';
import {InterruptPrompt} from './views/InterruptPrompt.js';
import {AgentPackagePanel, AgentSessionPanel} from './views/AgentPackagePanel.js';
import {LiveStatusLine} from './views/LiveStatusLine.js';
import {SessionPanel} from './views/SessionPanel.js';
import {ShellLayout} from './views/ShellLayout.js';
import {TimelineView} from './views/TimelineView.js';

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
		if (value === '/cancel') {
			store.dispatch({ui_type: 'notice', message: 'cancel requested'});
			send(command('cancel_runtime_request', {payload: {reason: 'user_cancelled'}}));
			return;
		}
		if (value === '/chat') {
			send(command('set_mode', {mode: 'chat', payload: {package_id: 'factory_chat'}}));
			return;
		}
		if (value === '/create-agent' || value === '/create—agent') {
			send(command('set_mode', {mode: 'create_agent'}));
			return;
		}
		if (value === '/exit') {
			if (state.mode === 'agent_package') {
				store.dispatch({ui_type: 'clear_agent_package_selection'});
				return;
			}
			send(command('set_mode', {mode: null}));
			return;
		}
		if (value === '/run-agent-package' || value === '/run_agent_package') {
			store.dispatch({ui_type: 'set_agent_package_picker_open', open: true});
			send(command('list_agent_packages'));
			return;
		}
		if (value === '/agent-sessions') {
			const packageId = activePackageId(state.activeAgentPackage);
			if (!packageId) {
				store.dispatch({ui_type: 'notice', message: 'select an agent package first with /run-agent-package'});
				return;
			}
			store.dispatch({ui_type: 'set_agent_session_picker_open', open: true});
			send(command('list_agent_package_sessions', {payload: {package_id: packageId}}));
			return;
		}
		if (value === '/sessions') {
			if (state.mode === 'agent_package') {
				const packageId = activePackageId(state.activeAgentPackage);
				if (!packageId) {
					store.dispatch({ui_type: 'notice', message: 'select an agent package first with /run-agent-package'});
					return;
				}
				store.dispatch({ui_type: 'set_agent_session_picker_open', open: true});
				send(command('list_agent_package_sessions', {payload: {package_id: packageId}}));
				return;
			}
			send(command('list_sessions'));
			store.dispatch({ui_type: 'set_session_picker_open', open: true});
			return;
		}
		if (value === '/new-session') {
			if (state.mode === 'agent_package') {
				store.dispatch({ui_type: 'select_agent_session', sessionId: null});
				return;
			}
			store.dispatch({ui_type: 'set_session_picker_open', open: false});
			send(command('new_session'));
			return;
		}
		if (value.startsWith('/resume ')) {
			if (state.mode === 'agent_package') {
				store.dispatch({ui_type: 'select_agent_session', sessionId: value.slice('/resume '.length).trim() || null});
				return;
			}
			store.dispatch({ui_type: 'set_session_picker_open', open: false});
			send(command('switch_session', {session_id: value.slice('/resume '.length).trim()}));
			return;
		}
		if (value === '/scheduler' || value.startsWith('/scheduler ')) {
			const schedulerPayload = parseSchedulerCommand(value);
			if ('error' in schedulerPayload) {
				store.dispatch({ui_type: 'notice', message: schedulerPayload.error});
				return;
			}
			send(command('scheduler_manage', {payload: schedulerPayload}));
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
			if (state.mode === 'agent_package') {
				store.dispatch({
					ui_type: 'notice',
					message: `agent ${activePackageId(state.activeAgentPackage) || '-'}  session ${state.activeAgentSessionId ?? 'new'}`
				});
				return;
			}
			store.dispatch({ui_type: 'notice', message: `session ${state.sessionId ?? '-'}  mode ${state.mode ?? '-'}`});
			return;
		}
		if (value === '/tools') {
			store.dispatch({ui_type: 'notice', message: `tools ${factoryToolGroups.join(' | ')}`});
			return;
		}
		if (state.mode === 'agent_package') {
			const packageId = activePackageId(state.activeAgentPackage);
			if (!packageId) {
				store.dispatch({ui_type: 'notice', message: 'select an agent package first with /run-agent-package'});
				return;
			}
			store.dispatch({ui_type: 'local_user_message', message: value});
			send(command('run_agent_package', {
				payload: {
					package_id: packageId,
					session_id: state.activeAgentSessionId,
					message: value
				}
			}));
			return;
		}
		store.dispatch({ui_type: 'local_user_message', message: value});
		send(command('send_message', {message: value}));
	}

	return (
		<RuntimeStoreProvider store={store}>
			<ShellLayout>
				<LiveStatusLine />
				<SessionPanel
					onClose={() => store.dispatch({ui_type: 'set_session_picker_open', open: false})}
					onSelect={sessionId => {
						store.dispatch({ui_type: 'set_session_picker_open', open: false});
						send(command('switch_session', {session_id: sessionId}));
					}}
				/>
				<ConnectedHelpPanel />
				<AgentPackagePanel
					onClose={() => store.dispatch({ui_type: 'set_agent_package_picker_open', open: false})}
					onRefresh={() => send(command('list_agent_packages'))}
					onSelect={packageId => send(command('select_agent_package', {payload: {package_id: packageId}}))}
					onDelete={packageId => send(command('delete_agent_package', {payload: {package_id: packageId}}))}
				/>
				<AgentSessionPanel
					onClose={() => store.dispatch({ui_type: 'set_agent_session_picker_open', open: false})}
					onSelect={sessionId => store.dispatch({ui_type: 'select_agent_session', sessionId})}
				/>
				<TimelineView />
				<InterruptChoicePanel onSubmit={resumeInterrupt} />
				<InterruptPrompt />
				<ConnectedComposer
					onSubmit={onSubmit}
					onCancel={() => {
						store.dispatch({ui_type: 'notice', message: 'cancel requested'});
						send(command('cancel_runtime_request', {payload: {reason: 'user_cancelled'}}));
					}}
				/>
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

function ConnectedComposer({onSubmit, onCancel}: {onSubmit: (value: string) => void; onCancel: () => void}) {
	const mode = useStoreSelector(state => state.mode);
	const pendingInterrupt = useStoreSelector(state => state.pendingInterrupt);
	const runStatus = useStoreSelector(state => state.runStatus);
	const sessionPickerOpen = useStoreSelector(state => state.sessionPickerOpen);
	const agentPackagePickerOpen = useStoreSelector(state => state.agentPackagePickerOpen);
	const agentSessionPickerOpen = useStoreSelector(state => state.agentSessionPickerOpen);
	const contextCompressionRunning = useStoreSelector(
		state => state.contextActivity.status === 'running' && contextActivityStatusLabel(state.contextActivity) === '上下文压缩中'
	);
	const choiceInterrupt = isChoiceInterrupt(pendingInterrupt);
	const inputDisabled = runStatus === 'running' || sessionPickerOpen || agentPackagePickerOpen || agentSessionPickerOpen || contextCompressionRunning;
	return (
		<Composer
			prompt={`factory${mode ? `:${modeLabel(mode)}` : ''}`}
			onSubmit={onSubmit}
			onCancel={onCancel}
			getSuggestions={value => commandSuggestions(value, mode, pendingInterrupt?.event_type === 'tool_approval_requested')}
			disabled={inputDisabled || choiceInterrupt}
			disabledText={pickerDisabledText(sessionPickerOpen, agentPackagePickerOpen, agentSessionPickerOpen, choiceInterrupt, contextCompressionRunning)}
		/>
	);
}

function modeLabel(mode: FactoryMode): string {
	return mode === 'create_agent' ? 'create-agent' : mode === 'agent_package' ? 'agent-package' : mode;
}

function activePackageId(value: Record<string, unknown> | null): string {
	return typeof value?.package_id === 'string' ? value.package_id : '';
}

type SchedulerCommandPayload = {action: string; job_id?: string; limit?: number} | {error: string};

function parseSchedulerCommand(value: string): SchedulerCommandPayload {
	const parts = value.trim().split(/\s+/).filter(Boolean);
	const action = parts[1] ?? 'list';
	if (action === 'list') {
		return {action: 'list'};
	}
	if (action === 'runs') {
		const payload: {action: string; job_id?: string; limit?: number} = {action: 'runs'};
		if (parts[2] && !/^\d+$/.test(parts[2])) {
			payload.job_id = parts[2];
		}
		const limitText = payload.job_id ? parts[3] : parts[2];
		if (limitText && /^\d+$/.test(limitText)) {
			payload.limit = Number(limitText);
		}
		return payload;
	}
	if (action === 'run-now') {
		return _schedulerJobCommand('run_now', parts[2]);
	}
	if (['describe', 'pause', 'resume', 'delete'].includes(action)) {
		return _schedulerJobCommand(action, parts[2]);
	}
	return {error: 'usage: /scheduler <list|describe|runs|pause|resume|delete|run-now> [job_id] [limit]'};
}

function _schedulerJobCommand(action: string, jobId: string | undefined): SchedulerCommandPayload {
	if (!jobId) {
		return {error: `/scheduler ${action.replace('_', '-')} requires job_id`};
	}
	return {action, job_id: jobId};
}

function pickerDisabledText(
	sessionPickerOpen: boolean,
	agentPackagePickerOpen: boolean,
	agentSessionPickerOpen: boolean,
	choiceInterrupt: boolean,
	contextCompressionRunning: boolean
): string {
	if (sessionPickerOpen) {
		return 'select a factory session above';
	}
	if (agentPackagePickerOpen) {
		return 'select an agent package above';
	}
	if (agentSessionPickerOpen) {
		return 'select an agent session above';
	}
	if (choiceInterrupt) {
		return 'use the option panel above';
	}
	if (contextCompressionRunning) {
		return 'compressing conversation context';
	}
	return 'runtime running; waiting for event, tool approval, or interrupt';
}
