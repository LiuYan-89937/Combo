import { nextTick } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import { useUiStore } from '@/stores/ui'
import type { ChatMessagePart, TranscriptItem } from '@/types/protocol'
import { showcaseRouter } from './router'
import {
  SHOWCASE_PACKAGE_ID,
  SHOWCASE_SESSION_ID,
  agentPackage,
} from './fakeServer'

const BASE_TIME = '2026-07-29T02:20:00.000Z'
const CHAT_PACKAGE_ID = 'factory_chat'

export function useShowcaseDirector() {
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const uiStore = useUiStore()
  const preferences = useRuntimePreferencesStore()
  let stopped = false
  let cycle = 0

  function start(): void {
    stopped = false
    preferences.setMainModelProfileId('showcase-main-model')
    preferences.setReasoningIntensity(2)
    seedAgents()
    void play()
  }

  function stop(): void {
    stopped = true
  }

  async function play(): Promise<void> {
    cycle += 1
    await collaborationScene()
  }

  async function collaborationScene(): Promise<void> {
    await showcaseRouter.replace({
      name: 'ChatNew',
    })
    await waitForView('.factory-view')
    agentStore.enterAgentChat(CHAT_PACKAGE_ID, null)
    runtimeStore.showEmptyAgentPackageSession(CHAT_PACKAGE_ID)
    resetConversation()
    uiStore.setConversationDockPanel(null)
    const input = await waitForElement<HTMLTextAreaElement>('.message-input-container textarea')
    if (input) {
      await typeText(input, '请分工完成东京五日亲子旅行手册，并给出可直接执行的最终版本。')
      appendMessage(message('user', [
        textPart('请分工完成东京五日亲子旅行手册，并给出可直接执行的最终版本。'),
      ]))
      input.value = ''
    }
    await wait(900)
    appendMessage(message('assistant', [
      textPart('我已拆分任务：调研员核对实时资料，行程编排师处理路线与节奏，文档交付员负责最终手册。'),
      toolPart('delegate', 'running', {
        agent_name: '旅行资料调研员',
        objective: '并行核对东京亲子旅行的实时资料与开放时间。',
        capabilities: [],
      }, null),
    ], { display_name: '主 Agent' }))
    runtimeStore.runStatus = 'waiting_for_workers'
    await wait(1800)

    completeLastTool({
      status: 'submitted',
      submitted_count: 3,
    })
    appendMessage(message('assistant', [
      textPart('实时资料与路线编排已经汇总，文档交付员正在生成最终 PDF。'),
    ], { display_name: '主 Agent' }))
    await wait(1700)
    runtimeStore.runStatus = 'completed'
    appendMessage(message('assistant', [
      textPart('协作完成。最终版本包含每日路线、交通换乘、预算、预约清单与雨天备选。'),
      artifactPart('东京五日亲子旅行手册.pdf', 'output/东京五日亲子旅行手册.pdf'),
    ], { display_name: '主 Agent' }))
  }

  function seedAgents(): void {
    agentStore.setPackages([
      {
        ...agentPackage,
        package_id: CHAT_PACKAGE_ID,
        agent_id: CHAT_PACKAGE_ID,
        agent_name: '闲聊',
        name: '闲聊',
        agent_description: '系统内置通用 Agent。',
      } as any,
      agentPackage as any,
      {
        ...agentPackage,
        package_id: 'destination_researcher',
        agent_id: 'destination_researcher',
        agent_name: '目的地调研员',
        name: '目的地调研员',
      },
      {
        ...agentPackage,
        package_id: 'itinerary_designer',
        agent_id: 'itinerary_designer',
        agent_name: '行程编排师',
        name: '行程编排师',
      },
      {
        ...agentPackage,
        package_id: 'document_assistant',
        agent_id: 'document_assistant',
        agent_name: '文档交付员',
        name: '文档交付员',
      },
    ])
    agentStore.setRecentSessions([{
      session_id: SHOWCASE_SESSION_ID,
      package_id: SHOWCASE_PACKAGE_ID,
      display_title: '东京五日亲子行程',
      first_user_input: '规划一份东京五日亲子旅行方案',
      turn_count: 4,
      created_at: '2026-07-29T02:00:00.000Z',
      updated_at: '2026-07-29T02:26:00.000Z',
      agent_name: '旅行规划师',
      visible_in_agent_session_list: true,
    }])
    runtimeStore.connectionStatus = 'connected'
  }

  function resetConversation(): void {
    runtimeStore.transcript = []
    runtimeStore.conversationTurns = []
    runtimeStore.tools = []
    runtimeStore.modelStreams = {}
    runtimeStore.activeRequestId = null
    runtimeStore.activeRequests = {}
    runtimeStore.runStatus = 'idle'
    runtimeStore.pendingInterrupt = null
  }

  function appendMessage(item: TranscriptItem): void {
    runtimeStore.transcript.push(item)
  }

  function completeLastTool(output: unknown): void {
    const item = [...runtimeStore.transcript].reverse()
      .find((candidate) => candidate.parts.some(
        (part) => part.type === 'tool_execution' && part.status === 'running',
      ))
    const part = item
      ? [...item.parts].reverse().find(
        (candidate) => candidate.type === 'tool_execution' && candidate.status === 'running',
      )
      : undefined
    if (!part || part.type !== 'tool_execution') return
    part.status = 'completed'
    part.output = output
    part.updatedAt = new Date().toISOString()
  }

  return { start, stop }

  async function wait(milliseconds: number): Promise<void> {
    if (stopped) return
    await new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds))
  }

  async function waitForView(selector: string): Promise<void> {
    await nextTick()
    await waitForElement(selector)
  }

  async function waitForElement<T extends Element = Element>(selector: string): Promise<T | null> {
    for (let attempt = 0; attempt < 100 && !stopped; attempt += 1) {
      const element = document.querySelector<T>(selector)
      if (element) return element
      await wait(60)
    }
    return null
  }

  async function typeText(input: HTMLTextAreaElement, text: string): Promise<void> {
    input.value = ''
    for (const character of text) {
      if (stopped) return
      input.value += character
      await wait(78)
    }
  }

  function id(prefix: string): string {
    return `${prefix}-${cycle}-${crypto.randomUUID()}`
  }

  function message(
    role: 'user' | 'assistant' | 'system',
    parts: ChatMessagePart[],
    metadata: Record<string, any> = {},
  ): TranscriptItem {
    return {
      id: id(`message-${role}`),
      role,
      parts,
      content: parts
        .filter((part) => part.type === 'text')
        .map((part) => part.type === 'text' ? part.text : '')
        .join('\n'),
      timestamp: new Date().toISOString(),
      status: 'completed',
      metadata,
    }
  }

  function textPart(text: string): ChatMessagePart {
    return {
      id: id('text'),
      type: 'text',
      format: 'markdown',
      text,
      status: 'completed',
      createdAt: BASE_TIME,
      updatedAt: BASE_TIME,
    }
  }

  function toolPart(
    toolName: string,
    status: 'running' | 'completed',
    args: unknown,
    output: unknown,
  ): ChatMessagePart {
    return {
      id: id('tool'),
      type: 'tool_execution',
      toolName,
      callId: id('call'),
      arguments: args,
      output,
      error: null,
      approvalState: null,
      artifacts: [],
      status,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
  }

  function artifactPart(name: string, path: string): ChatMessagePart {
    return {
      id: id('artifact'),
      type: 'artifact',
      name,
      path,
      mimeType: 'application/pdf',
      sizeBytes: 2841032,
      status: 'completed',
      createdAt: BASE_TIME,
      updatedAt: BASE_TIME,
    }
  }

}
