# Agent 群聊实现 - 可复用组件与逻辑分析报告

## 📊 复用机会总览

| 类别 | 现有组件/逻辑 | 当前实现状态 | 复用建议 |
|------|--------------|-------------|----------|
| **消息渲染** | `MessageItem.vue` | ❌ 自己实现 | ✅ 应复用 |
| **消息输入** | `MessageInput.vue` | ❌ 自己实现 | ✅ 应复用 |
| **工具审批** | `ToolApprovalPanel.vue` | ❌ 未集成 | ✅ 应复用 |
| **SSE 事件流** | `useEventStream.ts` | ❌ 用轮询 | ✅ 必须复用 |
| **Runtime 投影** | `useFactoryMessageProjection.ts` | ❌ 未集成 | ✅ 应复用 |
| **Scope 路由** | `runtime/scopes.ts` | ❌ 未扩展 | ✅ 必须扩展 |
| **工作区浏览** | `WorkspaceExplorer.vue` | ❌ 占位按钮 | ✅ 应复用 |

---

## 1️⃣ 消息渲染（❌ 当前自己实现，✅ 应复用）

### 现有组件
**`MessageItem.vue`** — 完整的消息渲染组件
- ✅ 支持用户/Agent/系统消息
- ✅ 支持流式渲染（`streaming` prop）
- ✅ 支持 thinking 状态
- ✅ 支持 markdown/code block
- ✅ 时间戳、头像、状态标签

### 当前实现（AgentGroupView.vue:36-62）
```vue
<!-- ❌ 自己写的简化版消息渲染 -->
<div v-if="message.speaker_type === 'user'" class="user-message">
  <div class="message-header">
    <span class="speaker">用户</span>
    <span class="timestamp">{{ formatTime(message.created_at) }}</span>
  </div>
  <div class="message-content">{{ message.content }}</div>
</div>

<div v-else-if="message.speaker_type === 'agent'" class="agent-message">
  <div class="message-header">
    <span class="speaker">{{ getAgentName(message.speaker_package_id) }}</span>
    <n-tag v-if="message.group_run_id" size="small">
      {{ getRunStatus(message.group_run_id) }}
    </n-tag>
    <span class="timestamp">{{ formatTime(message.created_at) }}</span>
  </div>
  <div class="message-content" :class="`kind-${message.message_kind}`">
    {{ message.content }}
  </div>
</div>
```

### 复用建议
✅ **替换为**：
```vue
<MessageItem
  v-for="message in projectedMessages"
  :key="message.id"
  :message="message"
  :streaming="isMessageStreaming(message.streamId)"
/>
```

**需要做的**：
1. Store 增加 `projectedMessages` computed（转换 `AgentGroupMessageView` → `TranscriptMessage`）
2. 复用 `CollaborationView.vue` 的消息投影模式

---

## 2️⃣ 消息输入（❌ 当前自己实现，✅ 应复用）

### 现有组件
**`MessageInput.vue`** — 完整的消息输入组件
- ✅ 附件上传
- ✅ Cmd/Ctrl+Enter 发送
- ✅ 禁用状态处理
- ✅ placeholder 自定义
- ✅ autosize

### 当前实现（AgentGroupView.vue:110-133）
```vue
<!-- ❌ 自己写的简化版输入框 + @mention 选择器 -->
<n-input
  v-model:value="messageInput"
  type="textarea"
  :placeholder="..."
  :autosize="{ minRows: 3, maxRows: 8 }"
  @keydown="handleKeyDown"
  @input="handleInput"
/>
```

### 复用建议
✅ **替换为**：
```vue
<MessageInput
  ref="inputRef"
  :disabled="inputDisabled"
  :placeholder="t('agentGroup.inputPlaceholder')"
  @send="handleSend"
/>
```

**@mention 逻辑保留**：
- 在 `handleSend` 里解析 `selectedMentions`
- 或者扩展 `MessageInput` 支持 `@mention` 模式（可选）

---

## 3️⃣ 工具审批（❌ 未集成，✅ 应复用）

### 现有组件
**`ToolApprovalPanel.vue`** — 完整的审批面板
- ✅ 审批请求列表
- ✅ 风险等级标签
- ✅ 参数折叠展示
- ✅ 批量审批/拒绝按钮

