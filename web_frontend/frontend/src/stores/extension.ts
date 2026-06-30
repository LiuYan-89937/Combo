/**
 * Extension Store
 * 管理 MCP 服务器和 Skill 扩展
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ExtensionItemView } from '@/types/protocol'

export const useExtensionStore = defineStore('extension', () => {
  const items = ref<ExtensionItemView[]>([])
  const selectedItem = ref<ExtensionItemView | null>(null)
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

  function selectItem(item: ExtensionItemView | null): void {
    selectedItem.value = item
    testResult.value = null
  }

  function setTestResult(result: any): void {
    testResult.value = result
  }

  function addOrUpdateItem(item: ExtensionItemView): void {
    const existingIndex = items.value.findIndex((i) => {
      if (item.kind === 'mcp') {
        return i.payload?.server_id === item.payload?.server_id
      } else {
        return i.payload?.skill_id === item.payload?.skill_id
      }
    })

    if (existingIndex !== -1) {
      items.value[existingIndex] = item
    } else {
      items.value.unshift(item)
    }
  }

  function removeItem(item: ExtensionItemView): void {
    const index = items.value.findIndex((i) => {
      if (item.kind === 'mcp') {
        return i.payload?.server_id === item.payload?.server_id
      } else {
        return i.payload?.skill_id === item.payload?.skill_id
      }
    })

    if (index !== -1) {
      items.value.splice(index, 1)
    }

    if (selectedItem.value === item) {
      selectedItem.value = null
    }
  }

  function updateItemEnabled(item: ExtensionItemView, enabled: boolean): void {
    const existingItem = items.value.find((i) => {
      if (item.kind === 'mcp') {
        return i.payload?.server_id === item.payload?.server_id
      } else {
        return i.payload?.skill_id === item.payload?.skill_id
      }
    })

    if (existingItem) {
      existingItem.enabled = enabled
    }
  }

  return {
    items,
    selectedItem,
    testResult,
    mcpItems,
    skillItems,
    setItems,
    selectItem,
    setTestResult,
    addOrUpdateItem,
    removeItem,
    updateItemEnabled,
  }
})
