<template>
  <img
    v-if="imageAttachment && previewUrl"
    class="uploaded-attachment-thumbnail"
    :src="previewUrl"
    :alt="attachment.name"
    :style="thumbnailStyle"
  />
  <span v-else class="uploaded-attachment-fallback">
    <ResourceIcon
      :name="attachment.name"
      :mime-type="attachment.mime_type"
      :kind="attachment.kind"
      :size="iconSize"
    />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import { useRuntimeAttachmentObjectUrl } from '@/composables/useRuntimeAttachmentObjectUrl'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import { isImageResource } from '@/utils/workspaceResources'

const props = withDefaults(defineProps<{
  attachment: RuntimeAttachmentInput
  size?: number
}>(), {
  size: 44,
})

const imageAttachment = computed(() => isImageResource(
  props.attachment.name,
  props.attachment.mime_type,
))
const attachmentId = computed(() => (
  imageAttachment.value ? props.attachment.attachment_id : null
))
const { url: previewUrl } = useRuntimeAttachmentObjectUrl(attachmentId)
const iconSize = computed(() => Math.max(16, Math.round(props.size * 0.4)))
const thumbnailStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  flexBasis: `${props.size}px`,
}))
</script>

<style scoped>
.uploaded-attachment-thumbnail {
  display: block;
  flex: 0 0 auto;
  border-radius: var(--app-radius-sm);
  object-fit: cover;
}

.uploaded-attachment-fallback {
  display: grid;
  place-items: center;
  background: var(--app-surface-muted);
  color: var(--app-text-muted);
}
</style>
