<template>
  <main class="diff-preview-page">
    <section class="diff-preview-card">
      <header class="diff-preview-header">
        <div>
          <span>LOCAL PREVIEW</span>
          <h1>{{ t('git.reviewTitle') }}</h1>
        </div>
        <span class="preview-total">
          {{ t('git.changedFiles', { count: 1 }) }}
          <b>+8</b>
          <i>-4</i>
        </span>
      </header>
      <div class="preview-file-row">
        <button type="button" class="preview-file-pill active">M README.md</button>
        <code>README.md</code>
      </div>
      <GitDiffViewer :diff="sampleDiff" />
    </section>
  </main>
</template>

<script setup lang="ts">
import type { GitFileDiff } from '@/api/git'
import GitDiffViewer from '@/components/chat/GitDiffViewer.vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const sampleDiff: GitFileDiff = {
  old_path: 'README.md',
  path: 'README.md',
  binary: false,
  truncated: false,
  old_content: `# Combo

一个本地优先的智能协作工作区。

## 功能

- 对话
- 本地工作区
- Git 变更查看

## 启动

npm run dev
`,
  new_content: `# Combo

一个本地优先、围绕真实工作区运行的智能协作应用。

## 功能

- 对话与跨会话记忆
- 本地工作区与文件预览
- Git 变更审查、撤销和重新应用
- 技能、工具、MCP、定时任务与知识库

## 启动

npm run dev

完成后访问本地预览页面。
`,
}
</script>

<style scoped>
.diff-preview-page { width: 100%; height: 100%; min-width: 0; min-height: 0; display: grid; place-items: center; padding: 24px; overflow: hidden; background: var(--app-surface); }
.diff-preview-card { width: min(1240px, 100%); height: min(760px, 100%); min-width: 0; min-height: 0; display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: 12px; padding: 24px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 28px; background: var(--app-surface-elevated); box-shadow: var(--app-shadow-lg); }
.diff-preview-header { min-width: 0; display: flex; align-items: end; justify-content: space-between; gap: 20px; }
.diff-preview-header > div { display: grid; gap: 5px; }.diff-preview-header span { color: var(--app-text-muted); font: 10px/1 var(--app-font-mono); letter-spacing: .12em; }.diff-preview-header h1 { color: var(--app-text-strong); font-size: 21px; }
.preview-total { display: inline-flex; align-items: center; gap: 8px; padding: 9px 13px; border: 1px solid var(--app-border); border-radius: 999px; letter-spacing: 0 !important; }.preview-total b { color: var(--app-diff-addition); }.preview-total i { color: var(--app-diff-deletion); font-style: normal; }
.preview-file-row { min-width: 0; display: flex; align-items: center; gap: 12px; }.preview-file-row code { min-width: 0; overflow: hidden; color: var(--app-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.preview-file-pill { flex: 0 0 auto; padding: 9px 14px; border: 1px solid var(--app-text); border-radius: 999px; background: var(--app-text); color: var(--app-text-inverse); font: 11px/1 var(--app-font-mono); }
@media (max-width: 700px) { .diff-preview-page { padding: 12px; }.diff-preview-card { padding: 16px; border-radius: 22px; }.diff-preview-header { align-items: flex-start; flex-direction: column; }.preview-total { align-self: flex-start; } }
</style>
