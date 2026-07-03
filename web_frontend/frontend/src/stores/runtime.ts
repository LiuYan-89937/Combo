/**
 * Runtime Store - 核心状态管理
 *
 * 基于协议文档的 Request-Scoped Reducer 规则实现
 * 参考 CLI 的 runtimeStore.ts
 */
import { defineStore } from 'pinia'
import type {
  FactoryFrontendEvent,
  FactoryMode,
  RuntimeViewState,
  ActiveRequestView,
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
  applySchedulerActivityEvent,
  recordDebugEvent,
  recordTimelineEvent,
} from './runtime/activityMutations'
import {
  interruptMessage,
  interruptType,
  isBackgroundEvent,
  isRequestScopedEvent,
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
  agentPackageConversationScope,
  agentPackageScopeInfoFromEvent,
  conversationScopeForMode,
  isMoreSpecificConversationScope,
  scopeFromEventPayload,
  scopeFromMessageMetadata,
} from './runtime/scopes'
import {
  agentPackageSessionSnapshotView,
  factorySessionSnapshotView,
} from './runtime/sessionSnapshots'
import {
  applyExtensionsEvent,
  applyWorkspaceEvent,
  markSchedulerRunNoticeRead,
} from './runtime/resourceMutations'
import {
  applyToolApprovalRequested,
  applyToolApprovalResolved,
  applyToolLifecycleEvent,
} from './runtime/toolMutations'
import {
  detectBrowserLocale,
  localeStorageKey,
  normalizeLocale,
  translate,
} from '@/i18n'

// 事件去重集合
const processedEventIds = new Set<string>()

