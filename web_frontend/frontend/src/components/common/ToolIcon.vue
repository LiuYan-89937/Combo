<template>
  <n-icon :size="size"><component :is="iconComponent" /></n-icon>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import {
  ArrowsVertical, Bot, Camera, Calendar, Catalog, Close, DataBase, DataView, Document,
  Download, Edit, Folder, Keyboard, ListBulleted, ListDropdown, NetworkPublic, Search,
  Task, Terminal, TextCreation, Timer, ToolBox, TouchInteraction, Upload, View,
} from '@vicons/carbon'
import type { ToolIconName } from '@/utils/toolPresentation'

const props = withDefaults(defineProps<{ name: ToolIconName; size?: number }>(), { size: 18 })

const iconComponent = computed(() => ({
  document: Document, edit: Edit, search: Search, terminal: Terminal, folder: Folder,
  calendar: Calendar, agent: Bot, task: Task, extension: ToolBox, catalog: Catalog,
  memory: DataBase, browser: NetworkPublic, view: View, pointer: TouchInteraction,
  type: TextCreation, select: ListDropdown, keyboard: Keyboard, scroll: ArrowsVertical,
  timer: Timer, extract: DataView, camera: Camera, download: Download, upload: Upload,
  tabs: ListBulleted, close: Close, generic: ToolBox,
}[props.name]))
</script>
