/**
 * Runtime Store - 核心状态管理
 *
 * 基于协议文档的 Request-Scoped Reducer 规则实现
 * 参考 CLI 的 runtimeStore.ts
 */
import { defineStore } from 'pinia'
import type {
  RuntimeFrontendEvent,
  RuntimeMode,
  RuntimeViewState,
  ActiveRequestView,
  ChatMessagePart,
  ConversationScopeState,
  ConversationTurn,
  ModelStream,
  TranscriptItem,
  RunStatus,
} from '@/types/protocol'
import {
  buildConversationScopeState,
  normalizeConversationScopeState,
} from './runtime/conversationState'
import {
  ensureConversationTurn,
} from './runtime/conversationMutations'
import {
  applyContextActivityEvent,
  applyKnowledgeActivityEvent,
  applyMemoryActivityEvent,
  applyRuntimeActivityEvent,
  applySchedulerActivityEvent,
  recordDebugEvent,
  recordTimelineEvent,
} from './runtime/activityMutations'
import {
  interruptMessage,
  interruptType,
  isBackgroundEvent,
  isRequestScopedEvent,
  isRequestTerminalEvent,
  isRestorableProcessStateEvent,
  isSchedulerRequest,
  isUserInputInterrupt,
  shouldRenderInterruptMessage,
} from './runtime/eventUtils'
import {
  applyNodeCompleted,
  applyNodeFailed,
  applyNodeProgress,
  applyNodeStarted,
  applyStageCompleted,
  applyStageFailed,
  applyStageStarted,
} from './runtime/graphMutations'
import {
  applyModelCallStarted,
  applyModelMessageCompleted,
  applyModelReasoningCompleted,
  applyModelReasoningDelta,
  applyModelStreamDelta,
} from './runtime/modelMutations'
import {
  applyMessageCompleted,
  applyMessagePartCompleted,
  applyMessagePartDelta,
  applyMessageStarted,
  reconcileAssistantDialogueInterrupt,
  reconcileCompletedAssistantSnapshot,
} from './runtime/messageMutations'
import {
  agentPackageConversationScope,
  agentPackageScopeInfoFromEvent,
  conversationScopeForMode,
  isMoreSpecificConversationScope,
  scopeFromEventPayload,
  scopeFromMessageMetadata,
  scopeFromRequestPayload,
} from './runtime/scopes'
import {
  agentPackageSessionSnapshotView,
} from './runtime/sessionSnapshots'
import {
  sessionDeletionFromPayload,
  sessionDeletionIncludes,
} from './runtime/sessionDeletion'
import {
  attachmentPart,
  errorPart,
  textPart,
} from './runtime/messageParts'
import {
  applyExtensionsEvent,
  applyWorkspaceEvent,
  markSchedulerRunNoticeRead,
  dismissSchedulerRunNoticeFromConversation,
} from './runtime/resourceMutations'
import {
  applyToolApprovalRequested,
  applyToolApprovalResolved,
  finalizeToolActivitiesForRequest,
  applyToolLifecycleEvent,
} from './runtime/toolMutations'
import {
  detectBrowserLocale,
  localeStorageKey,
  normalizeLocale,
  translate,
} from '@/i18n'
import { dismissPlanCapsule, restorePlanCapsule } from '@/utils/planCapsuleDismissals'
import {
  isStandaloneAgentSession,
} from '@/utils/sessionPresentation'

// 事件去重集合
const processedEventIds = new Set<string>()

