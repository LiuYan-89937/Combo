import mermaid from 'mermaid'
import { markdownApi } from '@/api/markdown'
import { runtimeLocale, translate } from '@/i18n'

const handlerRoots = new WeakSet<EventTarget>()
const interactionNodes = new WeakSet<HTMLElement>()
const sources = new WeakMap<HTMLElement, string>()
const repairRequests = new Map<string, Promise<string | null>>()
let configuredTheme = ''
let themeObserver: MutationObserver | null = null
let renderQueue: Promise<void> = Promise.resolve()
let preview: MermaidPreview | null = null
let activeDiagram: HTMLElement | null = null
let outsideInteractionReady = false

const ASPECT_WIDE = 1.6
const ASPECT_TALL = 0.8
const ZOOM_MIN = 0.25
const ZOOM_MAX = 4
const ZOOM_STEP = 0.1

interface MermaidPreview {
  root: HTMLElement
  viewport: HTMLElement
  stage: HTMLElement
  closeButton: HTMLButtonElement
  zoomInput: HTMLInputElement
  zoomLabel: HTMLElement
  svg: SVGSVGElement | null
  sourceWidth: number
  sourceHeight: number
  fitScale: number
  zoom: number
}

export function enhanceMermaidDiagrams(root: ParentNode): Promise<void> {
  if (!root.querySelector('.mermaid')) return Promise.resolve()
  ensureControls(root)
  ensureThemeObserver()
  return enqueueRender(() => {
    if (root instanceof Node && !root.isConnected) return Promise.resolve()
    return renderDiagrams(root)
  })
}

function ensureControls(root: ParentNode): void {
  const eventRoot = root as ParentNode & EventTarget
  if (handlerRoots.has(eventRoot)) return
  eventRoot.addEventListener('click', handleControlClick)
  handlerRoots.add(eventRoot)
  if (!outsideInteractionReady) {
    document.addEventListener('pointerdown', handleOutsideDiagramPointerDown)
    outsideInteractionReady = true
  }
}

function handleControlClick(event: Event): void {
  const target = event.target
  if (!(target instanceof Element)) return
  const button = target.closest<HTMLButtonElement>('[data-mermaid-expand="true"]')
  if (!button) return
  const svg = button.closest<HTMLElement>('.mermaid')?.querySelector<SVGSVGElement>('svg')
  if (!svg) return
  event.preventDefault()
  event.stopPropagation()
  openPreview(svg)
}

function enqueueRender(task: () => Promise<void>): Promise<void> {
  const next = renderQueue.then(task, task)
  renderQueue = next.catch(() => undefined)
  return next
}

async function renderDiagrams(root: ParentNode, force = false): Promise<void> {
  const nodes = Array.from(root.querySelectorAll<HTMLElement>('.mermaid'))
  if (nodes.length === 0) return
  const theme = activeTheme()
  const repairs: Array<{ node: HTMLElement; source: string; error: unknown }> = []
  configureTheme(theme)
  for (const node of nodes) {
    const source = sources.get(node) || String(node.textContent || '').trim()
    if (!source) continue
    sources.set(node, source)
    if (!force && node.dataset.processed === 'true' && node.dataset.mermaidTheme === theme) {
      finishDiagram(node)
      continue
    }
    node.textContent = source
    node.removeAttribute('data-processed')
    node.classList.remove('mermaid-render-failed')
    try {
      await mermaid.run({ nodes: [node] })
      node.dataset.mermaidTheme = theme
      finishDiagram(node)
    } catch (error) {
      console.error('Mermaid render error:', error)
      if (node.closest('.message-part.streaming')) {
        node.textContent = source
        node.removeAttribute('data-processed')
        continue
      }
      renderRepairing(node)
      repairs.push({ node, source, error })
    }
  }
  for (const repair of repairs) {
    await repairAndRender(repair.node, repair.source, repair.error, theme)
  }
}

function activeTheme(): string {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

function configureTheme(theme: string): void {
  if (configuredTheme === theme) return
  const styles = getComputedStyle(document.documentElement)
  const color = (name: string) => styles.getPropertyValue(name).trim()
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: 'base',
    themeVariables: {
      background: color('--app-surface'),
      primaryColor: color('--app-surface-elevated'),
      primaryTextColor: color('--app-text'),
      primaryBorderColor: color('--app-border-hover'),
      lineColor: color('--app-text-secondary'),
      secondaryColor: color('--app-surface-muted'),
      tertiaryColor: color('--app-surface-pressed'),
      clusterBkg: color('--app-surface-elevated'),
      clusterBorder: color('--app-border'),
      edgeLabelBackground: color('--app-surface'),
    },
  })
  configuredTheme = theme
}

function ensureThemeObserver(): void {
  if (themeObserver) return
  themeObserver = new MutationObserver((records) => {
    if (!records.some(record => record.attributeName === 'data-theme')) return
    configuredTheme = ''
    void enqueueRender(() => renderDiagrams(document, true))
  })
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
}