### 当前实现
❌ **完全缺失** — 只在 store 里有 `status: 'awaiting_approval'` 状态

### 复用建议
✅ **添加到 AgentGroupView.vue**：
```vue
<ToolApprovalPanel
  v-if="hasApprovalRequests"
  :requests="approvalRequests"
  :runtime-key="activeStreamContentKey"
  @approve="handleApprove"
  @reject="handleReject"
/>
```

**需要做的**：
1. Store 增加 `approvalRequests` computed（从 `activeRuns` 里筛选 `awaiting_approval`）
2. Composable 增加 `handleApprove/handleReject` 调用 runtime API

---

## 4️⃣ SSE 事件流（❌ 当前轮询，✅ 必须复用）

### 现有基础设施
**`useEventStream.ts`** + **`stores/runtime.ts`**
- ✅ `/events` SSE 端点
- ✅ `EventStreamClient` 自动重连
- ✅ `runtime.handleEvent()` 全局事件分发
- ✅ Scope 路由机制（`scopeFromEventPayload`）

### 当前实现（AgentGroupView.vue:140-150）
```typescript
// ❌ 错误：手动轮询
let refreshTimer: number | null = null
watch(() => store.activeGroup, (group) => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (group && store.activeRuns.length > 0) {
    refreshTimer = window.setInterval(() => {
      store.loadGroup(group.group_id)  // 每3秒全量刷新
    }, 3000)
  }
})
```

### 复用建议
✅ **删除轮询，扩展 SSE scope 路由**：

#### Step 1: 扩展 `runtime/scopes.ts`
```typescript
// 新增 agentGroupConversationScope
export function agentGroupConversationScope(
  groupId: string | null,
  speakerPackageId: string | null,
): string {
  return `agent_group:${groupId || 'unknown'}:${speakerPackageId || 'unknown'}`
}

// 扩展 conversationScopeForMode
export function conversationScopeForMode(
  mode: string | null,
  payload: Record<string, any> = {},
): string | null {
  // ... 现有逻辑 ...
  if (mode === 'agent_group_member') {
    return agentGroupConversationScope(payload.group_id, payload.speaker_package_id)
  }
  return null
}
```

#### Step 2: 后端扩展（event_projection.py 已有基础）
当前 `event_projection.py` 已经在记录消息到 DB，SSE 事件的 `payload` 里应该包含：
```python
{
  "mode": "agent_group_member",
  "group_id": "xxx",
  "speaker_package_id": "agent-a",
  "group_run_id": "xxx"
}
```

#### Step 3: Store 监听 SSE 更新
```typescript
// stores/agentGroup.ts 新增
watch(
  () => runtimeStore.lastEvent,  // 监听全局事件
  (event) => {
    if (event?.mode === 'agent_group_member' && event.payload?.group_id === activeGroup.value?.group_id) {
      // 增量更新（而非全量刷新）
      applyGroupSnapshot(event.payload.group_snapshot)
    }
  }
)
```

**好处**：
- ✅ 实时更新（无延迟）
- ✅ 无需轮询（节省带宽）
- ✅ 复用全局 SSE 连接

---

## 5️⃣ Runtime 消息投影（❌ 未集成，✅ 应复用）

### 现有 Composable
**`useFactoryMessageProjection.ts`**
- ✅ `thinkingMessages` — 转圈消息
- ✅ `timelineItems` — 时间线视图（消息 + 事件）
- ✅ `hasApprovalRequests` — 审批检测
- ✅ `isMessageStreaming` — 流式检测

### 当前实现
❌ **完全缺失** — 只渲染 `store.messages` 的静态快照

### 复用建议
✅ **创建 `useAgentGroupRuntime.ts`**（镜像 `useCollaborationRuntime.ts`）：
```typescript
export function useAgentGroupRuntime() {
  const store = useAgentGroupStore()
  const runtimeStore = useRuntimeStore()

  const {
    thinkingMessages,
    timelineItems,
    hasApprovalRequests,
    isMessageStreaming,
  } = useFactoryMessageProjection()

  // 转换 AgentGroupMessageView → TranscriptMessage
  const projectedMessages = computed(() => {
    return store.messages.map(msg => ({
      id: msg.message_id,
      role: msg.speaker_type === 'user' ? 'user' : 'assistant',
      content: msg.content,
      metadata: {
        speaker_package_id: msg.speaker_package_id,
        group_run_id: msg.group_run_id,
      },
      // ... 其他字段
    }))
  })

  return {
    projectedMessages,
    thinkingMessages,
    hasApprovalRequests,
    isMessageStreaming,
  }
}
```

