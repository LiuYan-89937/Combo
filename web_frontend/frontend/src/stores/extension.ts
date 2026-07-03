/**
 * Extension Store
 * 管理 MCP 服务器和 Skill 扩展
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ExtensionItemView, ToolPermissionsView } from '@/types/protocol'

export const useExtensionStore = defineStore('extension', () => {
  const items = ref<ExtensionItemView[]>([])
  const testResult = ref<any | null>(null)
  const toolPermissions = ref<ToolPermissionsView | null>(null)

  const mcpItems = computed(() => {
    return items.value.filter((item) => item.kind === 'mcp')
  })

  const skillItems = computed(() => {
    return items.value.filter((item) => item.kind === 'skill')
  })

  function setItems(newItems: ExtensionItemView[]): void {
    items.value = newItems
  }

  function setTestResult(result: any): void {
    testResult.value = result
  }

  function setToolPermissions(value: ToolPermissionsView | null): void {
    toolPermissions.value = value
  }

  function reset(): void {
    items.value = []
    testResult.value = null
    toolPermissions.value = null
  }

  return {
    items,
    testResult,
    toolPermissions,
    mcpItems,
    skillItems,
    setItems,
    setTestResult,
    setToolPermissions,
    reset,
  }
})
