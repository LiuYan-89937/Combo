import {describe, expect, it, vi} from 'vitest';
import {contextActivityStatusLabel, memoryActivityStatusLabel} from './renderProjection.js';
import {createRuntimeStore} from './runtimeStore.js';
import {type FactoryEvent} from '../protocol.js';

describe('RuntimeStore', () => {
	it('batches model stream deltas before notifying subscribers', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();
		let notifications = 0;
		store.subscribe(() => {
			notifications += 1;
		});

		store.dispatch(event('run_started', {request_id: 'request-model'}));
		store.dispatch(event('model_stream_delta', {
			request_id: 'request-model',
			payload: {stream_id: 's1', delta: 'hello'}
		}));
		expect(notifications).toBe(0);
		expect(store.getSnapshot().modelStreams.s1).toBeUndefined();

		vi.advanceTimersByTime(32);
		expect(notifications).toBe(0);

		vi.advanceTimersByTime(1);
		expect(notifications).toBe(1);
		expect(store.getSnapshot().modelStreams.s1?.content).toBe('hello');

		store.destroy();
		vi.useRealTimers();
	});

	it('flushes pending stream deltas before immediate completion events', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-model'}));
		store.dispatch(event('model_stream_delta', {
			request_id: 'request-model',
			payload: {stream_id: 's1', delta: 'hello'}
		}));
		store.dispatch(event('model_message_completed', {
			request_id: 'request-model',
			payload: {stream_id: 's1', content: 'hello'}
		}));

		const stream = store.getSnapshot().modelStreams.s1;
		expect(stream?.content).toBe('hello');
		expect(stream?.active).toBe(false);
		expect(store.getSnapshot().transcript.at(-1)?.content).toBe('hello');

		store.destroy();
		vi.useRealTimers();
	});

	it('keeps non-user-visible model streams out of the transcript', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-model'}));
		store.dispatch(event('model_stream_delta', {
			request_id: 'request-model',
			payload: {stream_id: 's1', delta: 'hidden', visible_to_user: false}
		}));
		store.dispatch(event('model_message_completed', {
			request_id: 'request-model',
			payload: {stream_id: 's1', content: 'hidden', visible_to_user: false}
		}));

		expect(store.getSnapshot().modelStreams.s1?.content).toBe('hidden');
		expect(store.getSnapshot().transcript.some(item => item.content === 'hidden')).toBe(false);

		store.destroy();
		vi.useRealTimers();
	});

	it('does not duplicate snapshot-like content delivered through model deltas', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-model'}));
		store.dispatch(event('model_stream_delta', {
			request_id: 'request-model',
			payload: {stream_id: 's1', delta: '进化已完成'}
		}));
		vi.advanceTimersByTime(33);
		store.dispatch(event('model_stream_delta', {
			request_id: 'request-model',
			payload: {stream_id: 's1', delta: '进化已完成并自动发布'}
		}));
		vi.advanceTimersByTime(33);

		expect(store.getSnapshot().modelStreams.s1?.content).toBe('进化已完成并自动发布');
		expect(store.getSnapshot().transcript.at(-1)?.content).toBe('进化已完成并自动发布');

		store.destroy();
		vi.useRealTimers();
	});

	it('merges adjacent duplicate assistant messages from different streams', () => {
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-model'}));
		store.dispatch(event('model_message_completed', {
			request_id: 'request-model',
			payload: {stream_id: 's1', content: '进化已完成并自动发布。'}
		}));
		store.dispatch(event('model_message_completed', {
			request_id: 'request-model',
			payload: {stream_id: 's2', content: '进化已完成并自动发布。'}
		}));

		const assistantItems = store.getSnapshot().transcript.filter(item => item.role === 'assistant');
		expect(assistantItems).toHaveLength(1);
		expect(assistantItems[0]?.content).toBe('进化已完成并自动发布。');
		expect(assistantItems[0]?.metadata?.duplicate_stream_id).toBe('s2');
	});

	it('rebuilds transcript from session snapshot messages', () => {
		const store = createRuntimeStore();
		store.dispatch(event('session_started', {
			mode: 'chat',
			payload: {
				session: {
					session_id: 'session-1',
					current_mode: 'chat',
					snapshot: {
						messages: [
							{role: 'user', content: '你好'},
							{role: 'assistant', content: '你好，我在'}
						]
					}
				}
			}
		}));

		expect(store.getSnapshot().transcript.map(item => item.content)).toEqual(['你好', '你好，我在']);
		expect(store.getSnapshot().timelineItems.map(item => item.body)).toEqual(['你好', '你好，我在']);
		expect(store.getSnapshot().timelineItems[0]).toMatchObject({
			kind: 'message',
			role: 'user',
			source: 'transcript'
		});
	});

	it('clears session scoped projections when switching sessions', () => {
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-1'}));
		store.dispatch(event('tool_call_proposed', {
			request_id: 'request-1',
			payload: {tool_call_id: 'call-1', tool_name: 'ls', arguments: {path: '.'}}
		}));
		store.dispatch(event('scheduler_run_completed', {
			payload: {job_id: 'job-1', run_id: 'run-a', status: 'completed'}
		}));
		store.dispatch(event('run_failed', {
			request_id: 'request-1',
			payload: {message: 'old failure'}
		}));

		store.dispatch(event('session_switched', {
			payload: {
				session: {
					session_id: 'session-2',
					current_mode: 'chat',
					snapshot: {messages: [{role: 'user', content: '新的会话'}]}
				}
			}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.sessionId).toBe('session-2');
		expect(snapshot.transcript.map(item => item.content)).toEqual(['新的会话']);
		expect(snapshot.toolActivities).toEqual([]);
		expect(snapshot.schedulerActivities).toEqual([]);
		expect(snapshot.recentActivities).toEqual([]);
		expect(snapshot.pendingInterrupt).toBeNull();
		expect(snapshot.runStatus).toBe('idle');
		expect(snapshot.errors).toEqual([]);
	});

	it('ignores unscoped background run events for the interactive run status', () => {
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {
			request_id: null,
			payload: {command: 'scheduler_graph_run'}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.runStatus).toBe('idle');
		expect(snapshot.activeRequestId).toBeNull();
		expect(snapshot.events.at(-1)?.event_type).toBe('run_started');
	});

	it('ignores stale request events after the active request has changed', () => {
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-current', run_id: 'run-current'}));
		store.dispatch(event('run_completed', {request_id: 'request-old', run_id: 'run-old'}));

		let snapshot = store.getSnapshot();
		expect(snapshot.runStatus).toBe('running');
		expect(snapshot.activeRequestId).toBe('request-current');

		store.dispatch(event('run_completed', {request_id: 'request-current', run_id: 'run-current'}));
		store.dispatch(event('node_started', {
			request_id: 'request-current',
			run_id: 'run-current',
			node_id: 'late-node'
		}));

		snapshot = store.getSnapshot();
		expect(snapshot.runStatus).toBe('completed');
		expect(snapshot.activeRequestId).toBeNull();
		expect(snapshot.currentNodeId).toBeNull();
	});

	it('stores structured plan updates for the active request', () => {
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-plan'}));
		store.dispatch(event('plan_updated', {
			request_id: 'request-plan',
			node_id: 'tool_exec',
			payload: {
				version: 'plan_state.v0',
				goal: '分析论文并导出报告',
				status: 'active',
				current_step_id: 'step_1',
				source_node_id: 'tool_exec',
				steps: [
					{
						step_id: 'step_1',
						title: '读取论文',
						objective: '提取论文正文',
						status: 'in_progress',
						depends_on: [],
						acceptance_criteria: ['正文可用于分析'],
						tool_hints: ['pdf_analyzer']
					},
					{
						step_id: 'step_2',
						title: '导出 PDF',
						objective: '生成排版 PDF',
						status: 'pending',
						depends_on: ['step_1'],
						acceptance_criteria: [],
						tool_hints: ['report_to_pdf']
					}
				]
			}
		}));

		const plan = store.getSnapshot().currentPlan;
		expect(plan?.goal).toBe('分析论文并导出报告');
		expect(plan?.currentStepId).toBe('step_1');
		expect(plan?.steps.map(step => step.title)).toEqual(['读取论文', '导出 PDF']);
		expect(plan?.steps[0]?.toolHints).toEqual(['pdf_analyzer']);
	});

	it('ignores stale structured plan updates', () => {
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-current'}));
		store.dispatch(event('plan_updated', {
			request_id: 'request-old',
			payload: {
				status: 'active',
				steps: [{step_id: 'step_1', title: '旧计划', objective: '', status: 'in_progress'}]
			}
		}));

		expect(store.getSnapshot().currentPlan).toBeNull();
		expect(store.getSnapshot().events.at(-1)?.event_type).toBe('plan_updated');
	});

	it('does not treat node failure as a run terminal event', () => {
		const store = createRuntimeStore();

		store.dispatch(event('run_started', {request_id: 'request-node-failure'}));
		store.dispatch(event('node_failed', {
			request_id: 'request-node-failure',
			node_id: 'tool_exec',
			payload: {message: 'tool node failed'}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.runStatus).toBe('running');
		expect(snapshot.activeRequestId).toBe('request-node-failure');
		expect(snapshot.nodeStatuses.tool_exec?.status).toBe('failed');
		expect(snapshot.lastError).toContain('tool node failed');
	});

	it('summarizes session tool messages instead of showing raw JSON', () => {
		const store = createRuntimeStore();
		store.dispatch(event('session_started', {
			mode: 'chat',
			payload: {
				session: {
					session_id: 'session-1',
					current_mode: 'chat',
					snapshot: {
						messages: [
							{
								type: 'ToolMessage',
								name: 'write',
								content: JSON.stringify({
									type: 'tool_observation',
									status: 'completed',
									message: 'write completed',
									output: {path: 'draft.txt', bytes_written: 12}
								})
							}
						]
					}
				}
			}
		}));

		const item = store.getSnapshot().transcript[0];
		expect(item?.title).toBe('Tool / write');
		expect(item?.content).toContain('message: write completed');
		expect(item?.content).not.toContain('"type":"tool_observation"');
	});

	it('merges tool approval into the proposed tool card without transcript duplication', () => {
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-approval'}));
		store.dispatch(event('tool_call_proposed', {
			request_id: 'request-approval',
			payload: {
				tool_call_id: 'call-write-1',
				tool_name: 'write',
				arguments: {path: 'draft.txt', content: 'hello'}
			}
		}));
		store.dispatch(event('tool_approval_requested', {
			request_id: 'request-approval',
			payload: {
				type: 'tool_approval',
				requests: [
					{
						tool_call_id: 'call-write-1',
						tool_name: 'write',
						args: {path: 'draft.txt', content: 'hello'},
						summary: 'write draft.txt'
					}
				]
			}
		}));
		store.dispatch(event('interrupt_requested', {
			request_id: 'request-approval',
			payload: {
				type: 'tool_approval',
				requests: [
					{
						tool_call_id: 'call-write-1',
						tool_name: 'write',
						args: {path: 'draft.txt', content: 'hello'}
					}
				]
			}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.toolActivities).toHaveLength(1);
		expect(snapshot.toolActivities[0]?.status).toBe('approval');
		expect(snapshot.toolActivities[0]?.approvalState).toBe('pending');
		expect(snapshot.timelineItems.some(item => item.title === 'Tool approval write')).toBe(true);
		expect(snapshot.transcript.some(item => item.title === 'Tool Approval Requested')).toBe(false);
	});

	it('renders capability realization interrupts as assistant dialogue', () => {
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-question'}));
		store.dispatch(event('interrupt_requested', {
			request_id: 'request-question',
			payload: {
				type: 'assistant_question',
				presentation: 'assistant_dialogue',
				resume_kind: 'answer',
				title: '补充制造信息',
				message: '请告诉我这个 Agent 可以使用的外部资源。',
				summary: '可以直接用自然语言回答。'
			}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.runStatus).toBe('interrupted');
		expect(snapshot.pendingInterrupt?.payload?.type).toBe('assistant_question');
		expect(snapshot.transcript[0]?.role).toBe('assistant');
		expect(snapshot.transcript[0]?.title).toBe('补充制造信息');
		expect(snapshot.transcript[0]?.content).toContain('请告诉我这个 Agent 可以使用的外部资源。');
		expect(snapshot.transcript[0]?.content).toContain('可以直接用自然语言回答。');
	});

	it('keeps timeline as stable store view state across unrelated ui changes', () => {
		const store = createRuntimeStore();
		store.dispatch({ui_type: 'local_user_message', message: 'hello'});

		const timeline = store.getSnapshot().timelineItems;
		expect(timeline).toHaveLength(1);
		expect(timeline[0]?.title).toBe('You');
		expect(timeline[0]).toMatchObject({
			kind: 'message',
			role: 'user',
			source: 'transcript'
		});

		store.dispatch({ui_type: 'set_tool_grep', query: 'write'});
		expect(store.getSnapshot().timelineItems).toBe(timeline);
	});

	it('resolves tool approval without creating a second raw tool activity', () => {
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-approval'}));
		store.dispatch(event('tool_call_proposed', {
			request_id: 'request-approval',
			payload: {
				tool_call_id: 'call-write-1',
				tool_name: 'write',
				arguments: {path: 'draft.txt'}
			}
		}));
		store.dispatch(event('tool_approval_requested', {
			request_id: 'request-approval',
			payload: {
				type: 'tool_approval',
				requests: [{tool_call_id: 'call-write-1', tool_name: 'write', args: {path: 'draft.txt'}}]
			}
		}));
		expect(store.getSnapshot().pendingInterrupt?.event_type).toBe('tool_approval_requested');
		store.dispatch(event('run_started', {request_id: 'request-resume'}));
		store.dispatch(event('tool_approval_resolved', {
			request_id: 'request-resume',
			payload: {action: 'deny', approved: false}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.pendingInterrupt).toBeNull();
		expect(snapshot.runStatus).toBe('running');
		expect(snapshot.toolActivities).toHaveLength(1);
		expect(snapshot.toolActivities[0]?.approvalState).toBe('rejected');
		expect(snapshot.toolActivities[0]?.toolName).toBe('write');
	});

	it('marks trusted tool approval without creating a second activity', () => {
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-approval'}));
		store.dispatch(event('tool_call_proposed', {
			request_id: 'request-approval',
			payload: {
				tool_call_id: 'call-write-1',
				tool_name: 'write',
				arguments: {path: 'draft.txt'}
			}
		}));
		store.dispatch(event('tool_approval_requested', {
			request_id: 'request-approval',
			payload: {
				type: 'tool_approval',
				requests: [{tool_call_id: 'call-write-1', tool_name: 'write', args: {path: 'draft.txt'}}]
			}
		}));
		store.dispatch(event('run_started', {request_id: 'request-resume'}));
		store.dispatch(event('tool_approval_resolved', {
			request_id: 'request-resume',
			payload: {action: 'trust_tool', approved: true, trust_scope: 'tool'}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.toolActivities).toHaveLength(1);
		expect(snapshot.toolActivities[0]?.approvalState).toBe('trusted');
	});

	it('shows a transient memory write hint when cross-session memory is queued', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();

		store.dispatch(event('memory_write_queued', {
			payload: {
				job_id: 'memory-job-1',
				namespace: ['memory', 'factory', 'default']
			}
		}));

		expect(store.getSnapshot().memoryActivity.status).toBe('writing');
		expect(memoryActivityStatusLabel(store.getSnapshot().memoryActivity)).toContain('后台写入中');
		expect(store.getSnapshot().memoryActivity.jobId).toBe('memory-job-1');

		vi.advanceTimersByTime(7999);
		expect(store.getSnapshot().memoryActivity.status).toBe('writing');

		vi.advanceTimersByTime(1);
		expect(store.getSnapshot().memoryActivity.status).toBe('idle');

		store.destroy();
		vi.useRealTimers();
	});

	it('briefly shows completion when memory write finishes', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();

		store.dispatch(event('memory_write_queued', {
			payload: {job_id: 'memory-job-1'}
		}));
		store.dispatch(event('memory_write_completed', {
			timestamp: '2026-05-17T00:00:01Z',
			payload: {
				job_id: 'memory-job-1',
				status: 'completed',
				action_counts: {add: 1}
			}
		}));

		expect(store.getSnapshot().memoryActivity.status).toBe('completed');
		expect(memoryActivityStatusLabel(store.getSnapshot().memoryActivity)).toContain('已更新');

		vi.advanceTimersByTime(3000);
		expect(store.getSnapshot().memoryActivity.status).toBe('idle');

		store.destroy();
		vi.useRealTimers();
	});

	it('shows context activity when context is injected', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-context'}));

		store.dispatch(event('context_injection_completed', {
			request_id: 'request-context',
			payload: {
				node_id: 'answer',
				item_count: 3,
				token_estimate: 420
			}
		}));

		expect(store.getSnapshot().contextActivity.status).toBe('completed');
		expect(contextActivityStatusLabel(store.getSnapshot().contextActivity)).toContain('上下文已注入');
		expect(store.getSnapshot().contextActivity.payload.item_count).toBe(3);

		vi.advanceTimersByTime(2500);
		expect(store.getSnapshot().contextActivity.status).toBe('idle');

		store.destroy();
		vi.useRealTimers();
	});

	it('archives knowledge preview and activity events without exposing document text', () => {
		const store = createRuntimeStore();

		store.dispatch(event('knowledge_source_preview_available', {
			payload: {
				source_id: 'docs',
				mode: 'rag',
				status: 'completed',
				preview: {
					source_id: 'docs',
					source_type: 'filesystem',
					display_name: 'Project docs',
					estimated_documents: 3,
					requires_embedding: true
				}
			}
		}));

		const snapshot = store.getSnapshot();
		expect(snapshot.knowledgeActivities).toHaveLength(1);
		expect(snapshot.knowledgeActivities[0]).toMatchObject({
			sourceId: 'docs',
			mode: 'rag',
			status: 'completed'
		});
		expect(snapshot.transcript.at(-1)).toMatchObject({
			role: 'knowledge',
			title: 'Knowledge / preview'
		});
		expect(snapshot.timelineItems.some(item => item.kind === 'knowledge' && item.source === 'knowledge')).toBe(true);
		expect(snapshot.transcript.at(-1)?.content).toContain('来源：Project docs');
		expect(snapshot.transcript.at(-1)?.content).not.toContain('document text');
	});

	it('shows skipped context compression separately from completed compression', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-context'}));

		store.dispatch(event('context_compression_skipped', {
			request_id: 'request-context',
			payload: {
				node_id: 'answer',
				status: 'skipped',
				token_estimate_before: 400,
				token_estimate_after: 400
			}
		}));

		expect(store.getSnapshot().contextActivity.status).toBe('skipped');
		expect(contextActivityStatusLabel(store.getSnapshot().contextActivity)).toContain('跳过');

		vi.advanceTimersByTime(2500);
		expect(store.getSnapshot().contextActivity.status).toBe('idle');

		store.destroy();
		vi.useRealTimers();
	});

	it('keeps compression running until a terminal context event arrives', () => {
		vi.useFakeTimers();
		const store = createRuntimeStore();
		store.dispatch(event('run_started', {request_id: 'request-context'}));

		store.dispatch(event('context_compression_started', {
			request_id: 'request-context',
			payload: {node_id: 'answer', status: 'started'}
		}));

		vi.advanceTimersByTime(10_000);
		expect(store.getSnapshot().contextActivity.status).toBe('running');
		expect(contextActivityStatusLabel(store.getSnapshot().contextActivity)).toContain('压缩中');

		store.dispatch(event('context_compression_completed', {
			request_id: 'request-context',
			payload: {node_id: 'answer', status: 'completed'}
		}));
		vi.advanceTimersByTime(2500);
		expect(store.getSnapshot().contextActivity.status).toBe('idle');

		store.destroy();
		vi.useRealTimers();
	});
});

function event(
	event_type: FactoryEvent['event_type'],
	patch: Partial<FactoryEvent> = {}
): FactoryEvent {
	return {
		event_id: `${event_type}-event`,
		event_type,
		protocol_version: 'factory_frontend.v1',
		producer_type: 'test',
		request_id: null,
		run_id: 'run-1',
		session_id: 'session-1',
		thread_id: null,
		mode: 'chat',
		graph_id: 'test',
		node_id: 'node-1',
		node_label: null,
		node_kind: null,
		stage_id: null,
		span_id: null,
		parent_span_id: null,
		sequence: 1,
		timestamp: '2026-05-17T00:00:00Z',
		severity: null,
		message: null,
		payload: {},
		...patch
	};
}
