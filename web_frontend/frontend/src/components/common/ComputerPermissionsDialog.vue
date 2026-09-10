<template>
  <n-modal
    :show="permissions.visible"
    preset="card"
    closable
    :title="t('computerPermissions.title')"
    :mask-closable="true"
    style="width: min(460px, calc(100vw - 32px))"
    @update:show="handleShow"
  >
    <div class="permission-content">
      <p>{{ t('computerPermissions.description') }}</p>
      <div v-for="permission in permissionNames" :key="permission" class="permission-row">
        <span>{{ t(`computerPermissions.${permission}`) }}</span>
        <n-button
          :disabled="permissions.busy || permissions.status?.[permission]"
          @click="permissions.request(permission)"
        >
          {{ t(permissions.status?.[permission] ? 'computerPermissions.granted' : 'computerPermissions.authorize') }}
        </n-button>
      </div>
      <p>{{ t('computerPermissions.recheckHint') }}</p>
      <n-text v-if="permissions.error" type="error">{{ permissions.error }}</n-text>
      <div class="permission-actions">
        <n-button quaternary :disabled="permissions.busy" @click="permissions.dismiss()">
          {{ t('computerPermissions.later') }}
        </n-button>
        <n-button type="primary" :disabled="permissions.busy" @click="permissions.check()">
          {{ t('computerPermissions.recheck') }}
        </n-button>
      </div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useComputerPermissionsStore } from '@/stores/computerPermissions'
import { useStartupStore } from '@/stores/startup'
import { useI18n } from '@/composables/useI18n'

const permissions = useComputerPermissionsStore()
const startup = useStartupStore()
const { t } = useI18n()
const permissionNames = ['accessibility', 'screen_recording'] as const

// 关闭（右上角叉或点击遮罩）表示不再提示，之后只能从设置里开启。
function handleShow(value: boolean) {
  if (!value) permissions.dismiss()
}

function recheckOnFocus() {
  if (startup.ready && !permissions.busy) void permissions.check()
}

watch(() => startup.ready, (ready) => {
  if (ready) void permissions.check()
}, { immediate: true })
onMounted(() => window.addEventListener('focus', recheckOnFocus))
onBeforeUnmount(() => window.removeEventListener('focus', recheckOnFocus))
</script>

<style scoped>
.permission-content { display: flex; flex-direction: column; gap: 16px; }
.permission-content p { margin: 0; }
.permission-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.permission-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
