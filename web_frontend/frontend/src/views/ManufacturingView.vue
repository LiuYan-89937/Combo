<template>
  <div class="view-placeholder">
    <n-empty :description="t('manufacturing.developing')">
      <template #icon>
        <n-icon size="80">
          <Build />
        </n-icon>
      </template>
      <template #extra>
        <n-text depth="3">
          {{ t('manufacturing.developingHint') }}
        </n-text>
      </template>
    </n-empty>
  </div>
</template>

<script setup lang="ts">
import { NEmpty, NIcon, NText } from 'naive-ui'
import { Build } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
</script>

<style scoped>
.view-placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}
</style>
