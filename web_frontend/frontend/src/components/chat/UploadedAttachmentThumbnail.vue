<template>
  <img
    v-if="imageAttachment && previewUrl"
    class="uploaded-attachment-thumbnail"
    :src="previewUrl"
    :alt="attachment.name"
  />
  <ResourceIcon
    v-else
    :name="attachment.name"
    :mime-type="attachment.mime_type"
    :kind="attachment.kind"
    :size="18"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import { useRuntimeAttachmentObjectUrl } from '@/composables/useRuntimeAttachmentObjectUrl'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import { isImageResource } from '@/utils/workspaceResources'

const props = defineProps<{
  attachment: RuntimeAttachmentInput
}>()

const imageAttachment = computed(() => isImageResource(
  props.attachment.name,
  props.attachment.mime_type,
))
const attachmentId = computed(() => (
  imageAttachment.value ? props.attachment.attachment_id : null
))
const { url: previewUrl } = useRuntimeAttachmentObjectUrl(attachmentId)
</script>

<style scoped>
.uploaded-attachment-thumbnail {
  display: block;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  border-radius: 8px;
  object-fit: cover;
}
</style>
