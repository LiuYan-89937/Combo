<template>
  <n-message-provider>
    <div class="pf">
      <!-- A/B：超长内容 + 流式状态抖动 -->
      <template v-if="!longCount">
        <section id="pf-long" class="pf-section">
          <p class="pf-title">A · 单个回合里的超长内容（思考 200k 字、命令输出 200k 字、结果 JSON 200k 字）</p>
          <MessageItem :message="hugeMessage" :streaming="false" />
        </section>

        <section id="pf-flicker" class="pf-section">
          <p class="pf-title">B · 流式思考（streaming 每 700ms 关一下：模拟回合中间的 stream 空档）</p>
          <MessageItem :message="flickerMessage" :streaming="streamingFlag" />
        </section>

        <section id="pf-many" class="pf-section">
          <p class="pf-title">A2 · 一次回合 30 个工具调用（展开后总高）</p>
          <MessageItem :message="manyToolsMessage" :streaming="false" />
        </section>
      </template>

      <!-- C：长记录 -->
      <template v-else>
        <section id="pf-long-transcript" class="pf-section">
          <p class="pf-title">C · 长记录（{{ longCount }} 个回合）</p>
          <MessageItem v-for="item in longTranscript" :key="item.id" :message="item" :streaming="false" />
        </section>
      </template>

      <pre id="pf-probe">{{ probe }}</pre>
    </div>
  </n-message-provider>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { NMessageProvider } from 'naive-ui'
import MessageItem from '@/components/chat/MessageItem.vue'
import { getPalette } from '@/theme/palette'
import { applyPaletteToRoot } from '@/theme/cssVariables'
import type {
  ChatMessage,
  ChatMessagePart,
  ReasoningMessagePart,
  TextMessagePart,
  ToolExecutionMessagePart,
} from '@/types/protocol'

const params = new URLSearchParams(window.location.search)
applyPaletteToRoot(getPalette(params.get('theme') !== 'light'), params.get('theme') === 'light' ? 'light' : 'dark')

const iso = (offset: number) => new Date(Date.now() + offset).toISOString()

function reasoning(id: string, text: string, status: string): ReasoningMessagePart {
  return { id, type: 'reasoning', text, status } as ReasoningMessagePart
}
function text(id: string, value: string): TextMessagePart {
  return { id, type: 'text', format: 'markdown', text: value, status: 'completed' }
}
function tool(id: string, name: string, status: string, output: unknown, args: unknown = {}): ToolExecutionMessagePart {
  return {
    id,
    type: 'tool_execution',
    toolName: name,
    callId: `call-${id}`,
    arguments: args,
    output,
    artifacts: [],
    status,
    startedAt: iso(-20_000),
    completedAt: iso(-18_000),
  } as ToolExecutionMessagePart
}

const HUGE = 200_000
const hugeReasoning = `思考开始：\n${'推理片段，包含代码与列表。\n'.repeat(Math.ceil(HUGE / 30))}`
const hugeStdout = Array.from({ length: 4000 }, (_, i) => `src/components/file-${i}.vue:${i}:  <img src="..." />`).join('\n')
const hugeJson = JSON.stringify({ rows: Array.from({ length: 4000 }, (_, i) => ({ index: i, path: `dir/file-${i}.ts`, note: 'x'.repeat(20) })) }, null, 1)

const hugeMessage: ChatMessage = {
  id: 'pf-huge',
  role: 'assistant',
  content: '',
  status: 'completed' as never,
  timestamp: iso(0),
  parts: [
    reasoning('pf-huge-r', hugeReasoning, 'completed'),
    tool('pf-huge-t1', 'run_command', 'completed', { stdout: hugeStdout, command: 'rg -n "<img" src' }, { command: 'rg -n "<img" src' }),
    tool('pf-huge-t2', 'read_file', 'completed', { content: hugeJson }, { path: 'data.json' }),
    text('pf-huge-a', '上面是超长内容，正文本身不设限。'),
  ] as ChatMessagePart[],
}

