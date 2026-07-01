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
  ConversationScopeState,
  ModelStream,
  ToolActivity,
  TranscriptItem,
  ConversationTurn,
  RunStatus,
} from '@/types/protocol'
import {
  buildConversationScopeState,
  normalizeConversationScopeState,
} from './runtime/conversationState'
import {
  interruptMessage,
  interruptType,
  isBackgroundEvent,
  isRequestScopedEvent,
  isSchedulerRequest,
  isUserInputInterrupt,
} from './runtime/eventUtils'
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
import { toolPayloadArguments, toolPayloadValue } from './runtime/toolPayload'
import {
  contextWindowView,
  extensionItemView,
  knowledgeDocumentView,
  knowledgeSearchResultView,
  knowledgeSourceView,
  schedulerJobView,
  schedulerRunNoticeView,
  schedulerToolOptionView,
  workspaceEntryView,
  workspaceFileView,
  workspaceRootView,
} from './runtime/viewMappers'

// 事件去重集合
const processedEventIds = new Set<string>()

export const useRuntimeStore = defineStore('runtime', {
  state: (): RuntimeViewState => ({
    protocolVersion: 'factory_frontend.v1',
    connectionStatus: 'disconnected',
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
          const scope = conversationScopeForMode('evolve_agent', {
            ...(payload || {}),
            session_id: this.activeFactorySessionId,
          })
          if (scope) {
            this._switchConversationScope(scope)
          }
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
      }

      // Run lifecycle
      else if (type === 'run_started') {
        this._handleRunStarted(event)
      } else if (type === 'run_completed') {
        this._handleRunCompleted(event)
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
      const turn = this._ensureTurnForRequest(event.request_id || null, event.timestamp)
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
      if (isSchedulerRequest(event.request_id) && event.request_id !== this.activeRequestId) {
        this._completeActiveRequest(event, 'completed')
        return
      }
      this._completeActiveRequest(event, 'completed')
      this.runStatus = 'completed'
      const requestId = event.request_id || this.activeRequestId || null
      const turn = this._ensureTurnForRequest(requestId, event.timestamp)
      turn.status = 'completed'
      turn.completedAt = event.timestamp
      if (!this.activeRequestId || this.activeRequestId === requestId) {
        this.activeRequestId = null
      }
      this.pendingInterrupt = null

      // 同步 agent session
      if (event.payload?.agent_session?.session_id) {
        this.activeAgentSessionId = event.payload.agent_session.session_id
        this._upsertAgentSession(event.payload.agent_session)
        if (event.mode === 'agent_package' && event.payload?.package_id) {
          const nextScope = agentPackageConversationScope(
            String(event.payload.package_id),
            String(event.payload.agent_session.session_id),
          )
          this._renameActiveConversationScope(nextScope)
          if (event.request_id && this.activeRequests[event.request_id]) {
            this.activeRequests[event.request_id].conversationScope = nextScope
          }
        }
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
      const turn = this._ensureTurnForRequest(requestId, event.timestamp)
      turn.status = 'failed'
      turn.completedAt = event.timestamp
      turn.errorMessage = errorMsg
      if (!this.activeRequestId || this.activeRequestId === requestId) {
        this.activeRequestId = null
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
      const turn = this._ensureTurnForRequest(requestId, event.timestamp)
      turn.status = 'interrupted'
      turn.completedAt = event.timestamp
      const message = interruptMessage(event)
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
      const stageId = event.stage_id
      if (!stageId) return

      this.stages[stageId] = {
        stageId,
        status: 'running',
        nodeId: event.node_id || null,
        startedAt: event.timestamp,
        completedAt: null,
        failedAt: null,
        lastEventType: event.event_type,
        lastMessage: event.message || null,
      }
    },

    _handleStageCompleted(event: FactoryFrontendEvent) {
      const stageId = event.stage_id
      if (!stageId || !this.stages[stageId]) return

      this.stages[stageId].status = 'completed'
      this.stages[stageId].completedAt = event.timestamp
      this.stages[stageId].lastEventType = event.event_type
      this.stages[stageId].lastMessage = event.message || null
    },

    _handleStageFailed(event: FactoryFrontendEvent) {
      const stageId = event.stage_id
      if (!stageId || !this.stages[stageId]) return

      this.stages[stageId].status = 'failed'
      this.stages[stageId].failedAt = event.timestamp
      this.stages[stageId].lastEventType = event.event_type
      this.stages[stageId].lastMessage = event.message || null
    },

    /**
     * Node handlers
     */
    _handleNodeStarted(event: FactoryFrontendEvent) {
      const nodeId = event.node_id
      if (!nodeId) return

      this.nodes[nodeId] = {
        nodeId,
        stageId: event.stage_id || null,
        status: 'running',
        label: event.node_label || null,
        kind: event.node_kind || null,
        startedAt: event.timestamp,
        completedAt: null,
        failedAt: null,
        message: event.message || null,
        payload: event.payload || {},
      }
    },

    _handleNodeProgress(event: FactoryFrontendEvent) {
      const nodeId = event.node_id
      if (!nodeId) return

      if (!this.nodes[nodeId]) {
        this.nodes[nodeId] = {
          nodeId,
          stageId: event.stage_id || null,
          status: 'running',
          label: event.node_label || null,
          kind: event.node_kind || null,
          startedAt: event.timestamp,
          completedAt: null,
          failedAt: null,
          message: event.message || null,
          payload: event.payload || {},
        }
      } else {
        this.nodes[nodeId].message = event.message || null
        this.nodes[nodeId].payload = { ...this.nodes[nodeId].payload, ...event.payload }
      }
    },

    _handleNodeCompleted(event: FactoryFrontendEvent) {
      const nodeId = event.node_id
      if (!nodeId || !this.nodes[nodeId]) return

      this.nodes[nodeId].status = 'completed'
      this.nodes[nodeId].completedAt = event.timestamp
      this.nodes[nodeId].message = event.message || null
    },

    _handleNodeFailed(event: FactoryFrontendEvent) {
      const nodeId = event.node_id
      if (!nodeId) return

      if (!this.nodes[nodeId]) {
        this.nodes[nodeId] = {
          nodeId,
          stageId: event.stage_id || null,
          status: 'failed',
          label: event.node_label || null,
          kind: event.node_kind || null,
          startedAt: event.timestamp,
          completedAt: null,
          failedAt: event.timestamp,
          message: event.message || null,
          payload: event.payload || {},
        }
      } else {
        this.nodes[nodeId].status = 'failed'
        this.nodes[nodeId].failedAt = event.timestamp
        this.nodes[nodeId].message = event.message || null
      }
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
      if (isBackgroundEvent(event, this.activeRequestId)) return
      const streamId = event.payload?.stream_id
      if (!streamId) return

      this.modelStreams[streamId] = {
        streamId,
        requestId: event.request_id || null,
        nodeId: event.node_id || null,
        content: '',
        active: true,
        completedAt: null,
        visibleToUser: event.payload?.visible_to_user !== false,
      }
    },

    _handleModelStreamDelta(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      const streamId = event.payload?.stream_id
      const delta = event.payload?.delta
      if (!streamId || delta == null) return
      const visibleToUser = event.payload?.visible_to_user !== false
      if (!visibleToUser) {
        this._discardAssistantMessageStream(streamId, event.timestamp)
        return
      }

      if (!this.modelStreams[streamId]) {
        this.modelStreams[streamId] = {
          streamId,
          requestId: event.request_id || null,
          nodeId: event.node_id || null,
          content: delta,
          active: true,
          completedAt: null,
          visibleToUser,
        }
      } else {
        this.modelStreams[streamId].requestId = this.modelStreams[streamId].requestId || event.request_id || null
        this.modelStreams[streamId].nodeId = this.modelStreams[streamId].nodeId || event.node_id || null
        this.modelStreams[streamId].visibleToUser = visibleToUser
        this.modelStreams[streamId].content += delta
      }
      const stream = this.modelStreams[streamId]
      if (stream.visibleToUser && stream.content) {
        this._upsertAssistantMessageFromStream(streamId, event.timestamp, event.request_id || stream.requestId || null)
      }
    },

    _handleModelMessageCompleted(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      const streamId = event.payload?.stream_id
      const content = event.payload?.content
      if (!streamId) return
      if (event.payload?.discard || event.payload?.visible_to_user === false) {
        this._discardAssistantMessageStream(streamId, event.timestamp)
        return
      }

      if (!this.modelStreams[streamId]) {
        // 没有 delta 时，直接用 snapshot 创建
        this.modelStreams[streamId] = {
          streamId,
          requestId: event.request_id || null,
          nodeId: event.node_id || null,
          content: content || '',
          active: false,
          completedAt: event.timestamp,
          visibleToUser: event.payload?.visible_to_user !== false,
        }
      } else {
        this.modelStreams[streamId].requestId = this.modelStreams[streamId].requestId || event.request_id || null
        // 有 delta 时，用 snapshot 补齐（或覆盖）
        if (content && content.length > this.modelStreams[streamId].content.length) {
          this.modelStreams[streamId].content = content
        }
        this.modelStreams[streamId].active = false
        this.modelStreams[streamId].completedAt = event.timestamp
      }

      // 添加到 transcript
      const stream = this.modelStreams[streamId]
      if (stream.visibleToUser && stream.content) {
        this._upsertAssistantMessageFromStream(streamId, event.timestamp, event.request_id || stream.requestId || null)
      }
    },

    /**
     * Tool handlers
     */
    _handleToolCallProposed(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      this._upsertToolActivityFromEvent(event, 'proposed')
    },

    _handleToolApprovalRequested(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      this.runStatus = 'interrupted'
      this.pendingInterrupt = event
      this._promoteAgentPackageScopeFromEvent(event)

      // 更新工具状态为 approval
      const requests = event.payload?.requests || []
      requests.forEach((req: any) => {
        const approvalEvent = {
          ...event,
          payload: { ...(event.payload || {}), ...req },
        } satisfies FactoryFrontendEvent
        const activity = this._upsertToolActivityFromEvent(approvalEvent, 'approval')
        if (activity) {
          activity.approvalState = 'pending'
          this._upsertTurnTool(activity)
        }
      })
    },

    _handleToolApprovalResolved(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      const approved = event.payload?.approved
      const toolCallId = event.payload?.tool_call_id
      this.pendingInterrupt = null
      if (this.runStatus === 'interrupted') {
        this.runStatus = 'running'
      }

      if (toolCallId) {
        const tool = this.tools.find((t) => t.toolCallId === toolCallId)
        if (tool) {
          tool.approvalState = approved ? 'approved' : 'rejected'
          this._upsertTurnTool(tool)
        }
      } else {
        this.tools
          .filter((tool) => tool.status === 'approval' && tool.approvalState === 'pending')
          .forEach((tool) => {
            tool.approvalState = approved ? 'approved' : 'rejected'
            this._upsertTurnTool(tool)
          })
      }
    },

    _handleToolCallStarted(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      this._upsertToolActivityFromEvent(event, 'started')
    },

    _handleToolCallCompleted(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      this._upsertToolActivityFromEvent(event, 'completed')
    },

    _handleToolCallFailed(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      this._upsertToolActivityFromEvent(event, 'failed')
    },

    _handleToolObservation(event: FactoryFrontendEvent) {
      if (isBackgroundEvent(event, this.activeRequestId)) return
      this._upsertToolActivityFromEvent(event, 'observed')
    },

    /**
     * Context/Memory/Knowledge/Scheduler handlers
     */
    _handleContextEvent(event: FactoryFrontendEvent) {
      const type = event.event_type
      if (type === 'context_prepare_started' || type.includes('compression_started')) {
        this.contextActivity.status = 'running'
      } else if (type.includes('completed') || type === 'context_window_updated') {
        this.contextActivity.status = 'completed'
      } else if (type.includes('failed')) {
        this.contextActivity.status = 'failed'
      } else if (type.includes('skipped')) {
        this.contextActivity.status = 'skipped'
      }
      this.contextActivity.eventType = type
      this.contextActivity.payload = event.payload
      if (type === 'context_window_updated') {
        this.contextWindow = contextWindowView(event)
      }
    },

    _handleMemoryEvent(event: FactoryFrontendEvent) {
      const type = event.event_type
      if (type.includes('queued') && !type.includes('failed')) {
        this.memoryActivity.status = 'writing'
      } else if (type.includes('completed')) {
        this.memoryActivity.status = 'completed'
      } else if (type.includes('failed')) {
        this.memoryActivity.status = 'failed'
      }
      this.memoryActivity.eventType = type
      this.memoryActivity.payload = event.payload
    },

    _handleKnowledgeEvent(event: FactoryFrontendEvent) {
      this.knowledgeActivity.push({
        eventType: event.event_type,
        timestamp: event.timestamp,
        sourceId: event.payload?.source_id || null,
        jobId: event.payload?.job_id || null,
        mode: event.payload?.mode || null,
        phase: event.payload?.phase || null,
        status: event.payload?.status || null,
        reportPath: event.payload?.report_path || null,
        payload: event.payload || {},
      })
      this._updateKnowledgeSources(event)
      if (event.event_type === 'knowledge_documents_listed') {
        const documents = event.payload?.documents || []
        this.knowledgeDocuments = Array.isArray(documents)
          ? documents.map(knowledgeDocumentView)
          : []
      } else if (event.event_type === 'knowledge_search_completed') {
        const results = event.payload?.results || []
        this.knowledgeResults = Array.isArray(results)
          ? results.map(knowledgeSearchResultView)
          : []
      } else if (event.event_type === 'knowledge_document_read') {
        this.knowledgeDocument = event.payload || null
      }
    },

    _handleWorkspaceEvent(event: FactoryFrontendEvent) {
      if (event.event_type === 'workspace_roots_listed') {
        const roots = event.payload?.roots || []
        this.workspaceRoots = Array.isArray(roots)
          ? roots.map(workspaceRootView)
          : []
      } else if (event.event_type === 'workspace_entries_listed') {
        const entries = event.payload?.entries || []
        this.workspaceEntries = Array.isArray(entries)
          ? entries.map(workspaceEntryView)
          : []
      } else if (event.event_type === 'workspace_file_read') {
        const payload = event.payload || {}
        this.workspaceFile = workspaceFileView(payload)
      }
    },

    _handleExtensionsEvent(event: FactoryFrontendEvent) {
      const mcpServers = Array.isArray(event.payload?.mcp_servers) ? event.payload?.mcp_servers : []
      const skills = Array.isArray(event.payload?.skills) ? event.payload?.skills : []
      this.extensionItems = [
        ...mcpServers.map((item: any) => extensionItemView(item, 'mcp')),
        ...skills.map((item: any) => extensionItemView(item, 'skill')),
      ]
      if (event.event_type === 'extension_config_tested') {
        this.extensionTestResult = event.payload?.test || event.payload || null
      } else if (event.event_type === 'extension_config_updated') {
        this.extensionTestResult = null
      }
    },

    _handleSchedulerEvent(event: FactoryFrontendEvent) {
      this.schedulerActivity.push({
        eventType: event.event_type,
        timestamp: event.timestamp,
        jobId: event.payload?.job_id || null,
        runId: event.payload?.run_id || null,
        targetType: event.payload?.target_type || null,
        status: event.payload?.status || null,
        reportPath: event.payload?.report_path || null,
        payload: event.payload || {},
      })
      this._updateSchedulerJobs(event)
      this._updateSchedulerOptions(event)
      this._updateSchedulerRunNotices(event)
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
          const errorMessage = event.message || event.payload?.message || '请求失败'
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
      if (this._hasLiveConversationState()) {
        return
      }
      if (!snapshot.hasMessages) return

      this.transcript = snapshot.transcript
      this.conversationTurns = snapshot.conversationTurns
      this._saveActiveConversationScope()
    },

    _restoreAgentPackageSession(session: any, packageId: string | null = null) {
      if (!session?.session_id) return
      const snapshot = agentPackageSessionSnapshotView(session, packageId)
      this.activeAgentSessionId = String(session.session_id)
      this.currentMode = 'agent_package'
      this._switchConversationScope(agentPackageConversationScope(snapshot.sessionPackageId, session.session_id))
      this._upsertAgentSession(session)
      if (this._hasLiveConversationState()) {
        return
      }
      this.currentPlan = null
      this.contextActivity = { status: 'idle' }
      this.contextWindow = null
      this.modelStreams = {}
      this.tools = []
      this.pendingInterrupt = null

      this.transcript = snapshot.transcript
      this.conversationTurns = snapshot.conversationTurns
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

    _ensureTurnForRequest(requestId: string | null, timestamp?: string): ConversationTurn {
      const existing = requestId
        ? this.conversationTurns.find((turn) => turn.requestId === requestId)
        : null
      if (existing) return existing
      const fallback = !requestId ? this.conversationTurns[this.conversationTurns.length - 1] : null
      if (fallback && fallback.status === 'running') return fallback
      const turn: ConversationTurn = {
        id: requestId || `turn-${Date.now()}`,
        requestId,
        status: this.runStatus,
        userMessage: null,
        assistantMessages: [],
        tools: [],
        startedAt: timestamp || new Date().toISOString(),
        completedAt: null,
        errorMessage: null,
      }
      this.conversationTurns.push(turn)
      return turn
    },

    _upsertAssistantMessageFromStream(streamId: string, timestamp: string, requestId: string | null = null) {
      const stream = this.modelStreams[streamId]
      if (!stream || !stream.content.trim()) return
      const existingIdx = this.transcript.findIndex((t) => t.streamId === streamId)
      let item: TranscriptItem
      if (existingIdx >= 0) {
        item = this.transcript[existingIdx]
        item.content = stream.content
        item.timestamp = timestamp
      } else {
        item = {
          id: streamId,
          role: 'assistant',
          content: stream.content,
          timestamp,
          streamId,
        }
        this.transcript.push(item)
      }
      const turn = this._ensureTurnForRequest(requestId || stream.requestId || this.activeRequestId, timestamp)
      const existingMessage = turn.assistantMessages.find((message) => message.streamId === streamId)
      if (existingMessage) {
        existingMessage.content = item.content
        existingMessage.timestamp = item.timestamp
      } else {
        turn.assistantMessages.push(item)
      }
    },

    _discardAssistantMessageStream(streamId: string, timestamp: string) {
      const stream = this.modelStreams[streamId]
      if (stream) {
        stream.content = ''
        stream.active = false
        stream.completedAt = timestamp
        stream.visibleToUser = false
      } else {
        this.modelStreams[streamId] = {
          streamId,
          requestId: null,
          nodeId: null,
          content: '',
          active: false,
          completedAt: timestamp,
          visibleToUser: false,
        }
      }
      this.transcript = this.transcript.filter((message) => message.streamId !== streamId)
      this.conversationTurns.forEach((turn) => {
        turn.assistantMessages = turn.assistantMessages.filter((message) => message.streamId !== streamId)
      })
    },

    _upsertToolActivityFromEvent(
      event: FactoryFrontendEvent,
      status: ToolActivity['status'],
    ): ToolActivity | null {
      const payload = event.payload || {}
      const toolCallId = toolPayloadValue(payload, ['tool_call_id', 'toolCallId'])
      const toolName = toolPayloadValue(payload, ['tool_name', 'tool_id', 'name'])
      const activityKey = String(toolCallId || event.span_id || event.event_id)
      const existingIndex = this.tools.findIndex((item) => (
        item.activityKey === activityKey ||
        Boolean(toolCallId && item.toolCallId === String(toolCallId))
      ))
      const existing = existingIndex >= 0 ? this.tools[existingIndex] : null
      const activity: ToolActivity = {
        activityKey: existing?.activityKey || activityKey,
        requestId: event.request_id || existing?.requestId || null,
        eventType: event.event_type,
        timestamp: event.timestamp,
        createdAt: existing?.createdAt || event.timestamp,
        stageId: event.stage_id || existing?.stageId || null,
        nodeId: event.node_id || existing?.nodeId || null,
        toolCallId: toolCallId ? String(toolCallId) : existing?.toolCallId || null,
        toolName: toolName ? String(toolName) : existing?.toolName || '工具调用',
        status,
        approvalState: existing?.approvalState || null,
        payload: {
          ...(existing?.payload || {}),
          ...payload,
          arguments: {
            ...toolPayloadArguments(existing?.payload || {}),
            ...toolPayloadArguments(payload),
          },
        },
      }
      if (existingIndex >= 0) {
        this.tools[existingIndex] = activity
      } else {
        this.tools.push(activity)
      }
      this._upsertTurnTool(activity)
      return activity
    },

    _upsertTurnTool(tool: ToolActivity) {
      const turn = this._ensureTurnForRequest(tool.requestId || this.activeRequestId, tool.timestamp)
      const index = turn.tools.findIndex((item) => item.activityKey === tool.activityKey)
      if (index >= 0) {
        turn.tools[index] = { ...tool }
      } else {
        turn.tools.push({ ...tool })
      }
    },

    _updateKnowledgeSources(event: FactoryFrontendEvent) {
      if (Array.isArray(event.payload?.sources)) {
        this.knowledgeSources = event.payload.sources.map((source: any) => knowledgeSourceView(source, event.timestamp))
        return
      }
      if (event.event_type === 'knowledge_source_removed') {
        const sourceId = event.payload?.source_id
        if (sourceId) {
          this.knowledgeSources = this.knowledgeSources.filter((source) => source.payload?.source_id !== sourceId)
          this.knowledgeDocuments = this.knowledgeDocuments.filter((document) => document.payload?.source_id !== sourceId)
          this.knowledgeResults = this.knowledgeResults.filter((result) => result.payload?.source_id !== sourceId)
        }
        return
      }
      const source = event.payload?.source || event.payload?.preview || null
      const sourceId = event.payload?.source_id || source?.source_id
      if (!sourceId && !source?.display_name) return
      const item = knowledgeSourceView(source || event.payload, event.timestamp)
      const key = String(sourceId || item.name)
      const index = this.knowledgeSources.findIndex((value) => String(value.payload?.source_id || value.name) === key)
      if (index >= 0) {
        this.knowledgeSources[index] = item
      } else {
        this.knowledgeSources.unshift(item)
      }
    },

    _updateSchedulerJobs(event: FactoryFrontendEvent) {
      if (event.event_type === 'scheduler_job_deleted') {
        const jobId = event.payload?.job_id
        this.schedulerJobs = this.schedulerJobs.filter((item) => item.payload?.job_id !== jobId)
        return
      }
      const jobs = event.payload?.payload?.jobs || event.payload?.jobs
      if (Array.isArray(jobs)) {
        this.schedulerJobs = jobs.map(schedulerJobView)
        return
      }
      const job = event.payload?.payload?.job || event.payload?.job
      if (!job) return
      const view = schedulerJobView(job)
      const index = this.schedulerJobs.findIndex((item) => item.payload?.job_id === job.job_id)
      if (index >= 0) {
        this.schedulerJobs[index] = view
      } else {
        this.schedulerJobs.unshift(view)
      }
    },

    _updateSchedulerOptions(event: FactoryFrontendEvent) {
      if (event.event_type !== 'scheduler_options_listed') return
      const tools = event.payload?.payload?.tools || event.payload?.tools || []
      this.schedulerToolOptions = Array.isArray(tools)
        ? tools
            .map(schedulerToolOptionView)
            .filter((tool): tool is NonNullable<ReturnType<typeof schedulerToolOptionView>> => tool !== null)
        : []
    },

    _updateSchedulerRunNotices(event: FactoryFrontendEvent) {
      if (![
        'scheduler_run_scheduled',
        'scheduler_run_started',
        'scheduler_run_completed',
        'scheduler_run_failed',
        'scheduler_run_skipped',
        'scheduler_run_cancelled',
      ].includes(event.event_type)) {
        return
      }
      const notice = schedulerRunNoticeView(event)
      if (!notice) return
      const index = this.schedulerRunNotices.findIndex((item) => item.id === notice.id)
      if (index >= 0) {
        this.schedulerRunNotices[index] = {
          ...this.schedulerRunNotices[index],
          ...notice,
          unread: notice.status === 'running' ? this.schedulerRunNotices[index].unread : true,
        }
      } else {
        this.schedulerRunNotices.unshift(notice)
      }
      if (this.schedulerRunNotices.length > 30) {
        this.schedulerRunNotices = this.schedulerRunNotices.slice(0, 30)
      }
    },

    markSchedulerNoticeRead(noticeId: string) {
      const notice = this.schedulerRunNotices.find((item) => item.id === noticeId)
      if (notice) {
        notice.unread = false
      }
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
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.workspaceEntries = []
      this.workspaceFile = null
      this.extensionTestResult = null
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
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.activeAgentSessionId = null
    },

    _recordDebugEvent(event: FactoryFrontendEvent) {
      this.debugEvents.push(event)
      // 保留最近 100 条
      if (this.debugEvents.length > 100) {
        this.debugEvents.shift()
      }
    },

    _recordTimelineEvent(event: FactoryFrontendEvent) {
      this.timeline.push({
        id: event.event_id,
        eventType: event.event_type,
        timestamp: event.timestamp,
        spanId: event.span_id || null,
        parentSpanId: event.parent_span_id || null,
        stageId: event.stage_id || null,
        nodeId: event.node_id || null,
        nodeLabel: event.node_label || null,
        message: event.message || null,
        severity: event.severity || null,
        payload: event.payload || {},
      })
      // 保留最近 200 条
      if (this.timeline.length > 200) {
        this.timeline.shift()
      }
    },

    /**
     * 添加用户消息到 transcript
     */
    addUserMessage(content: string, requestId: string | null = null, metadata: Record<string, any> = {}) {
      const timestamp = new Date().toISOString()
      const item: TranscriptItem = {
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        timestamp,
        metadata,
      }
      this.transcript.push(item)
      const turn = this._ensureTurnForRequest(requestId, timestamp)
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

  },
})
