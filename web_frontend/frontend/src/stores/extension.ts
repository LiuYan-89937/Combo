/**
 * Extension Store
 * 管理 MCP 服务器和 Skill 扩展
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ExtensionItemView } from '@/types/protocol'

export const useExtensionStore = defineStore('extension', () => {
  const items = ref<ExtensionItemView[]>([])
  const testResult = ref<any | null>(null)

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

  function reset(): void {
    items.value = []
    testResult.value = null
  }

  return {
    items,
    testResult,
    mcpItems,
    skillItems,
    setItems,
    setTestResult,
    reset,
  }
})
