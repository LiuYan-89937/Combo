<template>
  <n-drawer v-model:show="show" :width="500" placement="right">
    <n-drawer-content title="调试面板">
      <n-tabs type="line">
        <n-tab-pane name="events" tab="事件流">
          <div class="debug-content">
            <n-text depth="3">最近 {{ runtimeStore.debugEvents.length }} 个事件</n-text>
            <n-list bordered style="margin-top: 12px">
              <n-list-item v-for="event in recentEvents" :key="event.event_id">
                <n-thing>
                  <template #header>
                    <n-tag type="info" size="small">{{ event.event_type }}</n-tag>
                  </template>
                  <template #description>
                    <n-text depth="3" style="font-size: 12px">
                      {{ event.event_id }}
                    </n-text>
                  </template>
                  <n-code
                    v-if="event.payload && Object.keys(event.payload).length > 0"
                    :code="JSON.stringify(event.payload, null, 2)"
                    language="json"
                    style="font-size: 11px"
                  />
                </n-thing>
              </n-list-item>
            </n-list>
          </div>
        </n-tab-pane>

        <n-tab-pane name="state" tab="状态">
          <div class="debug-content">
            <n-code
              :code="stateSnapshot"
              language="json"
              style="font-size: 12px"
            />
          </div>
        </n-tab-pane>
      </n-tabs>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NDrawer, NDrawerContent, NTabs, NTabPane, NText, NList, NListItem, NThing, NTag, NCode } from 'naive-ui'
import { useRuntimeStore } from '@/stores/runtime'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const runtimeStore = useRuntimeStore()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const recentEvents = computed(() => {
  return runtimeStore.debugEvents.slice(-20).reverse()
})

const stateSnapshot = computed(() => {
  return JSON.stringify(
    {
      runStatus: runtimeStore.runStatus,
      currentMode: runtimeStore.currentMode,
      activeRequestId: runtimeStore.activeRequestId,
      connectionStatus: runtimeStore.connectionStatus,
      transcriptCount: runtimeStore.transcript.length,
      toolsCount: runtimeStore.tools.length,
    },
    null,
    2
  )
})
</script>

<style scoped>
.debug-content {
  padding: 12px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}
</style>
