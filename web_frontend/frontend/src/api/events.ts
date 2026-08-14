import type { RuntimeFrontendEvent } from '@/types/protocol'
import { runtimePrincipalId } from './runtimeIdentity'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error' | 'reconnecting'

export interface EventStreamConfig {
  url: string
  onEvent: (event: RuntimeFrontendEvent) => void
  onStatusChange: (status: ConnectionStatus) => void
  onError: (error: Error) => void
}

const RECONNECT_INITIAL_DELAY_MS = 500
const RECONNECT_MAX_DELAY_MS = 10_000
const CONNECTION_HEALTH_CHECK_MS = 15_000
const CONNECTION_STALE_AFTER_MS = 45_000

export class EventStreamClient {
  private source: EventSource | null = null
  private status: ConnectionStatus = 'disconnected'
  private seenEventIds = new Set<string>()
  private reconnectTimer: number | null = null
  private reconnectAttempt = 0
  private stopped = true
  private healthTimer: number | null = null
  private lastActivityAt = 0

  constructor(private readonly config: EventStreamConfig) {}

  connect(): void {
    if (!this.stopped && (this.source || this.reconnectTimer !== null)) {
      this.ensureConnected()
      return
    }
    this.stopped = false
    this.startHealthMonitor()
    this.openSource()
  }

  ensureConnected(): void {
    if (this.stopped) {
      this.connect()
      return
    }
    if (!this.source && this.reconnectTimer === null) {
      this.openSource()
      return
    }
    if (this.source && this.lastActivityAt > 0 && Date.now() - this.lastActivityAt > CONNECTION_STALE_AFTER_MS) {
      this.reconnectAttempt = 0
      this.openSource()
    }
  }

  reconnect(): void {
    if (this.stopped) {
      this.connect()
      return
    }
    this.reconnectAttempt = 0
    this.openSource()
  }

  disconnect(): void {
    this.stopped = true
    this.clearReconnectTimer()
    this.stopHealthMonitor()
    this.closeSource()
    this.reconnectAttempt = 0
    this.updateStatus('disconnected')
  }

  getStatus(): ConnectionStatus {
    return this.status
  }

  private openSource(): void {
    if (this.stopped) return
    this.clearReconnectTimer()
    this.closeSource()
    this.updateStatus(this.reconnectAttempt === 0 ? 'connecting' : 'reconnecting')
    const url = new URL(this.config.url, window.location.href)
    url.searchParams.set('principal_id', runtimePrincipalId())
    try {
      const source = new EventSource(url)
      this.source = source
      source.addEventListener('open', this.handleOpen)
      source.addEventListener('combo_frontend_event', this.handleMessage)
      source.addEventListener('combo_frontend_heartbeat', this.handleHeartbeat)
      source.addEventListener('message', this.handleMessage)
      source.addEventListener('error', this.handleError)
    } catch (error) {
      this.updateStatus('error')
      this.config.onError(error instanceof Error ? error : new Error(String(error)))
      this.scheduleReconnect()
    }
  }

  private handleOpen = () => {
    this.reconnectAttempt = 0
    this.markActivity()
    this.updateStatus('connected')
  }

  private handleMessage = (event: MessageEvent<string>) => {
    this.markActivity()
    try {
      const data = JSON.parse(event.data)
      const runtimeEvent = data.kind === 'combo_frontend_event' ? data.event : data
      if (!runtimeEvent?.event_id) return
      if (this.seenEventIds.has(runtimeEvent.event_id)) return
      this.seenEventIds.add(runtimeEvent.event_id)
      if (this.seenEventIds.size > 10000) {
        const firstId = this.seenEventIds.values().next().value
        if (firstId !== undefined) this.seenEventIds.delete(firstId)
      }
      this.config.onEvent(runtimeEvent as RuntimeFrontendEvent)
    } catch (error) {
      this.config.onError(error as Error)
    }
  }

  private handleHeartbeat = () => {
    this.markActivity()
  }

  private handleError = () => {
    if (this.stopped) return
    this.closeSource()
    this.config.onError(new Error('SSE connection error'))
    this.scheduleReconnect()
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer !== null) return
    const delay = Math.min(
      RECONNECT_INITIAL_DELAY_MS * (2 ** this.reconnectAttempt),
      RECONNECT_MAX_DELAY_MS,
    )
    this.reconnectAttempt += 1
    this.updateStatus('reconnecting')
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.openSource()
    }, delay)
  }

  private closeSource(): void {
    const source = this.source
    if (!source) return
    this.source = null
    source.removeEventListener('open', this.handleOpen)
    source.removeEventListener('combo_frontend_event', this.handleMessage)
    source.removeEventListener('combo_frontend_heartbeat', this.handleHeartbeat)
    source.removeEventListener('message', this.handleMessage)
    source.removeEventListener('error', this.handleError)
    source.close()
  }

  private markActivity(): void {
    this.lastActivityAt = Date.now()
  }

  private startHealthMonitor(): void {
    if (this.healthTimer !== null) return
    this.healthTimer = window.setInterval(() => this.ensureConnected(), CONNECTION_HEALTH_CHECK_MS)
  }

  private stopHealthMonitor(): void {
    if (this.healthTimer === null) return
    window.clearInterval(this.healthTimer)
    this.healthTimer = null
    this.lastActivityAt = 0
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return
    window.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
  }

  private updateStatus(status: ConnectionStatus): void {
    if (this.status === status) return
    this.status = status
    this.config.onStatusChange(status)
  }
}