export const useRuntimeStore = defineStore('runtime', {
  state: (): RuntimeViewState => ({
    protocolVersion: 'combo_frontend.v1',
    connectionStatus: 'disconnected',
    runtimeOptions: {
      context_window_tokens: null,
      context_window_tokens_source: 'unset',
    },
    activeRequestId: null,
    activeRequests: {},
    runStatus: 'idle',
    pendingInterrupt: null,
    currentMode: null,
    activeMainSessionId: null,
    activeAgentSessionId: null,
    activeWorkspaceId: null,
    currentRunId: null,
    nodes: {},
    stages: {},
    modelStreams: {},
    tools: [],
    currentPlan: null,
    activeConversationScope: null,
    conversationScopes: {},
    transcript: [],
    conversationTurns: [],
    timeline: [],
    debugEvents: [],
    runtimeActivity: { status: 'idle' },
    contextActivity: { status: 'idle' },
    contextWindow: null,
    memoryActivity: { status: 'idle' },
    knowledgeActivity: [],
    schedulerActivity: [],
    workspaceEntries: [],
    workspaceRoots: [],
    workspaceFile: null,
    knowledgeSources: [],
    knowledgeDocuments: [],
    knowledgeResults: [],
    knowledgeDocument: null,
    schedulerJobs: [],
    schedulerToolOptions: [],
    schedulerRunNotices: [],
    extensionItems: [],
    extensionTestResult: null,
    extensionBindings: { mcp_server_ids: [], skill_ids: [] },
    toolPermissions: null,
    sessions: [],
    agentPackages: [],
    agentPackageSelectionIntent: { packageId: null, purpose: null },
    selectedAgentPackage: null,
    agentSessions: [],
  }),

  getters: {
    // 输入只因需要专门 UI 处理的中断锁定；运行中不再作为跨会话输入锁。
    isInputLocked: (state): boolean => {
      return state.runStatus === 'interrupted' && !isUserInputInterrupt(state.pendingInterrupt)
    },

    isAwaitingUserInputInterrupt: (state): boolean => {
      return isUserInputInterrupt(state.pendingInterrupt)
    },

    // 当前是否有活跃的运行
    hasActiveRun: (state): boolean => {
      if (!state.activeRequestId || state.runStatus !== 'running') return false
      const request = state.activeRequests[state.activeRequestId]
      if (!request || request.status !== 'running' || request.payload?.stop_requested_at) return false
      return !['stopped', 'cancelled'].includes(String(request.payload?.dispatch_state || ''))
    },

    queuedRequestCount: (state): number => {
      return Object.values(state.activeRequests).filter((request) => (
        request.source === 'user'
        && request.status === 'running'
        && request.payload?.dispatch_state === 'queued'
        && (!state.activeConversationScope || request.conversationScope === state.activeConversationScope)
      )).length
    },

    queuedMessages: (state) => {
      return Object.values(state.activeRequests)
        .filter((request) => (
          request.source === 'user'
          && request.status === 'running'
          && request.payload?.dispatch_state === 'queued'
          && (!state.activeConversationScope || request.conversationScope === state.activeConversationScope)
        ))
        .sort((left, right) => {
          const positionDelta = Number(left.payload?.queue_position || 0) - Number(right.payload?.queue_position || 0)
          return positionDelta || Date.parse(left.startedAt) - Date.parse(right.startedAt)
        })
        .map((request) => {
          const turn = state.conversationTurns.find((item) => item.requestId === request.requestId)
          return {
            requestId: request.requestId,
            content: String(turn?.userMessage?.content || request.payload?.message || ''),
            position: Number(request.payload?.queue_position || 0),
          }
        })
    },

    // 获取可见的模型流（用于主 transcript）
    visibleModelStreams: (state): ModelStream[] => {
      return Object.values(state.modelStreams).filter((s) => s.visibleToUser)
    },

    activeTurn: (state): ConversationTurn | null => {
      if (state.activeRequestId) {
        return state.conversationTurns.find((turn) => turn.requestId === state.activeRequestId) || null
      }
      return state.conversationTurns[state.conversationTurns.length - 1] || null
    },

    // 获取当前审批请求
    currentApprovalRequests: (state): any[] => {
      if (!state.pendingInterrupt) return []
      const payload = state.pendingInterrupt.payload
      return payload?.requests || []
    },

    // 格式化的计划摘要
    planSummary: (state): string => {
      if (!state.currentPlan) return ''
      const steps = state.currentPlan.steps
      const summary = steps
        .map((s) => {
          const statusIcon = {
            completed: '✓',
            in_progress: '→',
            failed: '✗',
            pending: '○',
            skipped: '⊘',
          }[s.status] || '?'
          return `${statusIcon} ${s.title}`
        })
        .join(' → ')
      return summary
    },
  },

  actions: {
    /**
     * 处理事件 - 主 reducer
     */
    handleEvent(event: RuntimeFrontendEvent) {
      // 1. 事件去重
      if (processedEventIds.has(event.event_id)) {
        console.debug('Duplicate event ignored:', event.event_id)
        return
      }
      processedEventIds.add(event.event_id)

      // 2. 协议版本验证
      if (event.protocol_version !== this.protocolVersion) {
        console.error('Protocol version mismatch:', event.protocol_version)
        return
      }

      if (event.payload?.runtime_role === 'temporary') {
        const pendingRunId = this.pendingInterrupt?.run_id
        if (
          pendingRunId === event.run_id
          && ['run_started', 'run_completed', 'run_failed', 'run_cancelled'].includes(event.event_type)
        ) {
          this.pendingInterrupt = null
          if (!this.activeRequestId) this.runStatus = 'idle'
        }
        const isChildQuestion = (
          event.event_type === 'interrupt_requested'
          && String(event.payload?.type || '').trim() === 'ask_user'
        )
        if (event.event_type !== 'tool_approval_requested' && !isChildQuestion) return
      }

      // 3. Request-scoped 事件过滤
      if (
        event.request_id
        && isRequestScopedEvent(event.event_type)
        && this.activeRequests[event.request_id]?.payload?.stop_requested_at
        && !isRequestTerminalEvent(event.event_type)
      ) {
        return
      }
      const isRequestScoped = isRequestScopedEvent(event.event_type)
      const requestScope = isRequestScoped ? this._resolveRequestScopeForEvent(event) : null
      if (requestScope && requestScope !== this.activeConversationScope) {
        this._dispatchEventToConversationScope(requestScope, event)
        return
      }
      // 4. 路由到具体处理器
      this._dispatchEvent(event)

      // 5. 记录到 timeline
      this._recordTimelineEvent(event)
    },

    /**
     * 事件分发器
     */
    _dispatchEvent(event: RuntimeFrontendEvent) {
      const { event_type: type, payload } = event

      // Runtime lifecycle
      if (type === 'runtime_ready') {
        this._handleRuntimeOptionsChanged(event)
        this._restoreActiveRequestsFromRuntimeSnapshot(event)
        console.info('Runtime ready')
      } else if (type === 'mode_changed') {
        this._handleModeChanged(event)
      }

      // Runtime request dispatch
      else if (type === 'runtime_request_queued') {
        this._handleRuntimeRequestQueued(event)
      } else if (type === 'runtime_request_steering') {
        this._handleRuntimeRequestSteering(event)
      } else if (type === 'runtime_request_dispatched') {
        this._handleRuntimeRequestDispatched(event)
      }

      // Agent packages
      else if (type === 'agent_packages_listed') {
        this.agentPackages = payload?.packages || []
      } else if (type === 'agent_package_selected') {
        if (!this.ownsAgentPackageSelection(event)) return
        this.currentMode = event.mode || this.currentMode
        this.selectedAgentPackage = payload?.package || null
        this.agentSessions = payload?.sessions
          ? payload.sessions.filter(isStandaloneAgentSession)
          : this.agentSessions
      } else if (type === 'agent_package_deleted') {
        const deletedPackageId = payload?.package_id
        this.agentPackages = payload?.packages || this.agentPackages.filter((pkg) => pkg.package_id !== deletedPackageId)
        if (this.selectedAgentPackage?.package_id === deletedPackageId) {
          this.selectedAgentPackage = null
        }
      } else if (type === 'agent_package_sessions_listed') {
        this.agentSessions = (payload?.sessions || []).filter(isStandaloneAgentSession)
      } else if (type === 'agent_package_session_loaded') {
        this._restoreAgentPackageSession(payload?.session, payload?.package_id)
      } else if (type === 'agent_package_session_deleted') {
        const deletion = sessionDeletionFromPayload(payload)
        const deletedSessionIds = new Set(deletion.sessionIds)
        const deletedCurrentSession = sessionDeletionIncludes(deletion, this.activeAgentSessionId)
        this.agentSessions = payload?.sessions
          ? payload.sessions.filter(isStandaloneAgentSession)
          : this.agentSessions.filter((session: any) => !deletedSessionIds.has(session.session_id))
        if (deletedCurrentSession) {
          const packageId = String(payload?.package_id || this.selectedAgentPackage?.package_id || '').trim() || null
          this.showEmptyAgentPackageSession(packageId)
        }
        this._deleteConversationScopesForSessions(deletion.sessionIds)
      }

      // Run lifecycle
      else if (type === 'run_started') {
        this._handleRunStarted(event)
      } else if (type === 'run_completed') {
        this._handleRunCompleted(event)
      } else if (type === 'run_cancelled') {
        this._handleRunCancelled(event)
      } else if (type === 'run_failed') {
        this._handleRunFailed(event)
      } else if (type === 'runtime_paused') {
        // 暂停提示，不改变状态
      } else if (type === 'runtime_resumed') {
        this.runStatus = 'running'
        this.pendingInterrupt = null
      } else if (type === 'interrupt_requested') {
        this._handleInterruptRequested(event)
      }

      // Stage lifecycle
      else if (type === 'stage_started') {
        this._handleStageStarted(event)
      } else if (type === 'stage_completed') {
        this._handleStageCompleted(event)
      } else if (type === 'stage_failed') {
        this._handleStageFailed(event)
      }

      // Node lifecycle
      else if (type === 'node_started') {
        this._handleNodeStarted(event)
      } else if (type === 'node_progress') {
        this._handleNodeProgress(event)
      } else if (type === 'node_completed') {
        this._handleNodeCompleted(event)
      } else if (type === 'node_failed') {
        this._handleNodeFailed(event)
      }

      // Plan
      else if (type === 'plan_updated') {
        this._handlePlanUpdated(event)
      }

      // User-facing runtime activity
      else if (type === 'runtime_activity_updated') {
        applyRuntimeActivityEvent(this, event)
      }

      else if (type === 'delegated_task_terminal') {
        this._handleDelegatedTaskTerminal(event)
      }

      // Message parts
      else if (type === 'message_started') {
        applyMessageStarted(this, event)
      } else if (type === 'message_part_delta') {
        applyMessagePartDelta(this, event)
      } else if (type === 'message_part_completed') {
        applyMessagePartCompleted(this, event)
      } else if (type === 'message_completed') {
        applyMessageCompleted(this, event)
      }

      // Model streams
      else if (type === 'model_call_started') {
        this._handleModelCallStarted(event)
      } else if (type === 'model_reasoning_delta') {
        this._handleModelReasoningDelta(event)
      } else if (type === 'model_reasoning_completed') {
        this._handleModelReasoningCompleted(event)
      } else if (type === 'model_stream_delta') {
        this._handleModelStreamDelta(event)
      } else if (type === 'model_message_completed') {
        this._handleModelMessageCompleted(event)
      }

      // Tools
      else if (type === 'tool_call_proposed') {
        this._handleToolCallProposed(event)
      } else if (type === 'tool_approval_requested') {
        this._handleToolApprovalRequested(event)
      } else if (type === 'tool_approval_resolved') {
        this._handleToolApprovalResolved(event)
      } else if (type === 'tool_call_started') {
        this._handleToolCallStarted(event)
      } else if (type === 'tool_call_output_delta') {
        this._handleToolCallStarted(event)
      } else if (type === 'tool_call_completed') {
        this._handleToolCallCompleted(event)
      } else if (type === 'tool_call_failed') {
        this._handleToolCallFailed(event)
      } else if (type === 'tool_contract_invalid') {
        this._handleToolCallFailed(event)
      } else if (type === 'tool_observation_available') {
        this._handleToolObservation(event)
      }

      // Context
      else if (type.startsWith('context_')) {
        this._handleContextEvent(event)
      }

      // Memory
      else if (type.startsWith('memory_')) {
        this._handleMemoryEvent(event)
      }

      // Knowledge
      else if (type.startsWith('knowledge_')) {
        this._handleKnowledgeEvent(event)
      }

      // Workspace
      else if (type.startsWith('workspace_')) {
        this._handleWorkspaceEvent(event)
      }

      // Extensions
      else if (type === 'extension_configs_listed' || type === 'extension_config_updated' || type === 'extension_config_tested' || type === 'extension_config_test_output_delta' || type === 'extension_skillhub_result') {
        this._handleExtensionsEvent(event)
      }

      // Scheduler
      else if (type.startsWith('scheduler_')) {
        this._handleSchedulerEvent(event)
      }

      // Error
      else if (type === 'error') {
        this._handleError(event)
      }

      // Debug patch
      else if (type === 'debug_patch') {
        this._recordDebugEvent(event)
      }
    },

    /**
     * Run lifecycle handlers
     */
    _handleModeChanged(event: RuntimeFrontendEvent) {
      const nextMode = event.mode || event.payload?.mode || null
      this.currentMode = nextMode
      const nextScope = conversationScopeForMode(nextMode, {
        ...(event.payload || {}),
        session_id: event.session_id || event.payload?.session_id || this.activeMainSessionId,
      })
      if (nextScope) {
        this._switchConversationScope(nextScope)
      }
    },

    _handleRuntimeOptionsChanged(event: RuntimeFrontendEvent) {
      const options = event.payload?.options
      if (!options || typeof options !== 'object') return
      this.runtimeOptions = {
        ...this.runtimeOptions,
        ...options,
        context_window_tokens: optionalPositiveInteger(options.context_window_tokens),
        context_window_tokens_source: String(options.context_window_tokens_source || 'unset'),
      }
    },

    _handleDelegatedTaskTerminal(event: RuntimeFrontendEvent) {
      const taskId = String(event.payload?.task_id || '').trim()
      const terminalStatus = String(event.payload?.terminal_status || '').trim()
      if (!taskId || !['result', 'failed', 'cancelled'].includes(terminalStatus)) return
      const existing = this.transcript.find(message => String(message.metadata?.task_id || '') === taskId)
      if (existing) return
      const taskName = String(event.payload?.task_name || '').trim()
      this.transcript.push({
        id: `delegated-delivery:${taskId}`,
        role: 'system',
        content: '',
        timestamp: event.timestamp,
        status: 'completed',
        parts: [{
          id: `delegated-delivery:${taskId}:part`,
          type: 'delegated_delivery',
          taskId,
          taskName,
          terminalStatus: terminalStatus as 'result' | 'failed' | 'cancelled',
          status: 'completed',
          createdAt: event.timestamp,
          updatedAt: event.timestamp,
        }],
        metadata: {
          delegated_delivery: true,
          task_id: taskId,
          task_name: taskName,
          terminal_status: terminalStatus,
        },
      })
    },

    _restoreActiveRequestsFromRuntimeSnapshot(event: RuntimeFrontendEvent) {
      const activeRequests = Array.isArray(event.payload?.active_requests)
        ? event.payload.active_requests.map(activeRequestViewFromPayload).filter(Boolean) as ActiveRequestView[]
        : []
      const activeRequestIds = new Set(activeRequests.map(request => request.requestId))

      if (activeRequests.length === 0) {
        this._clearStaleForegroundRun()
        this._reconcileRestoredTurnStatuses(activeRequestIds)
        return
      }

      activeRequests.forEach((request) => {
        const scopeEvent = {
          ...event,
          request_id: request.requestId,
          run_id: request.runId,
          mode: request.mode,
          session_id: request.payload?.session_id || null,
          payload: request.payload,
        } satisfies RuntimeFrontendEvent
        request.conversationScope = request.conversationScope
          || scopeFromRequestPayload(request.mode, request.payload)
          || scopeFromEventPayload(scopeEvent)
          || null
        this.activeRequests[request.requestId] = request
      })

      const foregroundRequests = activeRequests.filter((request) => (
        !request.background
        && request.status === 'running'
        && request.payload?.dispatch_state !== 'queued'
      ))
      this._reconcileRestoredTurnStatuses(activeRequestIds)
      if (foregroundRequests.length === 0) return

      const currentActive = this.activeRequestId ? this.activeRequests[this.activeRequestId] : null
      const preferred =
        (currentActive?.status === 'running' && foregroundRequests.find((item) => item.requestId === currentActive.requestId)) ||
        foregroundRequests.find((request) => request.conversationScope && request.conversationScope === this.activeConversationScope) ||
        foregroundRequests[foregroundRequests.length - 1]

      this.activeRequestId = preferred.requestId
      const runtimeStatus = String(preferred.payload?.runtime_status || preferred.payload?.dispatch_state || '')
      this.runStatus = runtimeStatus === 'waiting_approval' || runtimeStatus === 'waiting_external'
        ? 'interrupted'
        : runtimeStatus === 'stopping'
          ? 'stopping'
          : 'running'
      this.currentRunId = preferred.runId
      if (this.runStatus !== 'interrupted') this.pendingInterrupt = null
      if (!this.currentMode && preferred.mode) {
        this.currentMode = preferred.mode
      }
      const turn = ensureConversationTurn(this, preferred.requestId, preferred.startedAt)
      turn.status = this.runStatus
      turn.completedAt = null
    },

    _clearStaleForegroundRun() {
      if (!this.activeRequestId || !['running', 'stopping'].includes(this.runStatus)) return
      const request = this.activeRequests[this.activeRequestId]
      if (request?.background) return
      this.activeRequestId = null
      this.runStatus = 'idle'
    },

    _handleRunStarted(event: RuntimeFrontendEvent) {
      if (isSchedulerRequest(event.request_id)) {
        this._registerActiveRequest(event, 'running')
        return
      }
      this._registerActiveRequest(event, 'running')
      const request = event.request_id ? this.activeRequests[event.request_id] : null
      if (request?.background) return
      this._syncAgentSessionFromRunEvent(event)
      this._setRequestDispatchState(event.request_id, 'running', event.payload)
      // 清空当前 run 的临时状态
      this.activeRequestId = event.request_id || null
      this.currentRunId = event.run_id || null
      this.runStatus = 'running'
      this.pendingInterrupt = null
      this.nodes = {}
      this.stages = {}
      this.modelStreams = {}
      this.tools = []
      this.currentPlan = null
      this.runtimeActivity = { status: 'idle' }
      const turn = ensureConversationTurn(this, event.request_id || null, event.timestamp)
      turn.status = 'running'
      turn.startedAt = event.timestamp
      turn.errorMessage = null
      turn.metadata = {
        ...turn.metadata,
        mode: event.mode || turn.metadata?.mode || null,
      }
      // 不清空 transcript，累积历史对话
    },

    _handleRunCompleted(event: RuntimeFrontendEvent) {
      const contextWindow = event.payload?.context_window
      if (contextWindow && typeof contextWindow === 'object' && !Array.isArray(contextWindow)) {
        applyContextActivityEvent(this, {
          ...event,
          event_type: 'context_window_updated',
          payload: contextWindow,
        })
      }
      const reportedStatus = String(event.payload?.finish_status || event.payload?.status || '')
      const completedStatus: RunStatus = reportedStatus === 'stopped'
        ? 'stopped'
        : reportedStatus === 'waiting_for_workers'
          ? 'waiting_for_workers'
          : 'completed'
      const existingRequest = event.request_id ? this.activeRequests[event.request_id] : null
      if (existingRequest?.background) {
        this._completeActiveRequest(event, completedStatus)
        reconcileCompletedAssistantSnapshot(this, event)
        return
      }
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, completedStatus)
        return
      }
      this._completeActiveRequest(event, completedStatus)
      if (completedStatus === 'stopped') {
        finalizeToolActivitiesForRequest(
          this,
          event.request_id || this.activeRequestId || null,
          event.timestamp,
          'cancelled',
          event.payload?.stop_reason || event.payload?.reason || undefined,
        )
      }
      this.runStatus = completedStatus
      const requestId = event.request_id || this.activeRequestId || null
      reconcileCompletedAssistantSnapshot(this, event)
      const turn = ensureConversationTurn(this, requestId, event.timestamp)
      turn.status = completedStatus
      turn.completedAt = event.timestamp
      if (!this.activeRequestId || this.activeRequestId === requestId) {
        this.activeRequestId = null
      }
      this.pendingInterrupt = null

      // 同步 agent session
      this._syncAgentSessionFromRunEvent(event)
    },

    _handleRunCancelled(event: RuntimeFrontendEvent) {
      const existingRequest = event.request_id ? this.activeRequests[event.request_id] : null
      if (existingRequest?.background) {
        this._completeActiveRequest(event, 'cancelled')
        return
      }
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, 'cancelled')
        return
      }
      this._completeActiveRequest(event, 'cancelled')
      finalizeToolActivitiesForRequest(
        this,
        event.request_id || this.activeRequestId || null,
        event.timestamp,
        'cancelled',
        event.payload?.stop_reason || event.payload?.reason || undefined,
      )
      this.runStatus = 'cancelled'
      const requestId = event.request_id || this.activeRequestId || null
      if (
        this.currentPlan?.status === 'active'
        && (!this.currentPlan.request_id || this.currentPlan.request_id === requestId)
      ) {
        this.currentPlan = {
          ...this.currentPlan,
          status: 'cancelled',
          current_step_id: null,
          updatedAt: event.timestamp,
        }
      }
      this.pendingInterrupt = null
      this._syncAgentSessionFromRunEvent(event)
      Object.values(this.modelStreams).forEach((stream) => {
        if (requestId && stream.requestId && stream.requestId !== requestId) return
        stream.active = false
        stream.reasoningActive = false
        stream.completedAt = event.timestamp
        stream.reasoningCompletedAt = stream.reasoningCompletedAt || event.timestamp
      })
      const turn = ensureConversationTurn(this, requestId, event.timestamp)
      turn.status = 'cancelled'
      turn.completedAt = event.timestamp
      turn.errorMessage = null
      if (!this.activeRequestId || this.activeRequestId === requestId) {
        this.activeRequestId = null
      }
    },

    _handleRunFailed(event: RuntimeFrontendEvent) {
      const existingRequest = event.request_id ? this.activeRequests[event.request_id] : null
      if (existingRequest?.background) {
        this._completeActiveRequest(event, 'failed')
        return
      }
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, 'failed')
        return
      }
      this._completeActiveRequest(event, 'failed')
      finalizeToolActivitiesForRequest(
        this,
        event.request_id || this.activeRequestId || null,
        event.timestamp,
        'failed',
        event.payload?.message || event.payload?.error || event.message || undefined,
      )
      this.runStatus = 'failed'
      const requestId = event.request_id || this.activeRequestId || null
      this.pendingInterrupt = null
      this._syncAgentSessionFromRunEvent(event)

      // 展示错误
      const errorMsg =
        event.payload?.message ||
        event.payload?.error ||
        event.payload?.error_message ||
        event.message ||
        'Run failed'

      const errorItem: TranscriptItem = {
        id: event.event_id,
        role: 'system',
        content: errorMsg,
        timestamp: event.timestamp,
        status: 'failed',
        parts: [
          errorPart(`${event.event_id}:error`, errorMsg, event.payload || {}, event.timestamp),
        ],
        metadata: {
          where: event.payload?.where,
          why: event.payload?.why,
          error_type: event.payload?.error_type,
        },
      }
      this.transcript.push(errorItem)
      const turn = ensureConversationTurn(this, requestId, event.timestamp)
      turn.status = 'failed'
      turn.completedAt = event.timestamp
      turn.errorMessage = errorMsg
      if (!this.activeRequestId || this.activeRequestId === requestId) {
        this.activeRequestId = null
      }
    },

    _syncAgentSessionFromRunEvent(event: RuntimeFrontendEvent) {
      if (event.mode !== 'agent_package') return
      this._promoteAgentPackageScopeFromEvent(event)
      if (event.payload?.agent_session?.session_id) {
        this._upsertAgentSession(event.payload.agent_session)
      }
    },

    _handleInterruptRequested(event: RuntimeFrontendEvent) {
      const isChildQuestion = (
        event.payload?.runtime_role === 'temporary'
        && String(event.payload?.type || '').trim() === 'ask_user'
      )
      if (isChildQuestion) {
        this.pendingInterrupt = event
        if (!this.activeRequestId) this.runStatus = 'interrupted'
        return
      }
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, 'interrupted')
        return
      }
      this._completeActiveRequest(event, 'interrupted')
      this.runStatus = 'interrupted'
      this.pendingInterrupt = event
      this._promoteAgentPackageScopeFromEvent(event)
      const requestId = event.request_id || this.activeRequestId || null
      const turn = ensureConversationTurn(this, requestId, event.timestamp)
      turn.status = 'interrupted'
      turn.completedAt = event.timestamp
      const message = shouldRenderInterruptMessage(event) ? interruptMessage(event) : ''
      const reconciled = message
        ? reconcileAssistantDialogueInterrupt(this, event, message)
        : false
      if (message && !reconciled) {
        const item: TranscriptItem = {
          id: event.event_id,
          role: 'assistant',
          content: message,
          timestamp: event.timestamp,
          status: 'completed',
          parts: [
            textPart(`${event.event_id}:text`, message, {
              format: 'markdown',
              status: 'completed',
              timestamp: event.timestamp,
            }),
          ],
          metadata: {
            interrupt: true,
            interrupt_type: interruptType(event),
            mode: event.mode || null,
          },
        }
        this.transcript.push(item)
        turn.assistantMessages.push(item)
      }
      if (isUserInputInterrupt(event)) {
        if (!this.activeRequestId || this.activeRequestId === requestId) {
          this.activeRequestId = null
        }
      }
    },

    /**
     * Stage handlers
     */
    _handleStageStarted(event: RuntimeFrontendEvent) {
      applyStageStarted(this, event)
    },

    _handleStageCompleted(event: RuntimeFrontendEvent) {
      applyStageCompleted(this, event)
    },

    _handleStageFailed(event: RuntimeFrontendEvent) {
      applyStageFailed(this, event)
    },

    /**
     * Node handlers
     */
    _handleNodeStarted(event: RuntimeFrontendEvent) {
      applyNodeStarted(this, event)
    },

    _handleNodeProgress(event: RuntimeFrontendEvent) {
      applyNodeProgress(this, event)
    },

    _handleNodeCompleted(event: RuntimeFrontendEvent) {
      applyNodeCompleted(this, event)
    },

    _handleNodeFailed(event: RuntimeFrontendEvent) {
      applyNodeFailed(this, event)
    },

    /**
     * Plan handler
     */
    _handlePlanUpdated(event: RuntimeFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      const payload = event.payload
      if (!payload || payload.version !== 'plan_state.v0') return

      const nextPlan = {
        version: payload.version,
        runtime_instance_id: payload.runtime_instance_id || event.run_id || null,
        request_id: payload.request_id || event.request_id || null,
        goal: payload.goal || '',
        status: payload.status || 'active',
        current_step_id: payload.current_step_id || null,
        steps: payload.steps || [],
        source_node_id: payload.source_node_id || null,
        updatedAt: event.timestamp,
      }
      restorePlanCapsule(nextPlan)
      this.currentPlan = nextPlan
    },

    dismissCurrentPlan(requestId: string | null = null) {
      if (!this.currentPlan) return
      if (requestId && this.currentPlan.request_id && this.currentPlan.request_id !== requestId) return
      dismissPlanCapsule(this.currentPlan)
      this.currentPlan = null
      this._saveActiveConversationScope()
    },

    /**
     * Model stream handlers
     */
    _handleModelCallStarted(event: RuntimeFrontendEvent) {
      applyModelCallStarted(this, event)
    },

    _handleModelReasoningDelta(event: RuntimeFrontendEvent) {
      applyModelReasoningDelta(this, event)
    },

    _handleModelReasoningCompleted(event: RuntimeFrontendEvent) {
      applyModelReasoningCompleted(this, event)
    },

    _handleModelStreamDelta(event: RuntimeFrontendEvent) {
      applyModelStreamDelta(this, event)
    },

    _handleModelMessageCompleted(event: RuntimeFrontendEvent) {
      applyModelMessageCompleted(this, event)
    },

    /**
     * Tool handlers
     */
    _handleToolCallProposed(event: RuntimeFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'proposed')
    },

    _handleToolApprovalRequested(event: RuntimeFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      applyToolApprovalRequested(this, event)
      if (!String(event.payload?.source_task_id || '').trim()) {
        this._promoteAgentPackageScopeFromEvent(event)
      }
    },

    _handleToolApprovalResolved(event: RuntimeFrontendEvent) {
      applyToolApprovalResolved(this, event)
    },

    _handleToolCallStarted(event: RuntimeFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'started')
    },

    _handleToolCallCompleted(event: RuntimeFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'completed')
    },

    _handleToolCallFailed(event: RuntimeFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'failed')
    },

    _handleToolObservation(event: RuntimeFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'observed')
    },

    /**
     * Context/Memory/Knowledge/Scheduler handlers
     */
    _handleContextEvent(event: RuntimeFrontendEvent) {
      applyContextActivityEvent(this, event)
    },

    _handleMemoryEvent(event: RuntimeFrontendEvent) {
      applyMemoryActivityEvent(this, event)
    },

    _handleKnowledgeEvent(event: RuntimeFrontendEvent) {
      applyKnowledgeActivityEvent(this, event)
    },

    _handleWorkspaceEvent(event: RuntimeFrontendEvent) {
      applyWorkspaceEvent(this, event)
    },

    _handleExtensionsEvent(event: RuntimeFrontendEvent) {
      applyExtensionsEvent(this, event)
    },

    _handleSchedulerEvent(event: RuntimeFrontendEvent) {
      applySchedulerActivityEvent(this, event)
    },

    /**
     * Error handler
     */
    _handleError(event: RuntimeFrontendEvent) {
      if (isSchedulerRequest(event.request_id)) {
        this._completeActiveRequest(event, 'failed')
        return
      }
      // 如果 error 的 request_id 命中 active request，视为 failed
      if (event.request_id === this.activeRequestId) {
        this._handleRunFailed(event)
      } else if (event.request_id) {
        const turn = this.conversationTurns.find((item) => item.requestId === event.request_id)
        if (turn) {
          const errorMessage = event.message || event.payload?.message || translate(currentLocale(), 'common.requestFailed')
          const errorItem: TranscriptItem = {
            id: event.event_id,
            role: 'system',
            content: errorMessage,
            timestamp: event.timestamp,
            status: 'failed',
            parts: [
              errorPart(`${event.event_id}:error`, errorMessage, event.payload || {}, event.timestamp),
            ],
            metadata: {
              where: event.payload?.where,
              why: event.payload?.why,
              error_type: event.payload?.error_type,
            },
          }
          this.transcript.push(errorItem)
          turn.status = 'failed'
          turn.completedAt = event.timestamp
          turn.errorMessage = errorMessage
        } else {
          console.error('Runtime error:', event.message, event.payload)
        }
      } else {
        // 否则只记录错误
        console.error('Runtime error:', event.message, event.payload)
      }
    },

    _registerActiveRequest(event: RuntimeFrontendEvent, status: RunStatus) {
      const requestId = event.request_id
      if (!requestId) return
      const existing = this.activeRequests[requestId]
      const conversationScope =
        existing?.conversationScope ||
        scopeFromEventPayload(event) ||
        this.activeConversationScope
      const source = activeRequestSource(event.payload?.request_source, existing?.source, requestId)
      this.activeRequests[requestId] = {
        requestId,
        status,
        mode: event.mode || existing?.mode || null,
        runId: event.run_id || event.payload?.run_id || existing?.runId || null,
        conversationScope,
        background: source === 'scheduler',
        source,
        startedAt: existing?.startedAt || event.timestamp,
        completedAt: status === 'running' ? existing?.completedAt || null : event.timestamp,
        payload: {
          ...(existing?.payload || {}),
          ...(event.payload || {}),
        },
      }
    },

    _handleRuntimeRequestQueued(event: RuntimeFrontendEvent) {
      this._registerActiveRequest(event, 'running')
      this._setRequestDispatchState(event.request_id, 'queued', event.payload)
    },

    _handleRuntimeRequestSteering(event: RuntimeFrontendEvent) {
      this._registerActiveRequest(event, 'completed')
      this._setRequestDispatchState(event.request_id, 'promoted', event.payload)
    },

    _handleRuntimeRequestDispatched(event: RuntimeFrontendEvent) {
      this._registerActiveRequest(event, 'running')
      this._setRequestDispatchState(event.request_id, 'running', event.payload)
      const request = event.request_id ? this.activeRequests[event.request_id] : null
      if (request?.source !== 'user') return
      this.activeRequestId = event.request_id || this.activeRequestId
      this.runStatus = 'running'
      this.pendingInterrupt = null
    },

    _setRequestDispatchState(
      requestId: string | null | undefined,
      dispatchState: 'queued' | 'promoted' | 'running' | 'stopping' | 'completed' | 'cancelled' | 'failed' | 'stopped',
      payload: Record<string, any> = {},
    ) {
      if (!requestId) return
      const request = this.activeRequests[requestId]
      if (request) {
        request.payload = {
          ...(request.payload || {}),
          ...payload,
          dispatch_state: dispatchState,
        }
      }
      const turn = this.conversationTurns.find((item) => item.requestId === requestId)
      if (turn) {
        turn.metadata = {
          ...(turn.metadata || {}),
          ...payload,
          dispatch_state: dispatchState,
        }
        if (turn.userMessage) {
          turn.userMessage.metadata = {
            ...(turn.userMessage.metadata || {}),
            ...payload,
            request_id: requestId,
            dispatch_state: dispatchState,
          }
        }
      }
      this.transcript
        .filter((item) => item.metadata?.request_id === requestId)
        .forEach((item) => {
          item.metadata = {
            ...(item.metadata || {}),
            ...payload,
            dispatch_state: dispatchState,
          }
        })
    },

    _resolveRequestScopeForEvent(event: RuntimeFrontendEvent): string | null {
      const requestId = event.request_id || null
      const payloadScope = scopeFromEventPayload(event)
      if (!requestId) return payloadScope
      const request = this.activeRequests[requestId]
      const currentScope = request?.conversationScope || null
      if (request && isMoreSpecificConversationScope(currentScope, payloadScope)) {
        this._renameConversationScope(currentScope as string, payloadScope as string)
        request.conversationScope = payloadScope
        return payloadScope
      }
      return currentScope || payloadScope
    },

    _completeActiveRequest(event: RuntimeFrontendEvent, status: RunStatus) {
      this._registerActiveRequest(event, status)
      const dispatchState = status === 'cancelled'
        ? 'cancelled'
        : status === 'failed'
          ? 'failed'
          : status === 'stopped'
            ? 'stopped'
            : 'completed'
      this._setRequestDispatchState(event.request_id, dispatchState, event.payload)
    },

    _restoreAgentPackageSession(session: any, packageId: string | null = null) {
      if (!session?.session_id) return
      const snapshot = agentPackageSessionSnapshotView(session, packageId)
      this._upsertAgentSession(session)
      const scope = snapshot.scope
      const activate = this._shouldActivateConversationScope(scope)
      const restore = () => this._applyAgentPackageSessionSnapshot(snapshot, session, scope, activate)
      if (activate) {
        this._switchConversationScope(scope)
        restore()
        this._saveActiveConversationScope()
      } else {
        this._projectConversationScope(scope, restore)
      }
    },

    _applyAgentPackageSessionSnapshot(
      snapshot: ReturnType<typeof agentPackageSessionSnapshotView>,
      session: any,
      scope: string,
      activate: boolean,
    ) {
      this.activeMainSessionId = null
      this.activeAgentSessionId = String(session.session_id)
      this.activeWorkspaceId = String(session.workspace_id || '') || null
      if (activate) this.currentMode = 'agent_package'
      this.currentPlan = snapshot.currentPlan
      this.runtimeActivity = { status: 'idle' }
      this.contextActivity = { status: 'idle' }
      this.contextWindow = snapshot.contextWindow
      this.memoryActivity = { status: 'idle' }
      this.modelStreams = {}
      this.tools = snapshot.tools
      this.pendingInterrupt = snapshot.pendingInterrupt

      this.transcript = snapshot.transcript
      this.conversationTurns = snapshot.conversationTurns
      this._reconcileRestoredTurnStatuses(
        new Set(
          Object.values(this.activeRequests)
            .filter(request => request.status === 'running')
            .map(request => request.requestId),
        ),
      )
      this._restoreProcessEvents(snapshot.processEvents)
      this._restoreActiveTurnFromSnapshot(snapshot.activeTurn, {
        mode: 'agent_package',
        conversationScope: scope,
        payload: {
          package_id: snapshot.sessionPackageId,
          session_id: session.session_id,
          agent_session: session,
        },
      })
    },

    _restoreProcessEvents(events: RuntimeFrontendEvent[]) {
      this.timeline = []
      this.nodes = {}
      this.stages = {}
      events.forEach((event) => {
        this._recordTimelineEvent(event)
        if (isRestorableProcessStateEvent(event.event_type)) {
          this._dispatchEvent(event)
        }
      })
    },

    showEmptyAgentPackageSession(
      packageId: string | null = null,
      workspaceId: string | null = null,
    ) {
      this._resetConversationScope(agentPackageConversationScope(packageId, null))
      this.activeMainSessionId = null
      this.activeAgentSessionId = null
      this.activeWorkspaceId = String(workspaceId || '').trim() || null
      this.currentMode = 'agent_package'
      this.workspaceFile = null
      this.workspaceEntries = []
    },

    clearConversationHistory(
      packageId: string | null = null,
      workspaceId: string | null = null,
    ) {
      this.sessions = []
      this.agentSessions = []
      this.activeRequests = {}
      this.conversationScopes = {}
      this.activeConversationScope = null
      this.showEmptyAgentPackageSession(packageId, workspaceId)
    },

    expectAgentPackageSession(
      packageId: string,
      sessionId: string,
    ) {
      this.expectAgentPackageSelection(packageId, 'run')
      this._switchConversationScope(agentPackageConversationScope(packageId, sessionId))
      this.currentMode = 'agent_package'
      this.activeMainSessionId = null
      this.activeAgentSessionId = sessionId
    },

    acceptAgentPackageSession(packageId: string, sessionId: string) {
      const pendingScope = agentPackageConversationScope(packageId, null)
      const acceptedScope = agentPackageConversationScope(packageId, sessionId)
      if (this.activeConversationScope === pendingScope) {
        this._renameActiveConversationScope(acceptedScope)
      } else if (this.activeConversationScope !== acceptedScope) {
        this._switchConversationScope(acceptedScope)
      }
      this.currentMode = 'agent_package'
      this.activeMainSessionId = null
      this.activeAgentSessionId = sessionId
      this._saveActiveConversationScope()
    },

    updateContextModelLimits(
      profileId: string,
      contextWindowTokens: number | null | undefined,
      compressionThresholdTokens: number | null | undefined,
    ) {
      const windowTokens = optionalPositiveInteger(contextWindowTokens)
      const thresholdTokens = optionalPositiveInteger(compressionThresholdTokens)
      if (!windowTokens || !thresholdTokens) return
      const current = this.contextWindow
      this.contextWindow = {
        tokenCount: current?.tokenCount ?? null,
        contextWindowTokens: windowTokens,
        compressionThresholdTokens: thresholdTokens,
        tokenCountMethod: current?.tokenCountMethod ?? null,
        source: 'model_pool.selection',
        modelRole: 'main',
        nodeId: current?.nodeId ?? null,
        compressionStatus: current?.compressionStatus ?? null,
        updatedAt: new Date().toISOString(),
        payload: {
          ...(current?.payload || {}),
          model_profile_id: profileId,
          context_window_tokens: windowTokens,
          compression_threshold_tokens: thresholdTokens,
          source: 'model_pool.selection',
        },
      }
    },

    expectAgentPackageSelection(packageId: string, purpose: 'run') {
      this.agentPackageSelectionIntent = {
        packageId: String(packageId || '').trim() || null,
        purpose,
      }
    },

    _clearAgentPackageSelectionIntent() {
      this.agentPackageSelectionIntent = { packageId: null, purpose: null }
    },

    ownsAgentPackageSelection(event: RuntimeFrontendEvent): boolean {
      const packageId = String(event.payload?.package_id || event.payload?.package?.package_id || '').trim()
      const purpose = 'run'
      return Boolean(packageId)
        && this.agentPackageSelectionIntent.packageId === packageId
        && this.agentPackageSelectionIntent.purpose === purpose
    },

    markSchedulerNoticeRead(noticeId: string) {
      markSchedulerRunNoticeRead(this, noticeId)
    },

    dismissSchedulerNoticeFromConversation(noticeId: string) {
      dismissSchedulerRunNoticeFromConversation(this, noticeId)
    },

    _upsertAgentSession(session: any) {
      if (!session?.session_id) return
      if (!isStandaloneAgentSession(session)) return
      const index = this.agentSessions.findIndex((item) => item.session_id === session.session_id)
      if (index >= 0) {
        this.agentSessions[index] = { ...this.agentSessions[index], ...session }
      } else {
        this.agentSessions.unshift(session)
      }
    },

    _switchConversationScope(scope: string) {
      if (!scope || this.activeConversationScope === scope) return
      this._saveActiveConversationScope()
      this.activeConversationScope = scope
      const saved = this.conversationScopes[scope]
      if (saved) {
        this._restoreConversationScope(saved)
      } else {
        this._clearConversationViewState()
      }
    },

    _shouldActivateConversationScope(scope: string): boolean {
      return !this.activeConversationScope
        || this.activeConversationScope === scope
        || isMoreSpecificConversationScope(this.activeConversationScope, scope)
    },

    _projectConversationScope(scope: string, project: () => void) {
      const previousScope = this.activeConversationScope
      if (previousScope) this._saveActiveConversationScope()
      this.activeConversationScope = scope
      const saved = this.conversationScopes[scope]
      if (saved) {
        this._restoreConversationScope(saved)
      } else {
        this._clearConversationViewState()
      }
      try {
        project()
        this._saveActiveConversationScope()
      } finally {
        if (previousScope) {
          this.activeConversationScope = previousScope
          const previous = this.conversationScopes[previousScope]
          if (previous) {
            this._restoreConversationScope(previous)
          } else {
            this._clearConversationViewState()
          }
        } else {
          this.activeConversationScope = null
          this._clearConversationViewState()
        }
      }
    },

    _saveActiveConversationScope() {
      const scope = this.activeConversationScope
      if (!scope) return
      this.conversationScopes[scope] = buildConversationScopeState(this)
    },

    _restoreConversationScope(saved: ConversationScopeState) {
      const restored = normalizeConversationScopeState(saved)
      this.activeRequestId = restored.activeRequestId ?? null
      this.runStatus = restored.runStatus ?? 'idle'
      this.pendingInterrupt = restored.pendingInterrupt ?? null
      this.currentRunId = restored.currentRunId ?? null
      this.nodes = restored.nodes || {}
      this.stages = restored.stages || {}
      this.transcript = restored.transcript
      this.conversationTurns = restored.conversationTurns
      this.timeline = restored.timeline
      this.tools = restored.tools
      this.currentPlan = restored.currentPlan
      this.runtimeActivity = restored.runtimeActivity
      this.contextActivity = restored.contextActivity
      this.contextWindow = restored.contextWindow
      this.memoryActivity = restored.memoryActivity
      this.modelStreams = restored.modelStreams
      this.activeMainSessionId = restored.activeMainSessionId
      this.activeAgentSessionId = restored.activeAgentSessionId
      this.activeWorkspaceId = restored.activeWorkspaceId
    },

    _dispatchEventToConversationScope(scope: string, event: RuntimeFrontendEvent) {
      this._projectConversationScope(scope, () => {
        this._dispatchEvent(event)
        this._recordTimelineEvent(event)
      })
    },

    _renameConversationScope(previousScope: string, nextScope: string) {
      if (!previousScope || !nextScope || previousScope === nextScope) return
      const saved = this.conversationScopes[previousScope]
      if (saved && !this.conversationScopes[nextScope]) {
        this.conversationScopes[nextScope] = saved
      }
      delete this.conversationScopes[previousScope]
      if (this.activeConversationScope === previousScope) {
        this.activeConversationScope = nextScope
      }
      Object.values(this.activeRequests).forEach((request) => {
        if (request.conversationScope === previousScope) {
          request.conversationScope = nextScope
        }
      })
    },

    _renameActiveConversationScope(nextScope: string) {
      const previousScope = this.activeConversationScope
      if (!previousScope || previousScope === nextScope) return
      this._renameConversationScope(previousScope, nextScope)
    },

    _resetConversationScope(scope: string) {
      if (!scope) return
      if (this.activeConversationScope && this.activeConversationScope !== scope) {
        this._saveActiveConversationScope()
      }
      delete this.conversationScopes[scope]
      this.activeConversationScope = scope
      this._clearConversationViewState()
    },

    _deleteConversationScopesForSessions(sessionIds: string[]) {
      const suffixes = sessionIds.filter(Boolean).map((sessionId) => `:${sessionId}`)
      if (suffixes.length === 0) return
      Object.keys(this.conversationScopes)
        .filter((scope) => suffixes.some((suffix) => scope.endsWith(suffix)))
        .forEach((scope) => {
          delete this.conversationScopes[scope]
        })
    },

    _promoteAgentPackageScopeFromEvent(event: RuntimeFrontendEvent) {
      const scopeInfo = agentPackageScopeInfoFromEvent(event)
      if (!scopeInfo) return
      this.activeMainSessionId = null
      this.activeAgentSessionId = scopeInfo.sessionId
      const workspaceId = String(
        event.payload?.agent_session?.workspace_id
        || event.payload?.workspace_id
        || '',
      ).trim()
      if (workspaceId) this.activeWorkspaceId = workspaceId
      this._renameActiveConversationScope(scopeInfo.scope)
      if (event.request_id && this.activeRequests[event.request_id]) {
        this.activeRequests[event.request_id].conversationScope = scopeInfo.scope
      }
    },

    _hasLiveConversationState(): boolean {
      return Boolean(
        this.pendingInterrupt ||
        this.activeRequestId ||
        this.runStatus === 'running' ||
        this.runStatus === 'stopping' ||
        this.runStatus === 'interrupted',
      )
    },

    _hasVisibleConversationContent(): boolean {
      return this.transcript.length > 0 || this.conversationTurns.some((turn) => (
        Boolean(turn.userMessage) ||
        turn.assistantMessages.length > 0 ||
        turn.tools.length > 0
      ))
    },

    _restoreActiveTurnFromSnapshot(
      turn: ConversationTurn | null,
      options: {
        mode: RuntimeMode | null
        conversationScope: string | null
        payload?: Record<string, any>
      },
    ) {
      if (!turn?.requestId) return
      if (!['running', 'stopping', 'interrupted'].includes(turn.status)) return
      const existing = this.activeRequests[turn.requestId]
      if (['running', 'stopping'].includes(turn.status) && existing?.status !== 'running') return
      this.activeRequestId = turn.requestId
      this.runStatus = turn.status
      this.currentRunId = existing?.runId || null
      this.pendingInterrupt = turn.status === 'interrupted' ? this.pendingInterrupt : null
      this.activeRequests[turn.requestId] = {
        requestId: turn.requestId,
        status: turn.status,
        mode: options.mode || existing?.mode || null,
        runId: existing?.runId || null,
        conversationScope: options.conversationScope || existing?.conversationScope || null,
        background: existing?.background || false,
        source: existing?.source || 'user',
        startedAt: existing?.startedAt || turn.startedAt,
        completedAt: turn.completedAt,
        payload: {
          ...(existing?.payload || {}),
          ...(turn.metadata || {}),
          ...(options.payload || {}),
        },
      }
    },

    _reconcileRestoredTurnStatuses(activeRequestIds: ReadonlySet<string>) {
      this.conversationTurns.forEach((turn) => {
        if (turn.status !== 'running' && turn.status !== 'stopping') return
        if (turn.requestId && activeRequestIds.has(turn.requestId)) return
        turn.status = 'stopped'
        turn.completedAt = turn.completedAt || turn.startedAt
      })
    },

    _clearConversationViewState() {
      this.activeRequestId = null
      this.runStatus = 'idle'
      this.pendingInterrupt = null
      this.currentRunId = null
      this.nodes = {}
      this.stages = {}
      this.modelStreams = {}
      this.tools = []
      this.currentPlan = null
      this.runtimeActivity = { status: 'idle' }
      this.contextActivity = { status: 'idle' }
      this.contextWindow = null
      this.memoryActivity = { status: 'idle' }
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.activeMainSessionId = null
      this.activeAgentSessionId = null
      this.activeWorkspaceId = null
    },

    _recordDebugEvent(event: RuntimeFrontendEvent) {
      recordDebugEvent(this, event)
    },

    _recordTimelineEvent(event: RuntimeFrontendEvent) {
      recordTimelineEvent(this, event)
    },

    /**
     * 添加用户消息到 transcript
     */
    addUserMessage(
      content: string,
      requestId: string | null = null,
      metadata: Record<string, any> = {},
      attachments: TranscriptItem['attachments'] = [],
    ) {
      const conversationScope = requestId
        ? scopeFromMessageMetadata(metadata, this.currentMode)
        : null
      if (conversationScope) {
        this._switchConversationScope(conversationScope)
      }
      const timestamp = new Date().toISOString()
      const messageId = `user-${Date.now()}`
      const queued = Boolean(this.activeRequestId && ['running', 'stopping'].includes(this.runStatus))
      const dispatchState = queued ? 'queued' : 'running'
      const messageMetadata = {
        ...metadata,
        request_id: requestId,
        dispatch_state: dispatchState,
      }
      const item: TranscriptItem = {
        id: messageId,
        role: 'user',
        content,
        timestamp,
        status: 'completed',
        parts: [
          textPart(`${messageId}:text`, content, {
            format: 'plain',
            status: 'completed',
            timestamp,
          }),
          ...attachments.map((attachment, index) => attachmentPart(`${messageId}:attachment:${index}`, attachment, timestamp)),
        ],
        attachments,
        metadata: messageMetadata,
      }
      this.transcript.push(item)
      const turn = ensureConversationTurn(this, requestId, timestamp)
      turn.userMessage = item
      turn.status = 'running'
      turn.metadata = {
        ...turn.metadata,
        ...messageMetadata,
      }
      if (requestId) {
        if (!queued) {
          this.activeRequestId = requestId
          this.runStatus = 'running'
          this.pendingInterrupt = null
        }
        this.activeRequests[requestId] = {
          requestId,
          status: 'running',
          mode: (metadata.mode as RuntimeMode | undefined) || this.currentMode || null,
          runId: null,
          conversationScope,
          background: false,
          source: 'user',
          startedAt: timestamp,
          completedAt: null,
          payload: {
            ...messageMetadata,
            queue_position: queued ? this.queuedRequestCount + 1 : 0,
          },
        }
      }
    },

    markActiveRequestStopping(requestId?: string | null) {
      const targetRequestId = requestId ?? this.activeRequestId
      if (!targetRequestId) return
      const timestamp = new Date().toISOString()
      const request = this.activeRequests[targetRequestId]
      if (request) {
        request.status = 'running'
        request.completedAt = null
        request.payload = {
          ...(request.payload || {}),
          stop_requested_at: timestamp,
          dispatch_state: 'stopping',
        }
      }
      Object.values(this.modelStreams).forEach((stream) => {
        if (stream.requestId && stream.requestId !== targetRequestId) return
        stream.active = false
        stream.reasoningActive = false
        stream.completedAt = stream.completedAt || timestamp
        stream.reasoningCompletedAt = stream.reasoningCompletedAt || timestamp
      })
      const turn = ensureConversationTurn(this, targetRequestId, timestamp)
      turn.metadata = {
        ...(turn.metadata || {}),
        stop_requested_at: timestamp,
        dispatch_state: 'stopping',
      }
      turn.status = 'stopping'
      turn.completedAt = null
      turn.errorMessage = null
      turn.assistantMessages.forEach((message) => {
        message.parts = message.parts.map((part) => (
          part.status === 'streaming'
            ? { ...part, status: 'completed', updatedAt: timestamp } as ChatMessagePart
            : part
        ))
      })
      this.transcript.forEach((message) => {
        if (message.metadata?.request_id !== targetRequestId) return
        message.parts = message.parts.map((part) => (
          part.status === 'streaming'
            ? { ...part, status: 'completed', updatedAt: timestamp } as ChatMessagePart
            : part
        ))
      })
      this.activeRequestId = targetRequestId
      this.runStatus = 'stopping'
      this.pendingInterrupt = null
      this._saveActiveConversationScope()
    },

    markRequestSteering(requestId: string) {
      const targetRequestId = String(requestId || '').trim()
      if (!targetRequestId) return
      const request = this.activeRequests[targetRequestId]
      if (request) {
        request.payload = {
          ...(request.payload || {}),
          dispatch_state: 'steering',
        }
      }
      const turn = this.conversationTurns.find((item) => item.requestId === targetRequestId)
      if (turn) {
        turn.metadata = {
          ...(turn.metadata || {}),
          dispatch_state: 'steering',
        }
        if (turn.userMessage) {
          turn.userMessage.metadata = {
            ...(turn.userMessage.metadata || {}),
            dispatch_state: 'steering',
          }
        }
      }
    },

    restoreRequestQueued(requestId: string) {
      const targetRequestId = String(requestId || '').trim()
      if (!targetRequestId) return
      const request = this.activeRequests[targetRequestId]
      if (request && request.status === 'running') {
        request.payload = {
          ...(request.payload || {}),
          dispatch_state: 'queued',
        }
      }
      const turn = this.conversationTurns.find((item) => item.requestId === targetRequestId)
      if (turn) {
        turn.metadata = {
          ...(turn.metadata || {}),
          dispatch_state: 'queued',
        }
        if (turn.userMessage) {
          turn.userMessage.metadata = {
            ...(turn.userMessage.metadata || {}),
            dispatch_state: 'queued',
          }
        }
      }
    },

  },
})

