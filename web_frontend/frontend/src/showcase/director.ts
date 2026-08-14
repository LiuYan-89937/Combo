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
const CHAT_PACKAGE_ID = 'main_chat'
const showcaseCopy = {
  'zh-CN': {
    prompt: '请分工完成东京五日亲子旅行手册，并给出可直接执行的最终版本。',
    delegation: '我已拆分任务：调研员核对实时资料，行程编排师处理路线与节奏，文档交付员负责最终手册。',
    researchAgent: '旅行资料调研员',
    researchObjective: '并行核对东京亲子旅行的实时资料与开放时间。',
    progress: '实时资料与路线编排已经汇总，文档交付员正在生成最终 PDF。',
    completion: '协作完成。最终版本包含每日路线、交通换乘、预算、预约清单与雨天备选。',
    artifactName: '东京五日亲子旅行手册.pdf',
    artifactPath: 'output/东京五日亲子旅行手册.pdf',
    mainAgent: '主 Agent',
    chatName: '闲聊',
    chatDescription: '系统内置通用 Agent。',
    plannerName: '旅行规划师',
    plannerDescription: '检索目的地信息，规划行程并生成可交付的旅行手册。',
    destinationResearcher: '目的地调研员',
    itineraryDesigner: '行程编排师',
    documentAssistant: '文档交付员',
    sessionTitle: '东京五日亲子行程',
    sessionInput: '规划一份东京五日亲子旅行方案',
  },
  'en-US': {
    prompt: 'Delegate a five-day Tokyo family travel guide and deliver a final version we can use immediately.',
    delegation: 'I split the work: a researcher is verifying live information, an itinerary designer is shaping the route and pace, and a document specialist owns the final guide.',
    researchAgent: 'Travel research agent',
    researchObjective: 'Verify live Tokyo family-travel information and opening hours in parallel.',
    progress: 'The research and route plan are consolidated. The document specialist is generating the final PDF.',
    completion: 'Collaboration complete. The final guide includes daily routes, transfers, budget, reservations, and rainy-day alternatives.',
    artifactName: 'Tokyo-family-travel-guide.pdf',
    artifactPath: 'output/Tokyo-family-travel-guide.pdf',
    mainAgent: 'Main Agent',
    chatName: 'Chat',
    chatDescription: 'Built-in general-purpose Agent.',
    plannerName: 'Travel planner',
    plannerDescription: 'Research destinations, plan itineraries, and produce a shareable travel guide.',
    destinationResearcher: 'Destination researcher',
    itineraryDesigner: 'Itinerary designer',
    documentAssistant: 'Document specialist',
    sessionTitle: 'Five days in Tokyo with kids',
    sessionInput: 'Plan a five-day family trip to Tokyo',
  },
} as const

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
    while (!stopped) {
      cycle += 1
      await collaborationScene()
      await wait(4200)
    }
  }

  async function collaborationScene(): Promise<void> {
    const copy = showcaseCopy[uiStore.locale]
    await showcaseRouter.replace({
      name: 'ChatNew',
    })
    await waitForView('.conversation-view')
    agentStore.enterAgentChat(CHAT_PACKAGE_ID, null)
    runtimeStore.showEmptyAgentPackageSession(CHAT_PACKAGE_ID)
    resetConversation()
    uiStore.setConversationDockPanel(null)
    const input = await waitForElement<HTMLTextAreaElement>('.message-input-container textarea')
    if (input) {
      await typeText(input, copy.prompt)
      appendMessage(message('user', [
        textPart(copy.prompt),
      ]))
      updateInputValue(input, '')
    }
    await wait(900)
    appendMessage(message('assistant', [
      textPart(copy.delegation),
      toolPart('delegate', 'running', {
        agent_name: copy.researchAgent,
        objective: copy.researchObjective,
        capabilities: [],
      }, null),
    ], { display_name: copy.mainAgent }))
    runtimeStore.runStatus = 'waiting_for_workers'
    await wait(1800)

    completeLastTool({
      status: 'submitted',
      submitted_count: 3,
    })
    appendMessage(message('assistant', [
      textPart(copy.progress),
    ], { display_name: copy.mainAgent }))
    await wait(1700)
    runtimeStore.runStatus = 'completed'
    appendMessage(message('assistant', [
      textPart(copy.completion),
      artifactPart(copy.artifactName, copy.artifactPath),
    ], { display_name: copy.mainAgent }))
  }

  function seedAgents(): void {
    const copy = showcaseCopy[uiStore.locale]
    const localizedPlanner = {
      ...agentPackage,
      agent_name: copy.plannerName,
      name: copy.plannerName,
      agent_description: copy.plannerDescription,
    }
    agentStore.setPackages([
      {
        ...agentPackage,
        package_id: CHAT_PACKAGE_ID,
        agent_id: CHAT_PACKAGE_ID,
        agent_name: copy.chatName,
        name: copy.chatName,
        agent_description: copy.chatDescription,
      } as any,
      localizedPlanner as any,
      {
        ...localizedPlanner,
        package_id: 'destination_researcher',
        agent_id: 'destination_researcher',
        agent_name: copy.destinationResearcher,
        name: copy.destinationResearcher,
      },
      {
        ...localizedPlanner,
        package_id: 'itinerary_designer',
        agent_id: 'itinerary_designer',
        agent_name: copy.itineraryDesigner,
        name: copy.itineraryDesigner,
      },
      {
        ...localizedPlanner,
        package_id: 'document_assistant',
        agent_id: 'document_assistant',
        agent_name: copy.documentAssistant,
        name: copy.documentAssistant,
      },
    ])
    agentStore.setRecentSessions([{
      session_id: SHOWCASE_SESSION_ID,
      package_id: SHOWCASE_PACKAGE_ID,
      display_title: copy.sessionTitle,
      first_user_input: copy.sessionInput,
      turn_count: 4,
      created_at: '2026-07-29T02:00:00.000Z',
      updated_at: '2026-07-29T02:26:00.000Z',
      agent_name: copy.plannerName,
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
    updateInputValue(input, '')
    let value = ''
    for (const character of text) {
      if (stopped) return
      value += character
      updateInputValue(input, value)
      await wait(78)
    }
  }

  function updateInputValue(input: HTMLTextAreaElement, value: string): void {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
    setter?.call(input, value)
    input.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      composed: true,
      data: value.slice(-1) || null,
      inputType: value ? 'insertText' : 'deleteContentBackward',
    }))
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
