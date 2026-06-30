<template>
  <n-modal v-model:show="show" preset="card" title="命令面板" style="width: 600px">
    <n-input
      v-model:value="searchQuery"
      placeholder="搜索命令..."
      clearable
      autofocus
    />
    <n-list class="command-list" hoverable clickable>
      <n-list-item
        v-for="cmd in filteredCommands"
        :key="cmd.key"
        @click="executeCommand(cmd)"
      >
        <n-thing :title="cmd.title" :description="cmd.description" />
      </n-list-item>
    </n-list>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NInput, NList, NListItem, NThing } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useCommand } from '@/composables/useCommand'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const router = useRouter()
const commands = useCommand()
const searchQuery = ref('')

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const allCommands = [
  { key: 'goto-factory', title: '打开闲聊', description: '进入闲聊页面', action: () => router.push('/factory') },
  { key: 'goto-manufacturing', title: '打开 Agent 制造', description: '创建新的 Agent', action: () => router.push('/manufacturing') },
  { key: 'goto-agents', title: '打开已发布 Agent', description: '查看和运行已发布的 Agent', action: () => router.push('/agents') },
  { key: 'new-session', title: '新建会话', description: '创建新的工厂会话', action: () => commands.newSession() },
  { key: 'cancel', title: '取消运行', description: '取消当前正在运行的请求', action: () => commands.cancelRequest() },
]

const filteredCommands = computed(() => {
  if (!searchQuery.value) return allCommands
  const query = searchQuery.value.toLowerCase()
  return allCommands.filter(
    (cmd) =>
      cmd.title.toLowerCase().includes(query) ||
      cmd.description.toLowerCase().includes(query)
  )
})

function executeCommand(cmd: typeof allCommands[0]) {
  cmd.action()
  show.value = false
  searchQuery.value = ''
}
</script>

<style scoped>
.command-list {
  margin-top: 16px;
  max-height: 400px;
  overflow-y: auto;
}
</style>
