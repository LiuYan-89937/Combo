<template>
  <img
    v-if="imageAttachment && previewUrl"
    class="uploaded-attachment-thumbnail"
    :src="previewUrl"
    :alt="attachment.name"
    :style="thumbnailStyle"
  />
  <span v-else class="uploaded-attachment-fallback" :style="thumbnailStyle">
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
  /** Edge length used for the standalone thumbnail and the fallback icon. */
  size?: number
  /**
   * Stretch to the parent box instead of a fixed square. Fixed-size attachment
   * tiles own their own geometry, so the thumbnail must not also set a size or
   * the inline style would win over the tile's box.
   */
  fill?: boolean
}>(), {
  size: 44,
  fill: false,
})

const imageAttachment = computed(() => isImageResource(
  props.attachment.name,
  props.attachment.mime_type,
))
const attachmentId = computed(() => (
  imageAttachment.value ? props.attachment.attachment_id : null
))
const { url: previewUrl } = useRuntimeAttachmentObjectUrl(attachmentId)
const iconSize = computed(() => Math.max(16, Math.round(props.size * 0.32)))
const thumbnailStyle = computed(() => (
  props.fill
    ? {}
    : {
        width: `${props.size}px`,
        height: `${props.size}px`,
        flexBasis: `${props.size}px`,
      }
))
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
  color: var(--app-text-muted);
}
</style>