// B · 用响应式 message 模拟真实抖动：part.status 在 streaming / completed 之间来回。
const flickerMessage = ref<ChatMessage>({
  id: 'pf-flicker',
  role: 'assistant',
  content: '',
  status: 'streaming' as never,
  timestamp: iso(0),
  parts: [
    reasoning('pf-flicker-r', '正在思考：先看渲染链路。', 'streaming'),
    tool('pf-flicker-t', 'run_command', 'completed', { stdout: 'ok', command: 'ls' }, { command: 'ls' }),
    text('pf-flicker-n', '先确认一下现状。'),
    text('pf-flicker-a', '结论：还在写。'),
  ] as ChatMessagePart[],
})

const manyToolsMessage: ChatMessage = {
  id: 'pf-many',
  role: 'assistant',
  content: '',
  status: 'completed' as never,
  timestamp: iso(0),
  parts: [
    reasoning('pf-many-r', '先做一轮探索。', 'completed'),
    ...Array.from({ length: 30 }, (_, i) => tool(
      `pf-many-t${i}`,
      i % 3 === 0 ? 'read_file' : i % 3 === 1 ? 'grep' : 'run_command',
      'completed',
      { stdout: `第 ${i} 次输出\n` + 'y'.repeat(200), content: 'z'.repeat(200) },
      { path: `src/file-${i}.ts` },
    )),
    text('pf-many-a', '30 次工具调用结束。'),
  ] as ChatMessagePart[],
}

const longCount = Number(params.get('n') || 0)const PROSE = [
  '先看这一段渲染链路，确认折叠与展开的边界。',
  '```ts\nconst value = compute(input)\n```',
  '再把工具结果接进来，确认滚动窗口的高度。',
  '- 第一项\n- 第二项\n- 第三项',
]
const longTranscript: ChatMessage[] = Array.from({ length: longCount }, (_, index) => ({
  id: `pf-long-${index}`,
  role: 'assistant',
  content: '',
  status: 'completed' as never,
  timestamp: iso(-index * 60_000),
  parts: [
    reasoning(`pf-long-${index}-r`, `第 ${index} 轮：${PROSE[index % PROSE.length]}`, 'completed'),
    tool(`pf-long-${index}-t`, 'run_command', 'completed', { stdout: `第 ${index} 轮输出\n` + 'x'.repeat(400) }, { command: `echo ${index}` }),
    text(`pf-long-${index}-n`, `第 ${index} 轮说明：${PROSE[(index + 1) % PROSE.length]}`),
    text(`pf-long-${index}-a`, `第 ${index} 轮回答：${PROSE[(index + 2) % PROSE.length]}\n\n链接 [示例](https://example.com/${index})`),
  ] as ChatMessagePart[],
}))

const probe = ref('等待测量…')
let timer: number | null = null
let errors = 'no-errors'
const flickerSamples: string[] = []
const streamingFlag = ref(true)

function measureElement(selector: string, label: string): string {
  const element = document.querySelector<HTMLElement>(selector)
  if (!element) return `${label}=缺失`
  return `${label}=${Math.round(element.clientHeight)}(内容 ${Math.round(element.scrollHeight)})`
}

function openAll(root: string): void {
  document.querySelectorAll<HTMLDetailsElement>(`${root} details`).forEach((details) => { details.open = true })
}