function finishDiagram(node: HTMLElement): void {
  node.classList.remove('mermaid-render-failed', 'mermaid-repairing')
  classifyDiagram(node)
  ensureExpandButton(node)
  ensureDiagramInteraction(node)
}

function ensureDiagramInteraction(node: HTMLElement): void {
  if (interactionNodes.has(node)) return
  interactionNodes.add(node)
  node.tabIndex = 0
  node.addEventListener('click', (event) => {
    const target = event.target
    if (target instanceof Element && target.closest('[data-mermaid-expand="true"]')) return
    activateDiagram(node)
  })
  node.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      activateDiagram(node)
    } else if (event.key === 'Escape') {
      deactivateDiagram(node)
      node.blur()
    }
  })
  node.addEventListener('focusout', () => {
    window.setTimeout(() => {
      if (!node.contains(document.activeElement)) deactivateDiagram(node)
    }, 0)
  })
}

function activateDiagram(node: HTMLElement): void {
  if (activeDiagram && activeDiagram !== node) deactivateDiagram(activeDiagram)
  activeDiagram = node
  node.dataset.mermaidInteractive = 'true'
  node.focus({ preventScroll: true })
}

function deactivateDiagram(node: HTMLElement): void {
  if (activeDiagram === node) activeDiagram = null
  delete node.dataset.mermaidInteractive
}

function handleOutsideDiagramPointerDown(event: PointerEvent): void {
  if (!activeDiagram) return
  const target = event.target
  if (target instanceof Node && activeDiagram.contains(target)) return
  deactivateDiagram(activeDiagram)
}

function classifyDiagram(node: HTMLElement): void {
  const dimensions = svgDimensions(node.querySelector('svg'))
  if (!dimensions) return
  const ratio = dimensions.width / dimensions.height
  node.dataset.mermaidAspect = ratio >= ASPECT_WIDE ? 'wide' : ratio <= ASPECT_TALL ? 'tall' : 'balanced'
}

function ensureExpandButton(node: HTMLElement): void {
  if (!node.querySelector('svg') || node.querySelector('[data-mermaid-expand="true"]')) return
  const label = translate(runtimeLocale(), 'markdown.expandDiagram')
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'mermaid-expand-button'
  button.dataset.mermaidExpand = 'true'
  button.title = label
  button.setAttribute('aria-label', label)
  const icon = document.createElement('span')
  icon.setAttribute('aria-hidden', 'true')
  icon.textContent = '⛶'
  button.append(icon)
  node.append(button)
}

async function repairAndRender(
  node: HTMLElement,
  source: string,
  error: unknown,
  theme: string,
): Promise<void> {
  const repairedSource = await requestRepair(source, error)
  if (!repairedSource || repairedSource === source) {
    renderFailure(node, source, theme)
    return
  }
  sources.set(node, repairedSource)
  node.textContent = repairedSource
  node.removeAttribute('data-processed')
  node.classList.remove('mermaid-repairing')
  try {
    await mermaid.run({ nodes: [node] })
    node.dataset.mermaidTheme = theme
    node.dataset.mermaidRepaired = 'true'
    finishDiagram(node)
  } catch (repairError) {
    console.error('Repaired Mermaid render error:', repairError)
    renderFailure(node, repairedSource, theme)
  }
}

function requestRepair(source: string, error: unknown): Promise<string | null> {
  const existing = repairRequests.get(source)
  if (existing) return existing
  const request = markdownApi.repairMermaid(source, errorText(error))
    .then(result => String(result.source || '').trim() || null)
    .catch((repairError) => {
      console.error('Mermaid automatic repair failed:', repairError)
      return null
    })
  repairRequests.set(source, request)
  return request
}

function errorText(error: unknown): string {
  if (error instanceof Error) return `${error.name}: ${error.message}`
  return String(error || '')
}

function renderRepairing(node: HTMLElement): void {
  node.replaceChildren()
  node.classList.add('mermaid-repairing')
  const status = document.createElement('span')
  status.textContent = translate(runtimeLocale(), 'markdown.diagramRepairing')
  node.append(status)
}

function renderFailure(node: HTMLElement, source: string, theme: string): void {
  node.replaceChildren()
  node.classList.add('mermaid-render-failed')
  node.dataset.processed = 'true'
  node.dataset.mermaidTheme = theme
  const title = document.createElement('strong')
  title.textContent = translate(runtimeLocale(), 'markdown.diagramSyntaxError')
  const code = document.createElement('pre')
  code.textContent = source
  node.append(title, code)
}

function openPreview(svg: SVGSVGElement): void {
  const current = ensurePreview()
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.removeAttribute('width')
  clone.removeAttribute('height')
  const dimensions = svgDimensions(clone)
  if (!dimensions) return
  current.svg = clone
  current.sourceWidth = dimensions.width
  current.sourceHeight = dimensions.height
  current.zoom = 1
  current.stage.replaceChildren(clone)
  current.root.classList.add('is-open')
  current.root.setAttribute('aria-hidden', 'false')
  document.body.classList.add('mermaid-preview-open')
  requestAnimationFrame(() => {
    current.fitScale = Math.min(
      current.viewport.clientWidth / current.sourceWidth,
      current.viewport.clientHeight / current.sourceHeight,
    )
    applyPreviewZoom(current, 1)
  })
  current.closeButton.focus()
}

