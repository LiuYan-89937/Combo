<template>
  <div>
    <!-- 使用 Naive UI 的通知系统 -->
  </div>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useNotification } from 'naive-ui'
import { useUiStore } from '@/stores/ui'

const notification = useNotification()
const uiStore = useUiStore()

// 监听通知变化
watch(
  () => uiStore.notifications,
  (notifications) => {
    // 显示最新的通知
    if (notifications.length > 0) {
      const latest = notifications[notifications.length - 1]
      notification[latest.type]({
        title: latest.title,
        content: latest.message,
        duration: latest.duration || 5000,
        onClose: () => {
          uiStore.removeNotification(latest.id)
        },
      })
    }
  },
  { deep: true }
)
</script>
