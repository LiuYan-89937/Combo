const PRINCIPAL_STORAGE_KEY = 'combo.principal_id'
const CLIENT_STORAGE_KEY = 'combo.client_instance_id'

export function runtimePrincipalId(): string {
  return stableBrowserId(PRINCIPAL_STORAGE_KEY)
}

export function runtimeClientInstanceId(): string {
  return stableBrowserId(CLIENT_STORAGE_KEY)
}

function stableBrowserId(key: string): string {
  const current = window.localStorage.getItem(key)?.trim()
  if (current) return current
  const value = crypto.randomUUID().replace(/-/g, '')
  window.localStorage.setItem(key, value)
  return value
}
