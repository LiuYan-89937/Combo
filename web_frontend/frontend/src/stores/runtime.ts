/**
 * Runtime Store - 核心状态管理
 *
 * 基于协议文档的 Request-Scoped Reducer 规则实现
 * 参考 CLI 的 runtimeStore.ts
 */
import { defineStore } from 'pinia'
import type {
  FactoryFrontendEvent,
  RuntimeViewState,
  ModelStream,
  ToolActivity,
  TranscriptItem,
  ConversationTurn,
  KnowledgeSourceView,
  KnowledgeDocumentView,
  KnowledgeSearchResultView,
  SchedulerJobView,
  WorkspaceEntry,
  WorkspaceFileView,
  WorkspaceRootView,
  ExtensionItemView,
} from '@/types/protocol'

// 事件去重集合
const processedEventIds = new Set<string>()

export const useRuntimeStore = defineStore('runtime', {
  state: (): RuntimeViewState => ({
    protocolVersion: 'factory_frontend.v1',
    connectionStatus: 'disconnected',
    activeRequestId: null,
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
    transcript: [],
    conversationTurns: [],
    timeline: [],
    debugEvents: [],
    contextActivity: { status: 'idle' },
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
    extensionItems: [],
    extensionTestResult: null,
    sessions: [],
    agentPackages: [],
    selectedAgentPackage: null,
    agentSessions: [],
  }),

  getters: {
    // 输入是否应该被锁定
    isInputLocked: (state): boolean => {
      return state.runStatus === 'running' || state.runStatus === 'interrupted'
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
      const isRequestScoped = this._isRequestScopedEvent(event.event_type)
      const isMismatchedActiveRequest =
        isRequestScoped &&
        this.activeRequestId !== null &&
        event.request_id !== null &&
        event.request_id !== this.activeRequestId
      if (isMismatchedActiveRequest) {
        // 不匹配的 request-scoped 事件只进入 debug/timeline，不更新主状态
        this._recordDebugEvent(event)
        this._recordTimelineEvent(event)
        return
      }

      // 4. 路由到具体处理器
      this._dispatchEvent(event)

      // 5. 记录到 timeline
      this._recordTimelineEvent(event)
    },

    /**
     * 判断是否为 request-scoped 事件
     */
    _isRequestScopedEvent(eventType: string): boolean {
      if (eventType === 'run_started') return false
      const requestScopedPrefixes = [
        'run_',
        'node_',
        'stage_',
        'model_',
        'tool_',
        'plan_',
        'context_',
        'runtime_paused',
        'runtime_resumed',
      ]
      return requestScopedPrefixes.some((prefix) => eventType.startsWith(prefix))
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
        this._clearSessionScopedState()
        this._restoreSessionSnapshot(payload)
      } else if (type === 'session_switched') {
        this.activeFactorySessionId = payload?.session_id || payload?.session?.session_id || event.session_id || null
        this._clearSessionScopedState()
        this._restoreSessionSnapshot(payload)
      } else if (type === 'sessions_listed') {
        this.sessions = payload?.sessions || []
      } else if (type === 'mode_changed') {
        this.currentMode = event.mode || null
      }

      // Agent packages
      else if (type === 'agent_packages_listed') {
        this.agentPackages = payload?.packages || []
      } else if (type === 'agent_package_selected') {
        this.selectedAgentPackage = payload?.package || null
        this.agentSessions = payload?.sessions || this.agentSessions
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
    _handleRunStarted(event: FactoryFrontendEvent) {
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
      this.runStatus = 'completed'
      const requestId = this.activeRequestId || event.request_id || null
      const turn = this._ensureTurnForRequest(requestId, event.timestamp)
      turn.status = 'completed'
      turn.completedAt = event.timestamp
      this.activeRequestId = null
      this.pendingInterrupt = null

      // 同步 agent session
      if (event.payload?.agent_session?.session_id) {
        this.activeAgentSessionId = event.payload.agent_session.session_id
        this._upsertAgentSession(event.payload.agent_session)
      }
    },

    _handleRunFailed(event: FactoryFrontendEvent) {
      this.runStatus = 'failed'
      const requestId = this.activeRequestId || event.request_id || null
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
      this.activeRequestId = null
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
      const streamId = event.payload?.stream_id
      if (!streamId) return

      this.modelStreams[streamId] = {
        streamId,
        nodeId: event.node_id || null,
        content: '',
        active: true,
        completedAt: null,
        visibleToUser: event.payload?.visible_to_user !== false,
      }
    },

    _handleModelStreamDelta(event: FactoryFrontendEvent) {
      const streamId = event.payload?.stream_id
      const delta = event.payload?.delta
      if (!streamId || delta == null) return

      if (!this.modelStreams[streamId]) {
        this.modelStreams[streamId] = {
          streamId,
          nodeId: event.node_id || null,
          content: delta,
          active: true,
          completedAt: null,
          visibleToUser: event.payload?.visible_to_user !== false,
        }
      } else {
        this.modelStreams[streamId].content += delta
      }
      const stream = this.modelStreams[streamId]
      if (stream.visibleToUser && stream.content) {
        this._upsertAssistantMessageFromStream(streamId, event.timestamp)
      }
    },

    _handleModelMessageCompleted(event: FactoryFrontendEvent) {
      const streamId = event.payload?.stream_id
      const content = event.payload?.content
      if (!streamId) return

      if (!this.modelStreams[streamId]) {
        // 没有 delta 时，直接用 snapshot 创建
        this.modelStreams[streamId] = {
          streamId,
          nodeId: event.node_id || null,
          content: content || '',
          active: false,
          completedAt: event.timestamp,
          visibleToUser: event.payload?.visible_to_user !== false,
        }
      } else {
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
        this._upsertAssistantMessageFromStream(streamId, event.timestamp)
      }
    },

    /**
     * Tool handlers
     */
    _handleToolCallProposed(event: FactoryFrontendEvent) {
      const toolCallId = event.payload?.tool_call_id
      const toolName = event.payload?.tool_name
      if (!toolCallId || !toolName) return

      const activity: ToolActivity = {
        activityKey: toolCallId,
        eventType: event.event_type,
        timestamp: event.timestamp,
        createdAt: event.timestamp,
        stageId: event.stage_id || null,
        nodeId: event.node_id || null,
        toolCallId,
        toolName,
        status: 'proposed',
        approvalState: null,
        payload: event.payload || {},
      }
      this.tools.push(activity)
      this._upsertTurnTool(activity)
    },

    _handleToolApprovalRequested(event: FactoryFrontendEvent) {
      this.runStatus = 'interrupted'
      this.pendingInterrupt = event

      // 更新工具状态为 approval
      const requests = event.payload?.requests || []
      requests.forEach((req: any) => {
        const tool = this.tools.find((t) => t.toolCallId === req.tool_call_id)
        if (tool) {
          tool.status = 'approval'
          tool.approvalState = 'pending'
          this._upsertTurnTool(tool)
        }
      })
    },

    _handleToolApprovalResolved(event: FactoryFrontendEvent) {
      const approved = event.payload?.approved
      const toolCallId = event.payload?.tool_call_id

      if (toolCallId) {
        const tool = this.tools.find((t) => t.toolCallId === toolCallId)
        if (tool) {
          tool.approvalState = approved ? 'approved' : 'rejected'
          this._upsertTurnTool(tool)
        }
      }
    },

    _handleToolCallStarted(event: FactoryFrontendEvent) {
      const toolCallId = event.payload?.tool_call_id
      const tool = this.tools.find((t) => t.toolCallId === toolCallId)
      if (tool) {
        tool.status = 'started'
        tool.payload = { ...tool.payload, ...event.payload }
        this._upsertTurnTool(tool)
      }
    },

    _handleToolCallCompleted(event: FactoryFrontendEvent) {
      const toolCallId = event.payload?.tool_call_id
      const tool = this.tools.find((t) => t.toolCallId === toolCallId)
      if (tool) {
        tool.status = 'completed'
        tool.payload = { ...tool.payload, ...event.payload }
        this._upsertTurnTool(tool)
      }
    },

    _handleToolCallFailed(event: FactoryFrontendEvent) {
      const toolCallId = event.payload?.tool_call_id
      const tool = this.tools.find((t) => t.toolCallId === toolCallId)
      if (tool) {
        tool.status = 'failed'
        tool.payload = { ...tool.payload, ...event.payload }
        this._upsertTurnTool(tool)
      }
    },

    _handleToolObservation(event: FactoryFrontendEvent) {
      const toolCallId = event.payload?.tool_call_id
      const tool = this.tools.find((t) => t.toolCallId === toolCallId)
      if (tool) {
        tool.status = 'observed'
        tool.payload = { ...tool.payload, ...event.payload }
        this._upsertTurnTool(tool)
      }
    },

    /**
     * Context/Memory/Knowledge/Scheduler handlers
     */
    _handleContextEvent(event: FactoryFrontendEvent) {
      const type = event.event_type
      if (type.includes('compression_started')) {
        this.contextActivity.status = 'running'
      } else if (type.includes('completed')) {
        this.contextActivity.status = 'completed'
      } else if (type.includes('failed')) {
        this.contextActivity.status = 'failed'
      }
      this.contextActivity.eventType = type
      this.contextActivity.payload = event.payload
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
          ? documents.map((document: any): KnowledgeDocumentView => this._knowledgeDocumentView(document))
          : []
      } else if (event.event_type === 'knowledge_search_completed') {
        const results = event.payload?.results || []
        this.knowledgeResults = Array.isArray(results)
          ? results.map((result: any): KnowledgeSearchResultView => this._knowledgeSearchResultView(result))
          : []
      } else if (event.event_type === 'knowledge_document_read') {
        this.knowledgeDocument = event.payload || null
      }
    },

    _handleWorkspaceEvent(event: FactoryFrontendEvent) {
      if (event.event_type === 'workspace_roots_listed') {
        const roots = event.payload?.roots || []
        this.workspaceRoots = Array.isArray(roots)
          ? roots.map((root: any): WorkspaceRootView => ({
              scope: root.scope,
              name: String(root.name || root.scope || 'Workspace'),
              exists: root.exists !== false,
            }))
          : []
      } else if (event.event_type === 'workspace_entries_listed') {
        const entries = event.payload?.entries || []
        this.workspaceEntries = Array.isArray(entries)
          ? entries.map((entry: any): WorkspaceEntry => ({
              name: String(entry.name || entry.path || '文件'),
              scope: entry.scope,
              path: String(entry.path || ''),
              kind: entry.kind === 'directory' ? 'directory' : 'file',
              sizeBytes: entry.size_bytes ?? entry.sizeBytes ?? null,
              updatedAt: entry.updated_at || entry.updatedAt || null,
            }))
          : []
      } else if (event.event_type === 'workspace_file_read') {
        const payload = event.payload || {}
        this.workspaceFile = {
          name: String(payload.name || payload.path || '文件'),
          scope: payload.scope,
          path: String(payload.path || ''),
          kind: payload.kind === 'binary' ? 'binary' : 'text',
          sizeBytes: Number(payload.size_bytes || payload.sizeBytes || 0),
          content: String(payload.content || ''),
          truncated: Boolean(payload.truncated),
          payload,
        } satisfies WorkspaceFileView
      }
    },

    _handleExtensionsEvent(event: FactoryFrontendEvent) {
      const mcpServers = Array.isArray(event.payload?.mcp_servers) ? event.payload?.mcp_servers : []
      const skills = Array.isArray(event.payload?.skills) ? event.payload?.skills : []
      this.extensionItems = [
        ...mcpServers.map((item: any): ExtensionItemView => this._extensionItemView(item, 'mcp')),
        ...skills.map((item: any): ExtensionItemView => this._extensionItemView(item, 'skill')),
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
    },

    /**
     * Error handler
     */
    _handleError(event: FactoryFrontendEvent) {
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

    /**
     * 辅助方法
     */
    _restoreSessionSnapshot(payload: Record<string, any> | undefined) {
      const session = payload?.session || payload || {}
      const snapshot = session.snapshot || payload?.snapshot || {}
      const messages = Array.isArray(snapshot.messages)
        ? snapshot.messages
        : Array.isArray(snapshot.transcript)
          ? snapshot.transcript
          : []
      if (messages.length === 0) return

      const transcript: TranscriptItem[] = []
      const turnsByIndex = new Map<string, ConversationTurn>()

      messages.forEach((message: any, index: number) => {
        const role = message.role === 'assistant' ? 'assistant' : message.role === 'system' ? 'system' : 'user'
        const turnKey = String(message.turn_index ?? Math.floor(index / 2) + 1)
        const restoredMode = snapshot.mode || session.current_mode || null
        const item: TranscriptItem = {
          id: `restored-${turnKey}-${role}-${index}`,
          role,
          content: String(message.content || ''),
          timestamp: String(message.created_at || message.timestamp || session.updated_at || new Date().toISOString()),
          metadata: {
            restored: true,
            mode: restoredMode,
          },
        }
        if (!item.content.trim()) return
        transcript.push(item)
        if (!turnsByIndex.has(turnKey)) {
          turnsByIndex.set(turnKey, {
            id: `restored-turn-${turnKey}`,
            requestId: null,
            status: 'completed',
            userMessage: null,
            assistantMessages: [],
            tools: [],
            startedAt: item.timestamp,
            completedAt: item.timestamp,
            errorMessage: null,
            metadata: {
              restored: true,
              mode: restoredMode,
            },
          })
        }
        const turn = turnsByIndex.get(turnKey)!
        if (role === 'user' && !turn.userMessage) {
          turn.userMessage = item
        } else if (role === 'assistant') {
          turn.assistantMessages.push(item)
        }
        turn.completedAt = item.timestamp
      })

      this.transcript = transcript
      this.conversationTurns = Array.from(turnsByIndex.values())
    },

    _restoreAgentPackageSession(session: any, packageId: string | null = null) {
      if (!session?.session_id) return
      this.activeAgentSessionId = String(session.session_id)
      this.currentMode = 'agent_package'
      this.currentPlan = null
      this.modelStreams = {}
      this.tools = []
      this.pendingInterrupt = null
      this._upsertAgentSession(session)

      const transcript: TranscriptItem[] = []
      const turns: ConversationTurn[] = []
      const sessionPackageId = packageId || session.package_id || null
      const rawTurns = Array.isArray(session.turns) ? session.turns : []

      rawTurns.forEach((turn: any, index: number) => {
        const turnIndex = String(turn?.index ?? index + 1)
        const timestamp = String(turn?.created_at || session.updated_at || new Date().toISOString())
        const metadata = {
          restored: true,
          mode: 'agent_package',
          package_id: sessionPackageId,
          agent_session_id: session.session_id,
        }
        const conversationTurn: ConversationTurn = {
          id: `agent-restored-turn-${session.session_id}-${turnIndex}`,
          requestId: null,
          status: 'completed',
          userMessage: null,
          assistantMessages: [],
          tools: [],
          startedAt: timestamp,
          completedAt: timestamp,
          errorMessage: null,
          metadata,
        }

        const userInput = String(turn?.user_input || '').trim()
        if (userInput) {
          const item: TranscriptItem = {
            id: `agent-restored-${session.session_id}-${turnIndex}-user`,
            role: 'user',
            content: userInput,
            timestamp,
            metadata,
          }
          transcript.push(item)
          conversationTurn.userMessage = item
        }

        const finalAnswer = String(turn?.final_answer || '').trim()
        if (finalAnswer) {
          const item: TranscriptItem = {
            id: `agent-restored-${session.session_id}-${turnIndex}-assistant`,
            role: 'assistant',
            content: finalAnswer,
            timestamp,
            metadata,
          }
          transcript.push(item)
          conversationTurn.assistantMessages.push(item)
        }

        if (conversationTurn.userMessage || conversationTurn.assistantMessages.length > 0) {
          turns.push(conversationTurn)
        }
      })

      this.transcript = transcript
      this.conversationTurns = turns
    },

    showEmptyAgentPackageSession(_packageId: string | null = null) {
      this.activeAgentSessionId = null
      this.currentMode = 'agent_package'
      this.currentPlan = null
      this.modelStreams = {}
      this.tools = []
      this.pendingInterrupt = null
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.workspaceFile = null
      this.workspaceEntries = []
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

    _upsertAssistantMessageFromStream(streamId: string, timestamp: string) {
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
      const turn = this._ensureTurnForRequest(this.activeRequestId, timestamp)
      const existingMessage = turn.assistantMessages.find((message) => message.streamId === streamId)
      if (existingMessage) {
        existingMessage.content = item.content
        existingMessage.timestamp = item.timestamp
      } else {
        turn.assistantMessages.push(item)
      }
    },

    _upsertTurnTool(tool: ToolActivity) {
      const turn = this._ensureTurnForRequest(this.activeRequestId, tool.timestamp)
      const index = turn.tools.findIndex((item) => item.activityKey === tool.activityKey)
      if (index >= 0) {
        turn.tools[index] = { ...tool }
      } else {
        turn.tools.push({ ...tool })
      }
    },

    _updateKnowledgeSources(event: FactoryFrontendEvent) {
      if (event.event_type === 'knowledge_sources_listed' && Array.isArray(event.payload?.sources)) {
        this.knowledgeSources = event.payload.sources.map((source: any): KnowledgeSourceView => (
          this._knowledgeSourceView(source, event.timestamp)
        ))
        return
      }
      if (event.event_type === 'knowledge_source_registered' && Array.isArray(event.payload?.sources)) {
        this.knowledgeSources = event.payload.sources.map((source: any): KnowledgeSourceView => (
          this._knowledgeSourceView(source, event.timestamp)
        ))
        return
      }
      const source = event.payload?.source || event.payload?.preview || null
      const sourceId = event.payload?.source_id || source?.source_id
      if (!sourceId && !source?.display_name) return
      const item = this._knowledgeSourceView(source || event.payload, event.timestamp)
      const key = String(sourceId || item.name)
      const index = this.knowledgeSources.findIndex((value) => String(value.payload?.source_id || value.name) === key)
      if (index >= 0) {
        this.knowledgeSources[index] = item
      } else {
        this.knowledgeSources.unshift(item)
      }
    },

    _knowledgeSourceView(source: any, timestamp: string): KnowledgeSourceView {
      const name = String(source?.display_name || source?.name || '知识源')
      return {
        name,
        status: String(source?.status || '更新中'),
        mode: source?.mount_mode || source?.mode || null,
        documentCount: source?.document_count ?? source?.estimated_documents ?? source?.counts?.documents_loaded ?? null,
        updatedAt: source?.updated_at || timestamp,
        payload: source || {},
      }
    },

    _knowledgeDocumentView(document: any): KnowledgeDocumentView {
      return {
        title: String(document.title || document.uri || '文档'),
        sourceName: document.source_name || null,
        documentType: document.document_type || null,
        uri: document.uri || null,
        payload: document || {},
      }
    },

    _knowledgeSearchResultView(result: any): KnowledgeSearchResultView {
      return {
        title: String(result.title || '搜索结果'),
        content: String(result.content || ''),
        score: typeof result.score === 'number' ? result.score : null,
        payload: result || {},
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
        this.schedulerJobs = jobs.map((job: any): SchedulerJobView => this._schedulerJobView(job))
        return
      }
      const job = event.payload?.payload?.job || event.payload?.job
      if (!job) return
      const view = this._schedulerJobView(job)
      const index = this.schedulerJobs.findIndex((item) => item.payload?.job_id === job.job_id)
      if (index >= 0) {
        this.schedulerJobs[index] = view
      } else {
        this.schedulerJobs.unshift(view)
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

    _schedulerJobView(job: any): SchedulerJobView {
      return {
        title: String(job.task_content || job.title || '定时任务'),
        schedule: String(job.schedule_expr || '未设置'),
        enabled: job.enabled !== false,
        status: job.enabled === false ? '已暂停' : '已启用',
        targetType: job.target?.target_type || null,
        payload: job || {},
      }
    },

    _extensionItemView(item: any, fallbackKind: 'mcp' | 'skill'): ExtensionItemView {
      const kind = item.kind === 'skill' ? 'skill' : item.kind === 'mcp' ? 'mcp' : fallbackKind
      return {
        name: String(item.name || (kind === 'mcp' ? 'MCP' : 'Skill')),
        kind,
        scope: String(item.scope || 'local'),
        status: String(item.status || (item.enabled === false ? 'disabled' : 'enabled')),
        enabled: item.enabled !== false,
        payload: item.payload || item || {},
      }
    },

    _clearSessionScopedState() {
      this.activeRequestId = null
      this.runStatus = 'idle'
      this.pendingInterrupt = null
      this.currentRunId = null
      this.nodes = {}
      this.stages = {}
      this.modelStreams = {}
      this.tools = []
      this.currentPlan = null
      this.transcript = []
      this.conversationTurns = []
      this.timeline = []
      this.workspaceEntries = []
      this.workspaceFile = null
      this.extensionTestResult = null
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
    },
  },
})
