import type { RuntimePlanView } from '@/types/protocol'

const STORAGE_KEY = 'combo.dismissedPlanCapsules'
const MAX_DISMISSALS = 100

export function dismissPlanCapsule(plan: RuntimePlanView): void {
  const identity = planIdentity(plan)
  if (!identity || typeof window === 'undefined') return
  const identities = readDismissals().filter(item => item !== identity)
  identities.unshift(identity)
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(identities.slice(0, MAX_DISMISSALS)))
}

export function isPlanCapsuleDismissed(plan: RuntimePlanView): boolean {
  const identity = planIdentity(plan)
  return Boolean(identity && readDismissals().includes(identity))
}

export function restorePlanCapsule(plan: RuntimePlanView): void {
  const identity = planIdentity(plan)
  if (!identity || typeof window === 'undefined') return
  const identities = readDismissals().filter(item => item !== identity)
  if (identities.length === 0) {
    window.localStorage.removeItem(STORAGE_KEY)
    return
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(identities))
}

function planIdentity(plan: RuntimePlanView): string | null {
  const runtimeInstanceId = String(plan.runtime_instance_id || '').trim()
  if (runtimeInstanceId) return `runtime:${runtimeInstanceId}`
  const requestId = String(plan.request_id || '').trim()
  return requestId ? `request:${requestId}` : null
}

function readDismissals(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(value)
      ? value.map(item => String(item || '').trim()).filter(Boolean)
      : []
  } catch {
    return []
  }
}