---

## 6️⃣ 工作区浏览器（❌ 占位按钮，✅ 应复用）

### 现有组件
**`WorkspaceExplorer.vue`**
- ✅ 文件树渲染
- ✅ 文件预览（`FilePreview.vue`）
- ✅ 搜索/过滤

### 当前实现（AgentGroupSidebarPanel.vue:90-96）
```vue
<!-- ❌ 占位按钮 -->
<section class="sidebar-section">
  <div class="section-header">
    <h3>共享工作区</h3>
  </div>
  <div class="workspace-info">
    <p>版本: {{ store.activeGroup.current_workspace_revision }}</p>
    <n-button size="small" @click="openWorkspace">浏览文件</n-button>
  </div>
</section>
```

### 复用建议
✅ **替换为**：
```vue
<section class="sidebar-section">
  <div class="section-header">
    <h3>共享工作区</h3>
    <n-tag size="tiny">v{{ store.activeGroup.current_workspace_revision }}</n-tag>
  </div>
  <WorkspaceExplorer
    :workspace-root="store.activeGroup.workspace_resource?.workdir"
    :resource-mode="'agent_group'"
    compact
  />
</section>
```

**需要做的**：
1. 后端 `workspace_resources.py` 扩展支持 `resource_mode='agent_group'`
2. WorkspaceExplorer 支持 `compact` 模式（简化版，适合侧边栏）

---

## 7️⃣ Runtime Scope 扩展（❌ 未扩展，✅ 必须扩展）

### 现有机制
**`runtime/scopes.ts`** — 事件路由到正确的对话上下文
- ✅ `chat` → `factoryConversationScope('chat', sessionId)`
- ✅ `agent_package` → `agentPackageConversationScope(packageId, sessionId)`
- ✅ `collaboration_worker` → `collaborationWorkerScope(...)`

### 当前实现
❌ **未扩展** — `agent_group_member` 模式不被识别

### 复用建议
✅ **扩展 `conversationScopeForMode`**（已在第4点详细说明）

---

## 📊 复用优先级总结

| 优先级 | 复用项 | 影响 | 工作量 |
|--------|--------|------|--------|
| 🔴 **P0 必须** | SSE 事件流（删除轮询） | 实时性 + 性能 | 中（1-2小时） |
| 🔴 **P0 必须** | Runtime scope 扩展 | 事件路由正确性 | 小（30分钟） |
| 🟡 **P1 应该** | MessageItem 组件 | 代码质量 + 功能完整性 | 中（1小时） |
| 🟡 **P1 应该** | ToolApprovalPanel | 功能完整性 | 小（30分钟） |
| 🟢 **P2 可选** | MessageInput 组件 | 代码一致性 | 小（20分钟） |
| 🟢 **P2 可选** | WorkspaceExplorer | 用户体验 | 中（1小时） |
| 🟢 **P2 可选** | useFactoryMessageProjection | 代码一致性 | 中（1小时） |

---

## 🎯 建议修正顺序

1. **立即修正（P0）**：
   - 删除轮询代码
   - 扩展 SSE scope 路由
   - 监听 `runtime.lastEvent` 更新 store

2. **快速优化（P1）**：
   - 集成 `ToolApprovalPanel`
   - 替换为 `MessageItem` 组件

3. **后续增强（P2）**：
   - 创建 `useAgentGroupRuntime` composable
   - 集成 `WorkspaceExplorer`
   - 统一 `MessageInput`

---

## 总结

**当前实现的主要问题**：
- ❌ 轮询而非 SSE（性能 + 实时性）
- ❌ 自己写消息渲染（重复轮子）
- ❌ 缺少工具审批 UI（功能不完整）
- ❌ 未扩展 runtime scope（事件路由失效）

**复用现有组件后的好处**：
- ✅ 实时更新（SSE）
- ✅ 代码量减少 ~300 行
- ✅ 功能完整性（审批、流式、工作区）
- ✅ 风格一致性（与 collaboration/factory 对齐）

**你希望我修正这些问题吗？还是保持当前版本（可用但有优化空间）？**