function currentLocale() {
  if (typeof window === 'undefined') return detectBrowserLocale()
  const stored = window.localStorage.getItem(localeStorageKey)
  return stored ? normalizeLocale(stored) : detectBrowserLocale()
}

function optionalPositiveInteger(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.trunc(value)
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed) && parsed > 0) {
      return Math.trunc(parsed)
    }
  }
  return null
}

function activeRequestViewFromPayload(value: unknown): ActiveRequestView | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, any>
  const requestId = String(payload.requestId || payload.request_id || '').trim()
  if (!requestId) return null
  const requestPayload = payload.payload && typeof payload.payload === 'object'
    ? { ...payload.payload }
    : {}
  const status = String(payload.status || 'running') as RunStatus
  const source = activeRequestSource(payload.source, undefined, requestId)
  return {
    requestId,
    status,
    mode: normalizeRuntimeMode(payload.mode),
    runId: payload.runId || payload.run_id || null,
    conversationScope: payload.conversationScope || payload.conversation_scope || null,
    background: source === 'scheduler',
    source,
    startedAt: String(payload.startedAt || payload.started_at || new Date().toISOString()),
    completedAt: payload.completedAt || payload.completed_at || null,
    payload: requestPayload,
  }
}

function activeRequestSource(
  value: unknown,
  existing: ActiveRequestView['source'] | undefined,
  requestId: string,
): ActiveRequestView['source'] {
  if (value === 'internal' || value === 'scheduler' || value === 'user') return value
  if (existing) return existing
  return requestId.startsWith('scheduler-') ? 'scheduler' : 'user'
}

function normalizeRuntimeMode(value: unknown): RuntimeMode | null {
  if (value === 'agent_package' || value === 'agent_group') {
    return value
  }
  return null
}
