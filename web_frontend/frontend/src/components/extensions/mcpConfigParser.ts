import type { McpServerConfig } from '@/api/resourceTypes'

type JsonObject = Record<string, unknown>

export interface McpImportResult {
  servers: McpServerConfig[]
  errors: string[]
}

export function parseMcpConfigText(text: string): McpImportResult {
  const source = text.trim()
  if (!source) return { servers: [], errors: ['请粘贴 MCP 配置。'] }
  let decoded: unknown
  try {
    decoded = JSON.parse(source)
  } catch (error) {
    return { servers: [], errors: [`JSON 解析失败：${error instanceof Error ? error.message : String(error)}`] }
  }
  const entries = mcpServerEntries(decoded)
  if (entries.length === 0) return { servers: [], errors: ['没有找到可识别的 MCP Server 配置。'] }
  const servers: McpServerConfig[] = []
  const errors: string[] = []
  entries.forEach(([name, value], index) => {
    try {
      servers.push(normalizeMcpServer(value, name || `mcp_server_${index + 1}`))
    } catch (error) {
      errors.push(`${name || `Server ${index + 1}`}：${error instanceof Error ? error.message : String(error)}`)
    }
  })
  const duplicateIds = duplicatedValues(servers.map(server => server.server_id || ''))
  if (duplicateIds.length > 0) errors.push(`Server ID 重复：${duplicateIds.join('、')}`)
  return { servers, errors }
}

export function mcpConfigRecordText(value: string | Record<string, string> | undefined): string {
  if (!value) return ''
  if (typeof value === 'string') return value
  return Object.entries(value).map(([key, item]) => `${key}=${item}`).join('\n')
}

export function mcpConfigArgsText(value: string | string[] | undefined): string {
  if (!value) return ''
  return Array.isArray(value) ? value.map(shellToken).join(' ') : value
}

function mcpServerEntries(value: unknown): Array<[string, JsonObject]> {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => isObject(item) ? [[String(item.name || item.server_id || `mcp_server_${index + 1}`), item]] : [])
  }
  if (!isObject(value)) return []
  const mcpServers = value.mcpServers
  if (isObject(mcpServers)) return objectEntries(mcpServers)
  const servers = value.servers
  if (Array.isArray(servers)) {
    return servers.flatMap((item, index) => isObject(item) ? [[String(item.name || item.server_id || `mcp_server_${index + 1}`), item]] : [])
  }
  if (isObject(servers)) return objectEntries(servers)
  if (hasServerShape(value)) return [[String(value.name || value.server_id || 'mcp_server'), value]]
  return objectEntries(value).filter(([, item]) => hasServerShape(item))
}

function normalizeMcpServer(raw: JsonObject, fallbackName: string): McpServerConfig {
  const displayName = String(raw.display_name || raw.name || fallbackName).trim()
  const url = String(raw.url || raw.endpoint || '').trim()
  const transport = normalizeTransport(raw.transport || raw.type, Boolean(url))
  const command = normalizeCommand(raw.command)
  if (transport === 'stdio' && !command) throw new Error('stdio transport 必须提供 command。')
  if (transport !== 'stdio' && !url) throw new Error(`${transport} transport 必须提供 URL。`)
  return {
    server_id: normalizeIdentifier(String(raw.server_id || fallbackName)),
    display_name: displayName || fallbackName,
    description: String(raw.description || raw.summary || '').trim(),
    transport,
    command: command || undefined,
    args: normalizeArgs(raw.args),
    cwd: String(raw.cwd || '').trim() || undefined,
    env: stringRecord(raw.env),
    url: url || undefined,
    headers: stringRecord(raw.headers),
    timeout_seconds: positiveNumber(raw.timeout_seconds || raw.timeout, 60),
    enabled: raw.enabled !== false,
    risk_level_default: normalizeRisk(raw.risk_level_default),
    source: {
      type: transport === 'stdio' ? 'imported' : 'remote',
      name: displayName || fallbackName,
      description: String(raw.description || raw.summary || '').trim() || undefined,
    },
  }
}

function normalizeTransport(value: unknown, hasUrl: boolean): McpServerConfig['transport'] {
  const transport = String(value || '').trim().toLowerCase().replace(/-/g, '_')
  if (!transport) return hasUrl ? 'streamable_http' : 'stdio'
  if (transport === 'http' || transport === 'streamablehttp') return 'streamable_http'
  if (transport === 'streamable_http' || transport === 'sse' || transport === 'stdio') return transport
  throw new Error(`不支持的 transport：${transport}`)
}

function normalizeCommand(value: unknown): string {
  if (Array.isArray(value)) return String(value[0] || '').trim()
  return String(value || '').trim()
}

function normalizeArgs(value: unknown): string | string[] {
  if (Array.isArray(value)) return value.map(item => String(item)).filter(Boolean)
  const text = String(value || '').trim()
  return text
}

function stringRecord(value: unknown): Record<string, string> | undefined {
  if (!isObject(value)) return undefined
  const entries = Object.entries(value).map(([key, item]) => [key, String(item)] as const)
  return entries.length > 0 ? Object.fromEntries(entries) : undefined
}

function normalizeRisk(value: unknown): 'low' | 'medium' | 'high' {
  const risk = String(value || 'medium')
  return risk === 'low' || risk === 'high' ? risk : 'medium'
}

function positiveNumber(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function normalizeIdentifier(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')
  if (!normalized) return 'mcp_server'
  return /^\d/.test(normalized) ? `mcp_${normalized}` : normalized
}

function objectEntries(value: JsonObject): Array<[string, JsonObject]> {
  return Object.entries(value).flatMap(([name, item]) => isObject(item) ? [[name, item]] : [])
}

function hasServerShape(value: JsonObject): boolean {
  return ['command', 'url', 'endpoint', 'transport', 'args'].some(key => key in value)
}

function duplicatedValues(values: string[]): string[] {
  return [...new Set(values.filter((value, index) => value && values.indexOf(value) !== index))]
}

function isObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function shellToken(value: string): string {
  return /\s/.test(value) ? JSON.stringify(value) : value
}
