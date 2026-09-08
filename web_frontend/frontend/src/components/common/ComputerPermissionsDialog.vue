<template>
  <n-modal
    v-model:show="permissions.visible"
    preset="card"
    :title="t('computerPermissions.title')"
    :mask-closable="false"
    style="width: min(460px, calc(100vw - 32px))"
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
      <n-button type="primary" :disabled="permissions.busy" @click="permissions.check()">
        {{ t('computerPermissions.recheck') }}
      </n-button>
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

function recheckOnFocus() {
  if (startup.ready && permissions.visible && !permissions.busy) void permissions.check()
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
</style>
