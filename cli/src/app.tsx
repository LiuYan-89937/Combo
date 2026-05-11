import React, {useEffect, useMemo, useReducer} from 'react';
import {Box, Text, useApp} from 'ink';
import {PythonBridge} from './bridge/PythonBridge.js';
import {routeFactoryEvent} from './bridge/eventRouter.js';
import {command, type FactoryCommand, type FactoryEvent, type FactoryMode} from './protocol.js';
import {initialFactoryUiState} from './state/factoryStore.js';
import {ChatView} from './views/ChatView.js';
import {CommandInput} from './views/CommandInput.js';
import {CreateAgentView} from './views/CreateAgentView.js';
import {ErrorPanel} from './views/ErrorPanel.js';
import {MessagesPanel} from './views/MessagesPanel.js';
import {ResourceInputPrompt} from './views/ResourceInputPrompt.js';
import {SessionPanel} from './views/SessionPanel.js';
import {ShellLayout} from './views/ShellLayout.js';
import {ToolApprovalPrompt} from './views/ToolApprovalPrompt.js';

export function App() {
	const {exit} = useApp();
	const [state, dispatch] = useReducer(routeFactoryEvent, initialFactoryUiState);
	const bridge = useMemo(() => new PythonBridge(), []);

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
			send(command('resume_interrupt', {payload: resumePayload(state.pendingInterrupt, value)}));
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
			dispatch({
				type: 'stage_delta',
				node_id: 'help',
				payload: {
					patch: {
						commands: ['/chat', '/create-agent', '/exit', '/sessions', '/new-session', '/resume <session_id>', '/stop <stage_id|off>', '/state on|off', '/messages on|off', '/quit']
					}
				}
			});
			return;
		}
		send(command('send_message', {message: value}));
	}

	return (
		<ShellLayout state={state}>
			<ErrorPanel message={state.lastError} />
			<SessionPanel state={state} />
			{state.mode === 'create_agent' ? <CreateAgentView state={state} /> : <ChatView streamingText={state.streamingText} />}
			<ToolApprovalPrompt event={state.pendingInterrupt} />
			<ResourceInputPrompt event={state.pendingInterrupt} />
			<MessagesPanel state={state} />
			<Box marginTop={1}>
				<Text color={state.ready ? 'green' : 'yellow'}>{state.ready ? 'ready' : 'starting bridge'}</Text>
			</Box>
			<CommandInput prompt={`factory${state.mode ? `:${modeLabel(state.mode)}` : ''}`} onSubmit={onSubmit} />
		</ShellLayout>
	);
}

function modeLabel(mode: FactoryMode): string {
	return mode === 'create_agent' ? 'create-agent' : mode;
}

function resumePayload(event: FactoryEvent, value: string): Record<string, unknown> {
	const payload = event.payload ?? {};
	if (payload.type === 'tool_approval') {
		return {approved: value.trim().toLowerCase() === '-y'};
	}
	if (event.type === 'resource_input_requested') {
		const requirements = (payload.requirements as Array<Record<string, unknown>>) ?? [];
		return {
			type: 'resource_input_answer',
			requirement_ids: requirements.map(item => String(item.requirement_id ?? '')).filter(Boolean),
			input_text: value
		};
	}
	if (payload.type === 'plan_review') {
		if (['继续', 'continue', 'c', 'yes', 'y'].includes(value.trim().toLowerCase())) {
			return {type: 'plan_review_result', decision: 'continue'};
		}
		return {type: 'plan_review_result', decision: 'revise', revision_instruction: value};
	}
	if (payload.type === 'requirement_clarification') {
		const questions = (payload.questions as Array<Record<string, unknown>>) ?? [];
		const answers = questions.map((question, index) => ({
			question_id: String(question.id ?? `question_${index + 1}`),
			selected_option_id: 'custom',
			selected_label: '自定义输入',
			custom_text: value
		}));
		return {type: 'requirement_clarification_answer', answers};
	}
	return {input_text: value};
}

