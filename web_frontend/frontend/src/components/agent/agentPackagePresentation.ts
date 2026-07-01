import type {
  AgentPackageExtensionView,
  AgentPackageInstanceView,
  AgentPackageKnowledgeSourceView,
  AgentPackageToolView,
  AgentPackageView,
} from '@/stores/agent'

export type NaiveTagType = 'default' | 'success' | 'warning' | 'error' | 'info'

export function packageDisplayName(pkg: AgentPackageView): string {
  return pkg.agent_name || pkg.name || '未命名 Agent'
}

export function isPackageReady(instance: AgentPackageInstanceView | null): boolean {
  return instance?.ready === true
}

export function isInstanceInitializing(instance: AgentPackageInstanceView | null): boolean {
  return instance?.status === 'initializing'
}

export function instanceStatusLabel(instance: AgentPackageInstanceView | null): string {
  if (!instance) return '未初始化'
  if (instance.error) return '实例异常'
  if (instance.status === 'initializing') return '初始化中'
  if (instance.ready) return instance.active_request_count ? `运行中 ${instance.active_request_count}` : '已就绪'
  return '未初始化'
}

export function instanceStatusType(instance: AgentPackageInstanceView | null): NaiveTagType {
  if (instance?.error) return 'error'
  if (instance?.status === 'initializing') return 'info'
  if (instance?.active_request_count) return 'info'
  if (instance?.ready) return 'success'
  return 'default'
}

export function packageInitial(pkg: AgentPackageView): string {
  const name = pkg.agent_name || pkg.name || pkg.package_id
  return name.charAt(0).toUpperCase()
}

export function packageColor(pkg: AgentPackageView): string {
  const colors = ['#18a058', '#2080f0', '#f0a020', '#d03050']
  const hash = pkg.package_id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
  return colors[hash % colors.length]
}

export function statusType(status: string): NaiveTagType {
  const types: Record<string, NaiveTagType> = {
    ready: 'success',
    running: 'info',
    failed: 'error',
  }
  return types[status] || 'default'
}

export function formatPackageDate(timestamp: string | null): string {
  if (!timestamp) return '未知'
  const date = new Date(timestamp)
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

export function formatPackageDateTime(timestamp: string | null): string {
  if (!timestamp) return '未知'
  return new Date(timestamp).toLocaleString('zh-CN')
}

export function extensionKey(item: AgentPackageExtensionView): string {
  const payloadId = item.payload?.server_id || item.payload?.skill_id
  return String(payloadId || item.name)
}

export function toolMeta(tool: AgentPackageToolView): string {
  return tool.concurrent === false ? '串行执行' : '可并发执行'
}

export function extensionDescription(item: AgentPackageExtensionView): string {
  return String(item.payload?.description || item.summary || '').trim()
}

export function mcpMeta(server: AgentPackageExtensionView): string {
  const payload = server.payload || {}
  const envCount = Array.isArray(payload.env_keys) ? payload.env_keys.length : 0
  const parts = [
    server.transport || payload.transport,
    server.scope,
    envCount > 0 ? `环境变量 ${envCount} 项` : null,
    payload.timeout_seconds ? `${payload.timeout_seconds} 秒超时` : null,
  ].filter(Boolean)
  return parts.join(' · ') || 'MCP 服务器'
}

export function skillMeta(skill: AgentPackageExtensionView): string {
  const payload = skill.payload || {}
  const resourceCount = Number(payload.resource_count || 0)
  const scriptCount = Number(payload.script_count || 0)
  const parts = [
    skill.scope,
    resourceCount > 0 ? `${resourceCount} 个资源` : null,
    scriptCount > 0 ? `${scriptCount} 个脚本` : null,
  ].filter(Boolean)
  return parts.join(' · ') || 'Skill'
}

export function knowledgeMeta(source: AgentPackageKnowledgeSourceView): string {
  const parts = [
    source.kind,
    source.mode,
    source.document_count != null ? `${source.document_count} 文档` : null,
    source.updated_at ? `更新于 ${formatPackageDateTime(source.updated_at)}` : null,
  ].filter(Boolean)
  return parts.join(' · ') || '知识源'
}

export function knowledgeSamples(source: AgentPackageKnowledgeSourceView): string {
  const titles = (source.sample_titles || []).filter(Boolean).slice(0, 3)
  return titles.length > 0 ? `样例：${titles.join('、')}` : ''
}