function measure(): void {
  if (!longCount) {
    const reasonRow = document.querySelector<HTMLDetailsElement>('#pf-long .part-reasoning details')
    if (reasonRow) reasonRow.open = true
    document.querySelectorAll<HTMLDetailsElement>('#pf-long .tool-execution-card').forEach((card) => { card.open = true })
    document.querySelectorAll<HTMLDetailsElement>('#pf-long .tool-section').forEach((section) => { section.open = true })
    const turn = document.querySelector<HTMLElement>('#pf-long .message-item')
    const flickerRow = document.querySelector<HTMLDetailsElement>('#pf-flicker .part-reasoning details')
    probe.value = [
      `A 超长内容（展开后高度 clientHeight(scrollHeight)）：`,
      `  ${measureElement('#pf-long .part-reasoning .reasoning-markdown', '思考正文')}`,
      `  ${measureElement('#pf-long .structured-results.shell-output pre', '命令输出')}`,
      `  ${measureElement('#pf-long .tool-execution-card .tool-section pre', '结果 JSON')}`,
      `  回合总高=${turn ? Math.round(turn.getBoundingClientRect().height) : '-'} 页面总高=${document.body.scrollHeight}`,
      `B 流式思考开合：${flickerSamples.length ? `${flickerSamples.join('')} 抖动次数=${countFlips(flickerSamples)}` : '采集中'}`,
      `  当前 open=${flickerRow ? flickerRow.open : '-'}`,
      `长记录：回合数=${longCount} DOM 节点=${document.getElementsByTagName('*').length} 挂载=${Math.round(Number((window as any).__mountMs || 0))}ms 堆=${heapMb()}`,
      `错误=${errors}`,
    ].join('\n')
  } else {
    const first = document.querySelector<HTMLElement>('#pf-long-transcript .message-item')
    probe.value = [
      `长记录：回合数=${longCount}`,
      `  DOM 节点=${document.getElementsByTagName('*').length}`,
      `  挂载=${Math.round(Number((window as any).__mountMs || 0))}ms 现在=${Math.round(performance.now() - Number((window as any).__bootTs || 0))}ms`,
      `  堆=${heapMb()}`,
      `  首个回合高=${first ? Math.round(first.getBoundingClientRect().height) : '-'} 页面总高=${document.body.scrollHeight}`,
      `错误=${errors}`,
    ].join('\n')
  }
}

function countFlips(samples: string[]): number {
  let flips = 0
  samples.forEach((value, index) => {
    if (index > 0 && value !== samples[index - 1]) flips += 1
  })
  return flips
}

function heapMb(): string {
  const memory = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory
  return memory ? `${Math.round((memory.usedJSHeapSize / 1024 / 1024) * 10) / 10}MB` : '不可用'
}

onMounted(() => {
  ;(window as any).__bootTs = performance.now()
  const record = (kind: string, detail: unknown) => {
    const message = detail instanceof Error ? detail.message : String(detail)
    errors = errors === 'no-errors' ? `${kind}: ${message}` : `${errors}; ${kind}: ${message}`
  }
  window.addEventListener('error', event => record('error', event.error || event.message))
  window.addEventListener('unhandledrejection', event => record('unhandledrejection', event.reason))

  if (!longCount) {
    let toggle = 0
    window.setInterval(() => {
      toggle += 1
      const parts = flickerMessage.value.parts.map(part => (
        part.type === 'reasoning'
          ? { ...part, status: toggle % 2 ? 'completed' : 'streaming' } as ChatMessagePart
          : part
      ))
      flickerMessage.value = { ...flickerMessage.value, parts, timestamp: iso(0) }
    }, 400)
    window.setInterval(() => {
      const row = document.querySelector<HTMLDetailsElement>('#pf-flicker .part-reasoning details')
      if (row) flickerSamples.push(row.open ? '开' : '关')
      if (flickerSamples.length > 40) flickerSamples.shift()
    }, 200)
  } else {
    // 长记录：测一次滚动到底的成本。
    window.setTimeout(() => {
      const scroller = document.scrollingElement
      if (scroller) scroller.scrollTop = scroller.scrollHeight
      const started = performance.now()
      requestAnimationFrame(() => {
        ;(window as any).__scrollMs = performance.now() - started
      })
    }, 600)
  }

  timer = window.setInterval(measure, 400)
  measure()
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<style scoped>
.pf {
  min-height: 100vh;
  padding: 24px 28px 400px;
  background: var(--app-bg);
  color: var(--app-text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

.pf-section {
  max-width: 900px;
  margin: 0 auto 22px;
  padding: 14px 16px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
}

.pf-title { margin: 0 0 12px; color: var(--app-text-secondary); font-size: 12px; font-weight: 600; }

.pf-probe {
  position: fixed;
  right: 12px;
  bottom: 12px;
  z-index: 999999;
  max-width: 620px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid #3a3a3a;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.85);
  color: #9ef;
  font: 11px/1.5 ui-monospace, Menlo, monospace;
  white-space: pre-wrap;
  pointer-events: none;
}
</style>
