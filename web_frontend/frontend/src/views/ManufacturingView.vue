<template>
  <div class="view-placeholder">
    <n-empty description="Agent 制造功能开发中">
      <template #icon>
        <n-icon size="80">
          <Build />
        </n-icon>
      </template>
      <template #extra>
        <n-text depth="3">
          此页面正在开发中，敬请期待
        </n-text>
      </template>
    </n-empty>
  </div>
</template>

<script setup lang="ts">
import { NEmpty, NIcon, NText } from 'naive-ui'
import { Build } from '@vicons/ionicons5'
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
