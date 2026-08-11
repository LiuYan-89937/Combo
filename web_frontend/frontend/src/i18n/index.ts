export type Locale = 'zh-CN' | 'en-US'
export type I18nKey = string

export const localeStorageKey = 'fast-agent-factory.locale'
export const localeOptions = [
  { label: '简体中文', value: 'zh-CN' },
  { label: 'English', value: 'en-US' },
] as const

const zhCN: Record<string, string> = {
  'common.cancel': '取消',
  'common.delete': '删除',
  'common.disabled': '已禁用',
  'common.edit': '编辑',
  'common.enabled': '已启用',
  'common.refresh': '刷新',
  'common.requestFailed': '请求失败',
  'common.save': '保存',
  'validation.required': '此项为必填项',
  'validation.selectionRequired': '请选择一项',
  'validation.url': '请输入有效的 HTTP 或 HTTPS 地址',
  'modelPool.title': '模型池',
  'modelPool.subtitle': '管理运行时使用的模型配置与凭据',
  'modelPool.profiles': '模型配置',
  'modelPool.credentials': '凭据',
  'modelPool.usage': '用量',
  'modelPool.addProfile': '添加模型',
  'modelPool.addCredential': '添加凭据',
  'modelPool.noProfiles': '尚未配置模型',
  'modelPool.noCredentials': '尚未配置凭据',
  'modelPool.noUsage': '暂无用量记录',
  'modelPool.usageByModel': '按模型',
  'modelPool.usageByProvider': '按服务商',
  'modelPool.usageByRuntimeRole': '按运行角色',
  'modelPool.usageByStrategy': '按执行策略',
  'modelPool.usageCacheWrite': '缓存写入',
  'modelPool.testConnection': '测试连接',
  'modelPool.connectionSucceeded': '连接成功',
  'modelPool.embeddingConnectionSucceeded': 'Embedding 连接成功，维度 {dimensions}',
  'modelPool.infrastructureBindings': '基础模型绑定',
  'modelPool.infrastructureBindingsHint': '为路由、任务和检索选择共享模型',
  'modelPool.bindingsSaved': '模型绑定已保存',
  'modelPool.chatModel': '对话模型',
  'modelPool.embeddingModel': 'Embedding 模型',
  'modelPool.imageGenerationModel': '图像生成模型',
  'modelPool.taskModel': '任务模型',
  'modelPool.taskModelHint': '供主 Agent 的辅助模型操作使用',
  'modelPool.profileHint': '发布可供动态运行时选择的模型配置。',
  'modelPool.credentialHint': '凭据由模型配置按不可变引用使用。',
  'modelPool.noApiKey': '未配置 API Key',
}

const enUS: Record<string, string> = {
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.disabled': 'Disabled',
  'common.edit': 'Edit',
  'common.enabled': 'Enabled',
  'common.refresh': 'Refresh',
  'common.requestFailed': 'Request failed',
  'common.save': 'Save',
  'validation.required': 'This field is required',
  'validation.selectionRequired': 'Select an option',
  'validation.url': 'Enter a valid HTTP or HTTPS URL',
  'modelPool.title': 'Model Pool',
  'modelPool.subtitle': 'Manage runtime model profiles and credentials',
  'modelPool.profiles': 'Profiles',
  'modelPool.credentials': 'Credentials',
  'modelPool.usage': 'Usage',
  'modelPool.addProfile': 'Add profile',
  'modelPool.addCredential': 'Add credential',
  'modelPool.noProfiles': 'No model profiles',
  'modelPool.noCredentials': 'No credentials',
  'modelPool.noUsage': 'No usage data',
  'modelPool.usageByModel': 'By model',
  'modelPool.usageByProvider': 'By provider',
  'modelPool.usageByRuntimeRole': 'By runtime role',
  'modelPool.usageByStrategy': 'By strategy',
  'modelPool.usageCacheWrite': 'Cache writes',
  'modelPool.testConnection': 'Test connection',
  'modelPool.connectionSucceeded': 'Connection succeeded',
  'modelPool.embeddingConnectionSucceeded': 'Embedding connection succeeded ({dimensions} dimensions)',
  'modelPool.infrastructureBindings': 'Infrastructure bindings',
  'modelPool.infrastructureBindingsHint': 'Choose shared models for routing, tasks, and retrieval',
  'modelPool.bindingsSaved': 'Model bindings saved',
  'modelPool.chatModel': 'Chat model',
  'modelPool.embeddingModel': 'Embedding model',
  'modelPool.imageGenerationModel': 'Image generation model',
  'modelPool.taskModel': 'Task model',
  'modelPool.taskModelHint': 'Used for main-agent auxiliary model operations',
  'modelPool.profileHint': 'Publish model profiles for dynamic runtime selection.',
  'modelPool.credentialHint': 'Profiles refer to versioned credentials.',
  'modelPool.noApiKey': 'No API key',
}

export function normalizeLocale(value: string): Locale {
  return value.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
}

export function detectBrowserLocale(): Locale {
  return normalizeLocale(typeof navigator === 'undefined' ? 'zh-CN' : navigator.language)
}

export function translate(locale: Locale, key: I18nKey, params: Record<string, string | number> = {}): string {
  const dictionary = locale === 'zh-CN' ? zhCN : enUS
  const template = dictionary[key] || humanizeKey(key)
  return Object.entries(params).reduce(
    (value, [name, replacement]) => value.replaceAll(`{${name}}`, String(replacement)),
    template,
  )
}

function humanizeKey(key: string): string {
  const tail = key.split('.').at(-1) || key
  return tail.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ')
}