export const useRuntimeStore = defineStore('runtime', {
  state: (): RuntimeViewState => ({
    protocolVersion: 'factory_frontend.v1',
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
    activeFactorySessionId: null,
    activeAgentSessionId: null,
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
    toolPermissions: null,
    sessions: [],
    agentPackages: [],
    selectedAgentPackage: null,
    agentSessions: [],
  }),

  getters: {
    // 输入只因需要专门 UI 处理的中断锁定；运行中不再作为跨会话输入锁。
    isInputLocked: (state): boolean => {
      return state.runStatus === 'interrupted' && !isUserInputInterrupt(state.pendingInterrupt)
    },

    // 制造 Agent 的业务中断需要用户继续输入，而不是审批按钮。
    isAwaitingUserInputInterrupt: (state): boolean => {
      return state.runStatus === 'interrupted' && isUserInputInterrupt(state.pendingInterrupt)
    },

    isPublishConfirmationPending: (state): boolean => {
      return state.runStatus === 'interrupted' && interruptType(state.pendingInterrupt) === 'create_agent_publish_confirmation'
    },

    publishConfirmationPayload: (state): Record<string, any> | null => {
      if (interruptType(state.pendingInterrupt) !== 'create_agent_publish_confirmation') return null
      return state.pendingInterrupt?.payload || null
    },

    // 当前是否有活跃的运行
    hasActiveRun: (state): boolean => {
      return state.activeRequestId !== null && state.runStatus === 'running'
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

    activeVisibleAssistantOutput: (state): Record<string, any> | null => {
      if (!state.activeRequestId) return null
      const turn = state.conversationTurns.find((item) => item.requestId === state.activeRequestId)
      const message = turn?.assistantMessages?.[turn.assistantMessages.length - 1]
      if (!message) return null
      return {
        content: message.content || '',
        reasoning_content: message.reasoning?.content || '',
        stream_id: message.streamId || null,
      }
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
    handleEvent(event: FactoryFrontendEvent) {
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

      // 3. Request-scoped 事件过滤
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
    _dispatchEvent(event: FactoryFrontendEvent) {
      const { event_type: type, payload } = event

      // Runtime lifecycle
      if (type === 'runtime_ready') {
        this._handleRuntimeOptionsChanged(event)
        this._restoreActiveRequestsFromRuntimeSnapshot(event)
        console.info('Runtime ready')
      } else if (type === 'session_started') {
        this.activeFactorySessionId = payload?.session_id || payload?.session?.session_id || event.session_id || null
        this.currentMode = event.mode || null
        this._upsertFactorySession(payload?.session)
        this._clearSessionScopedState()
        this._restoreSessionSnapshot(payload)
      } else if (type === 'session_switched') {
        this.activeFactorySessionId = payload?.session_id || payload?.session?.session_id || event.session_id || null
        this._upsertFactorySession(payload?.session)
        this._clearSessionScopedState()
        this._restoreSessionSnapshot(payload)
      } else if (type === 'sessions_listed') {
        this.sessions = payload?.sessions || []
      } else if (type === 'session_deleted') {
        const deletedSessionId = String(payload?.session_id || '')
        this.sessions = payload?.sessions || this.sessions.filter((session: any) => session.session_id !== deletedSessionId)
        this._deleteConversationScopesForSession(deletedSessionId)
        if (deletedSessionId && this.activeFactorySessionId === deletedSessionId) {
          this.activeFactorySessionId = null
          this.activeConversationScope = null
          this._clearConversationViewState()
        }
      } else if (type === 'mode_changed') {
        this._handleModeChanged(event)
      }

      // Agent packages
      else if (type === 'agent_packages_listed') {
        this.agentPackages = payload?.packages || []
      } else if (type === 'agent_package_selected') {
        this.currentMode = event.mode || this.currentMode
        this.selectedAgentPackage = payload?.package || null
        this.agentSessions = payload?.sessions || this.agentSessions
        if (payload?.purpose === 'evolution' && payload?.package?.package_id) {
          this.activeFactorySessionId = payload?.session_id || payload?.session?.session_id || event.session_id || this.activeFactorySessionId
          this._upsertFactorySession(payload?.session)
          this._clearSessionScopedState()
          this._restoreSessionSnapshot(payload)
        }
      } else if (type === 'agent_package_deleted') {
        const deletedPackageId = payload?.package_id
        this.agentPackages = payload?.packages || this.agentPackages.filter((pkg) => pkg.package_id !== deletedPackageId)
        if (this.selectedAgentPackage?.package_id === deletedPackageId) {
          this.selectedAgentPackage = null
        }
      } else if (type === 'agent_package_sessions_listed') {
        this.agentSessions = payload?.sessions || []
      } else if (type === 'agent_package_session_loaded') {
        this._restoreAgentPackageSession(payload?.session, payload?.package_id)
      } else if (type === 'agent_package_session_deleted') {
        const deletedSessionId = String(payload?.session_id || '')
        this.agentSessions = payload?.sessions || this.agentSessions.filter((session: any) => session.session_id !== deletedSessionId)
        this._deleteConversationScopesForSession(deletedSessionId)
        if (deletedSessionId && this.activeAgentSessionId === deletedSessionId) {
          this.activeAgentSessionId = null
          this.activeConversationScope = null
          this._clearConversationViewState()
        }
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
      else if (type === 'extension_configs_listed' || type === 'extension_config_updated' || type === 'extension_config_tested') {
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
    _handleModeChanged(event: FactoryFrontendEvent) {
      const nextMode = event.mode || event.payload?.mode || null
      this.currentMode = nextMode
      const nextScope = conversationScopeForMode(nextMode, {
        ...(event.payload || {}),
        session_id: event.session_id || event.payload?.session_id || this.activeFactorySessionId,
      })
      if (nextScope) {
        this._switchConversationScope(nextScope)
      }
    },

    _handleRuntimeOptionsChanged(event: FactoryFrontendEvent) {
      const options = event.payload?.options
      if (!options || typeof options !== 'object') return
      this.runtimeOptions = {
        ...this.runtimeOptions,
        ...options,
        context_window_tokens: optionalPositiveInteger(options.context_window_tokens),
        context_window_tokens_source: String(options.context_window_tokens_source || 'unset'),
      }
    },

    _restoreActiveRequestsFromRuntimeSnapshot(event: FactoryFrontendEvent) {
      const activeRequests = Array.isArray(event.payload?.active_requests)
        ? event.payload.active_requests.map(activeRequestViewFromPayload).filter(Boolean) as ActiveRequestView[]
        : []

      if (activeRequests.length === 0) {
        this._clearStaleForegroundRun()
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
        } satisfies FactoryFrontendEvent
        request.conversationScope = request.conversationScope || scopeFromEventPayload(scopeEvent) || null
        this.activeRequests[request.requestId] = request
      })

      const foregroundRequests = activeRequests.filter((request) => !request.background && request.status === 'running')
      if (foregroundRequests.length === 0) return

      const currentActive = this.activeRequestId ? this.activeRequests[this.activeRequestId] : null
      const preferred =
        (currentActive?.status === 'running' && foregroundRequests.find((item) => item.requestId === currentActive.requestId)) ||
        foregroundRequests.find((request) => request.conversationScope && request.conversationScope === this.activeConversationScope) ||
        foregroundRequests[foregroundRequests.length - 1]

      this.activeRequestId = preferred.requestId
      this.runStatus = 'running'
      this.currentRunId = preferred.runId
      this.pendingInterrupt = null
      if (!this.currentMode && preferred.mode) {
        this.currentMode = preferred.mode
      }
      const turn = ensureConversationTurn(this, preferred.requestId, preferred.startedAt)
      turn.status = 'running'
      turn.completedAt = null
    },

    _clearStaleForegroundRun() {
      if (!this.activeRequestId || this.runStatus !== 'running') return
      const request = this.activeRequests[this.activeRequestId]
      if (request?.background) return
      this.activeRequestId = null
      this.runStatus = 'idle'
    },

    _handleRunStarted(event: FactoryFrontendEvent) {
      if (isSchedulerRequest(event.request_id)) {
        this._registerActiveRequest(event, 'running')
        return
      }
      this._registerActiveRequest(event, 'running')
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

    _handleRunCompleted(event: FactoryFrontendEvent) {
      const completedStatus: RunStatus = event.payload?.status === 'stopped' ? 'stopped' : 'completed'
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, completedStatus)
        return
      }
      this._completeActiveRequest(event, completedStatus)
      this.runStatus = completedStatus
      const requestId = event.request_id || this.activeRequestId || null
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

    _handleRunCancelled(event: FactoryFrontendEvent) {
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, 'cancelled')
        return
      }
      this._completeActiveRequest(event, 'cancelled')
      this.runStatus = 'cancelled'
      const requestId = event.request_id || this.activeRequestId || null
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

    _handleRunFailed(event: FactoryFrontendEvent) {
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, 'failed')
        return
      }
      this._completeActiveRequest(event, 'failed')
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

    _syncAgentSessionFromRunEvent(event: FactoryFrontendEvent) {
      if (!event.payload?.agent_session?.session_id) return
      this.activeAgentSessionId = event.payload.agent_session.session_id
      this._upsertAgentSession(event.payload.agent_session)
      if (event.mode !== 'agent_package' || !event.payload?.package_id) return
      const nextScope = agentPackageConversationScope(
        String(event.payload.package_id),
        String(event.payload.agent_session.session_id),
      )
      this._renameActiveConversationScope(nextScope)
      if (event.request_id && this.activeRequests[event.request_id]) {
        this.activeRequests[event.request_id].conversationScope = nextScope
      }
    },

    _handleInterruptRequested(event: FactoryFrontendEvent) {
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
      if (message) {
        const item: TranscriptItem = {
          id: event.event_id,
          role: 'assistant',
          content: message,
          timestamp: event.timestamp,
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
    _handleStageStarted(event: FactoryFrontendEvent) {
      applyStageStarted(this, event)
    },

    _handleStageCompleted(event: FactoryFrontendEvent) {
      applyStageCompleted(this, event)
    },

    _handleStageFailed(event: FactoryFrontendEvent) {
      applyStageFailed(this, event)
    },

    /**
     * Node handlers
     */
    _handleNodeStarted(event: FactoryFrontendEvent) {
      applyNodeStarted(this, event)
    },

    _handleNodeProgress(event: FactoryFrontendEvent) {
      applyNodeProgress(this, event)
    },

    _handleNodeCompleted(event: FactoryFrontendEvent) {
      applyNodeCompleted(this, event)
    },

    _handleNodeFailed(event: FactoryFrontendEvent) {
      applyNodeFailed(this, event)
    },

    /**
     * Plan handler
     */
    _handlePlanUpdated(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      const payload = event.payload
      if (!payload || payload.version !== 'plan_state.v0') return

      this.currentPlan = {
        version: payload.version,
        goal: payload.goal || '',
        status: payload.status || 'active',
        current_step_id: payload.current_step_id || null,
        steps: payload.steps || [],
        source_node_id: payload.source_node_id || null,
        updatedAt: event.timestamp,
      }
    },

    /**
     * Model stream handlers
     */
    _handleModelCallStarted(event: FactoryFrontendEvent) {
      applyModelCallStarted(this, event)
    },

    _handleModelReasoningDelta(event: FactoryFrontendEvent) {
      applyModelReasoningDelta(this, event)
    },

    _handleModelReasoningCompleted(event: FactoryFrontendEvent) {
      applyModelReasoningCompleted(this, event)
    },

    _handleModelStreamDelta(event: FactoryFrontendEvent) {
      applyModelStreamDelta(this, event)
    },

    _handleModelMessageCompleted(event: FactoryFrontendEvent) {
      applyModelMessageCompleted(this, event)
    },

    /**
     * Tool handlers
     */
    _handleToolCallProposed(event: FactoryFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'proposed')
    },

    _handleToolApprovalRequested(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      applyToolApprovalRequested(this, event)
      this._promoteAgentPackageScopeFromEvent(event)
    },

    _handleToolApprovalResolved(event: FactoryFrontendEvent) {
      applyToolApprovalResolved(this, event)
    },

    _handleToolCallStarted(event: FactoryFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'started')
    },

    _handleToolCallCompleted(event: FactoryFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'completed')
    },

    _handleToolCallFailed(event: FactoryFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'failed')
    },

    _handleToolObservation(event: FactoryFrontendEvent) {
      applyToolLifecycleEvent(this, event, 'observed')
    },

    /**
     * Context/Memory/Knowledge/Scheduler handlers
     */
    _handleContextEvent(event: FactoryFrontendEvent) {
      applyContextActivityEvent(this, event)
    },

    _handleMemoryEvent(event: FactoryFrontendEvent) {
      applyMemoryActivityEvent(this, event)
    },

    _handleKnowledgeEvent(event: FactoryFrontendEvent) {
      applyKnowledgeActivityEvent(this, event)
    },

    _handleWorkspaceEvent(event: FactoryFrontendEvent) {
      applyWorkspaceEvent(this, event)
    },

    _handleExtensionsEvent(event: FactoryFrontendEvent) {
      applyExtensionsEvent(this, event)
    },

    _handleSchedulerEvent(event: FactoryFrontendEvent) {
      applySchedulerActivityEvent(this, event)
    },

    /**
     * Error handler
     */
    _handleError(event: FactoryFrontendEvent) {
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

    _registerActiveRequest(event: FactoryFrontendEvent, status: RunStatus) {
      const requestId = event.request_id
      if (!requestId) return
      const existing = this.activeRequests[requestId]
      const conversationScope =
        existing?.conversationScope ||
        scopeFromEventPayload(event) ||
        this.activeConversationScope
      this.activeRequests[requestId] = {
        requestId,
        status,
        mode: event.mode || existing?.mode || null,
        runId: event.run_id || event.payload?.run_id || existing?.runId || null,
        conversationScope,
        background: isSchedulerRequest(requestId),
        source: isSchedulerRequest(requestId) ? 'scheduler' : 'user',
        startedAt: existing?.startedAt || event.timestamp,
        completedAt: status === 'running' ? existing?.completedAt || null : event.timestamp,
        payload: {
          ...(existing?.payload || {}),
          ...(event.payload || {}),
        },
      }
    },

    _resolveRequestScopeForEvent(event: FactoryFrontendEvent): string | null {
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

    _completeActiveRequest(event: FactoryFrontendEvent, status: RunStatus) {
      this._registerActiveRequest(event, status)
    },

    _restoreSessionSnapshot(payload: Record<string, any> | undefined) {
      const snapshot = factorySessionSnapshotView(payload)
      this.currentMode = snapshot.restoredMode
      if (!snapshot.scope) return

      this._switchConversationScope(snapshot.scope)
      if (this._hasLiveConversationState() && this._hasVisibleConversationContent()) {
        return
      }
      if (!snapshot.hasMessages) return

      this.transcript = snapshot.transcript
      this.conversationTurns = snapshot.conversationTurns
      this._restoreActiveTurnFromSnapshot(snapshot.activeTurn, {
        mode: snapshot.restoredMode,
        conversationScope: snapshot.scope,
        payload: {
          session_id: payload?.session_id || payload?.session?.session_id || null,
          package_id: payload?.package_id || payload?.session?.evolve_agent_package_id || null,
        },
      })
      this._saveActiveConversationScope()
    },

    _restoreAgentPackageSession(session: any, packageId: string | null = null) {
      if (!session?.session_id) return
      const snapshot = agentPackageSessionSnapshotView(session, packageId)
      this.currentMode = 'agent_package'
      this._switchConversationScope(agentPackageConversationScope(snapshot.sessionPackageId, session.session_id))
      this.activeAgentSessionId = String(session.session_id)
      this._upsertAgentSession(session)
      if (this._hasLiveConversationState() && this._hasVisibleConversationContent()) {
        return
      }
      this.currentPlan = null
      this.contextActivity = { status: 'idle' }
      this.contextWindow = null
      this.memoryActivity = { status: 'idle' }
      this.modelStreams = {}
      this.tools = []
      this.pendingInterrupt = null

      this.transcript = snapshot.transcript
      this.conversationTurns = snapshot.conversationTurns
      this._restoreActiveTurnFromSnapshot(snapshot.activeTurn, {
        mode: 'agent_package',
        conversationScope: agentPackageConversationScope(snapshot.sessionPackageId, session.session_id),
        payload: {
          package_id: snapshot.sessionPackageId,
          session_id: session.session_id,
          agent_session: session,
        },
      })
      this._saveActiveConversationScope()
    },

    showEmptyAgentPackageSession(_packageId: string | null = null) {
      this._switchConversationScope(agentPackageConversationScope(_packageId, null))
      if (this._hasLiveConversationState()) {
        this.currentMode = 'agent_package'
        return
      }
      this.activeAgentSessionId = null
      this.currentMode = 'agent_package'
      this.currentPlan = null
      this.contextActivity = { status: 'idle' }
      this.contextWindow = null
      this.memoryActivity = { status: 'idle' }
      this.modelStreams = {}
      this.tools = []
      this.pendingInterrupt = null
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.workspaceFile = null
      this.workspaceEntries = []
    },

    enterFactoryConversation(mode: 'chat' | 'create_agent' | 'evolve_agent', packageId: string | null = null) {
      this.currentMode = mode
      const scope = conversationScopeForMode(mode, {
        package_id: packageId,
        session_id: this.activeFactorySessionId,
      })
      if (scope) {
        this._switchConversationScope(scope)
      }
    },

    markSchedulerNoticeRead(noticeId: string) {
      markSchedulerRunNoticeRead(this, noticeId)
    },

    _upsertAgentSession(session: any) {
      if (!session?.session_id) return
      const index = this.agentSessions.findIndex((item) => item.session_id === session.session_id)
      if (index >= 0) {
        this.agentSessions[index] = { ...this.agentSessions[index], ...session }
      } else {
        this.agentSessions.unshift(session)
      }
    },

    _upsertFactorySession(session: any) {
      if (!session?.session_id) return
      const index = this.sessions.findIndex((item) => item.session_id === session.session_id)
      if (index >= 0) {
        this.sessions[index] = { ...this.sessions[index], ...session }
      } else {
        this.sessions.unshift(session)
      }
    },

    _clearSessionScopedState() {
      this._saveActiveConversationScope()
      this.activeRequestId = null
      this.runStatus = 'idle'
      this.pendingInterrupt = null
      this.currentRunId = null
      this.nodes = {}
      this.stages = {}
      this.modelStreams = {}
      this.tools = []
      this.currentPlan = null
      this.contextActivity = { status: 'idle' }
      this.contextWindow = null
      this.memoryActivity = { status: 'idle' }
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.workspaceEntries = []
      this.workspaceFile = null
      this.extensionTestResult = null
      this.toolPermissions = null
      this.activeConversationScope = null
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
      this.contextActivity = restored.contextActivity
      this.contextWindow = restored.contextWindow
      this.memoryActivity = restored.memoryActivity
      this.modelStreams = restored.modelStreams
      this.activeAgentSessionId = restored.activeAgentSessionId
    },

    _dispatchEventToConversationScope(scope: string, event: FactoryFrontendEvent) {
      const previousScope = this.activeConversationScope
      if (previousScope) {
        this._saveActiveConversationScope()
      }
      this.activeConversationScope = scope
      const saved = this.conversationScopes[scope]
      if (saved) {
        this._restoreConversationScope(saved)
      } else {
        this._clearConversationViewState()
      }
      this._dispatchEvent(event)
      this._recordTimelineEvent(event)
      this._saveActiveConversationScope()
      if (previousScope) {
        this.activeConversationScope = previousScope
        const previousSaved = this.conversationScopes[previousScope]
        if (previousSaved) {
          this._restoreConversationScope(previousSaved)
        }
      } else {
        this.activeConversationScope = null
        this._clearConversationViewState()
      }
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

    _deleteConversationScopesForSession(sessionId: string) {
      if (!sessionId) return
      const suffix = `:${sessionId}`
      Object.keys(this.conversationScopes)
        .filter((scope) => scope.endsWith(suffix))
        .forEach((scope) => {
          delete this.conversationScopes[scope]
        })
    },

    _promoteAgentPackageScopeFromEvent(event: FactoryFrontendEvent) {
      const scopeInfo = agentPackageScopeInfoFromEvent(event)
      if (!scopeInfo) return
      this.activeAgentSessionId = scopeInfo.sessionId
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
        mode: FactoryMode | null
        conversationScope: string | null
        payload?: Record<string, any>
      },
    ) {
      if (!turn?.requestId) return
      if (turn.status !== 'running' && turn.status !== 'interrupted') return
      const existing = this.activeRequests[turn.requestId]
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
      this.contextActivity = { status: 'idle' }
      this.contextWindow = null
      this.memoryActivity = { status: 'idle' }
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.activeAgentSessionId = null
    },

    _recordDebugEvent(event: FactoryFrontendEvent) {
      recordDebugEvent(this, event)
    },

    _recordTimelineEvent(event: FactoryFrontendEvent) {
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
      const timestamp = new Date().toISOString()
      const item: TranscriptItem = {
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        timestamp,
        attachments,
        metadata,
      }
      this.transcript.push(item)
      const turn = ensureConversationTurn(this, requestId, timestamp)
      turn.userMessage = item
      turn.status = 'running'
      turn.metadata = {
        ...turn.metadata,
        ...metadata,
      }
      if (requestId) {
        this.activeRequestId = requestId
        this.runStatus = 'running'
        this.pendingInterrupt = null
        const conversationScope = scopeFromMessageMetadata(metadata, this.currentMode, this.activeFactorySessionId)
        this.activeRequests[requestId] = {
          requestId,
          status: 'running',
          mode: (metadata.mode as FactoryMode | undefined) || this.currentMode || null,
          runId: null,
          conversationScope,
          background: false,
          source: 'user',
          startedAt: timestamp,
          completedAt: null,
          payload: { ...metadata },
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
      }
      turn.status = 'running'
      turn.completedAt = null
      this.activeRequestId = targetRequestId
      this.runStatus = 'running'
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
  const source = payload.source === 'scheduler' ? 'scheduler' : 'user'
  return {
    requestId,
    status,
    mode: normalizeFactoryMode(payload.mode),
    runId: payload.runId || payload.run_id || null,
    conversationScope: payload.conversationScope || payload.conversation_scope || null,
    background: Boolean(payload.background || requestId.startsWith('scheduler-')),
    source,
    startedAt: String(payload.startedAt || payload.started_at || new Date().toISOString()),
    completedAt: payload.completedAt || payload.completed_at || null,
    payload: requestPayload,
  }
}

function normalizeFactoryMode(value: unknown): FactoryMode | null {
  if (value === 'chat' || value === 'create_agent' || value === 'evolve_agent' || value === 'agent_package') {
    return value
  }
  return null
}
