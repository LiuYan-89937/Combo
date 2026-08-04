<script setup lang="ts">
/*
 * Maps an upload/release status to a toned badge. The status vocabulary is
 * fixed by the backend (UPLOAD_STATUSES); tone is presentational only.
 */
import { computed } from 'vue'
import BaseBadge from '@/components/base/BaseBadge.vue'
import BaseIcon, { type IconName } from '@/components/base/BaseIcon.vue'
import { useI18n } from '@/i18n'
import type { UploadStatus } from '@/api/types'

const props = defineProps<{ status: UploadStatus | string }>()
const { t } = useI18n()

type Tone = 'neutral' | 'success' | 'warning' | 'danger'
const MAP: Record<string, { tone: Tone; icon: IconName }> = {
  awaiting_upload: { tone: 'neutral', icon: 'clock' },
  queued: { tone: 'neutral', icon: 'clock' },
  validating: { tone: 'warning', icon: 'spinner' },
  pending_review: { tone: 'warning', icon: 'clock' },
  published: { tone: 'success', icon: 'check' },
  rejected: { tone: 'danger', icon: 'x-circle' },
  failed: { tone: 'danger', icon: 'alert' },
}

const meta = computed(() => MAP[props.status] ?? { tone: 'neutral' as Tone, icon: 'clock' as IconName })
const label = computed(() => t(`status.${props.status}`))
</script>

<template>
  <BaseBadge :tone="meta.tone">
    <BaseIcon :name="meta.icon" :size="13" />
    {{ label }}
  </BaseBadge>
</template>