function ensurePreview(): MermaidPreview {
  if (preview) return preview
  const root = document.createElement('div')
  root.className = 'mermaid-preview'
  root.setAttribute('role', 'dialog')
  root.setAttribute('aria-modal', 'true')
  root.setAttribute('aria-hidden', 'true')

  const header = document.createElement('div')
  header.className = 'mermaid-preview-header'
  const title = document.createElement('strong')
  title.textContent = translate(runtimeLocale(), 'markdown.diagramPreview')
  const controls = document.createElement('div')
  controls.className = 'mermaid-preview-controls'
  const zoomOut = controlButton('−', 'markdown.zoomOut')
  const zoomInput = document.createElement('input')
  zoomInput.className = 'mermaid-preview-zoom'
  zoomInput.type = 'range'
  zoomInput.min = String(ZOOM_MIN * 100)
  zoomInput.max = String(ZOOM_MAX * 100)
  zoomInput.step = String(ZOOM_STEP * 100)
  zoomInput.value = '100'
  zoomInput.setAttribute('aria-label', translate(runtimeLocale(), 'markdown.diagramZoom'))
  const zoomLabel = document.createElement('span')
  zoomLabel.className = 'mermaid-preview-zoom-label'
  const zoomIn = controlButton('+', 'markdown.zoomIn')
  const closeButton = document.createElement('button')
  closeButton.type = 'button'
  closeButton.className = 'mermaid-preview-close'
  closeButton.textContent = '×'
  closeButton.title = translate(runtimeLocale(), 'common.close')
  closeButton.setAttribute('aria-label', translate(runtimeLocale(), 'common.close'))
  controls.append(zoomOut, zoomInput, zoomLabel, zoomIn, closeButton)
  header.append(title, controls)

  const viewport = document.createElement('div')
  viewport.className = 'mermaid-preview-viewport'
  const stage = document.createElement('div')
  stage.className = 'mermaid-preview-stage'
  viewport.append(stage)
  const panel = document.createElement('div')
  panel.className = 'mermaid-preview-panel'
  panel.append(header, viewport)
  root.append(panel)
  document.body.append(root)

  const close = () => {
    root.classList.remove('is-open')
    root.setAttribute('aria-hidden', 'true')
    stage.replaceChildren()
    document.body.classList.remove('mermaid-preview-open')
  }
  closeButton.addEventListener('click', close)
  root.addEventListener('click', event => event.target === root && close())
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && root.classList.contains('is-open')) close()
  })

  preview = {
    root,
    viewport,
    stage,
    closeButton,
    zoomInput,
    zoomLabel,
    svg: null,
    sourceWidth: 0,
    sourceHeight: 0,
    fitScale: 1,
    zoom: 1,
  }
  zoomOut.addEventListener('click', () => preview && applyPreviewZoom(preview, preview.zoom - ZOOM_STEP))
  zoomIn.addEventListener('click', () => preview && applyPreviewZoom(preview, preview.zoom + ZOOM_STEP))
  zoomInput.addEventListener('input', () => preview && applyPreviewZoom(preview, Number(zoomInput.value) / 100))
  viewport.addEventListener('wheel', (event) => {
    if ((!event.ctrlKey && !event.metaKey) || !preview) return
    event.preventDefault()
    applyPreviewZoom(preview, preview.zoom + (event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP))
  }, { passive: false })
  return preview
}

function controlButton(icon: string, labelKey: 'markdown.zoomIn' | 'markdown.zoomOut'): HTMLButtonElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'mermaid-preview-control'
  button.textContent = icon
  const label = translate(runtimeLocale(), labelKey)
  button.title = label
  button.setAttribute('aria-label', label)
  return button
}

function applyPreviewZoom(current: MermaidPreview, value: number): void {
  if (!current.svg) return
  current.zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value))
  current.zoomInput.value = String(Math.round(current.zoom * 100))
  current.zoomLabel.textContent = `${Math.round(current.zoom * 100)}%`
  current.svg.style.width = `${current.sourceWidth * current.fitScale * current.zoom}px`
  current.svg.style.height = `${current.sourceHeight * current.fitScale * current.zoom}px`
  requestAnimationFrame(() => centerPreview(current.viewport))
}

function centerPreview(viewport: HTMLElement): void {
  viewport.scrollTo({
    left: Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2),
    top: Math.max(0, (viewport.scrollHeight - viewport.clientHeight) / 2),
  })
}

function svgDimensions(svg: SVGSVGElement | null): { width: number; height: number } | null {
  if (!svg) return null
  const values = String(svg.getAttribute('viewBox') || '').trim().split(/\s+/).map(Number)
  if (values.length !== 4 || !values.every(Number.isFinite) || values[2] <= 0 || values[3] <= 0) return null
  return { width: values[2], height: values[3] }
}
