<template>
  <main class="mascot-preview">
    <header class="preview-header">
      <div>
        <span class="eyebrow">PNG FRAME LAB</span>
        <h1>Combo 动作库</h1>
        <p>双角色状态与两名角色的独立动画。所有动作均由独立 PNG 序列帧播放。</p>
      </div>
      <div class="preview-controls">
        <n-button secondary @click="paused = !paused">
          {{ paused ? '继续播放' : '暂停全部' }}
        </n-button>
        <label>
          <span>{{ fps }} FPS</span>
          <n-slider v-model:value="fps" :min="2" :max="10" :step="1" />
        </label>
      </div>
    </header>

    <section class="preview-section">
      <header class="section-header">
        <div><span class="eyebrow">PAIRED STATES</span><h2>协作状态</h2></div>
        <small>工作状态由两个独立 running 动画组合，其余状态为双角色动画。</small>
      </header>
      <div class="state-grid paired-grid">
        <article v-for="item in pairedStates" :key="item.state" class="state-card">
          <div class="state-stage">
            <ComboMascot
              :state="item.state"
              :size="210"
              :paused="paused"
              :fps="fps"
              :aria-label="item.title"
            />
          </div>
          <footer><strong>{{ item.title }}</strong><small>{{ item.description }}</small></footer>
        </article>
      </div>
    </section>

    <section v-for="character in characters" :key="character.id" class="preview-section">
      <header class="section-header">
        <div><span class="eyebrow">{{ character.eyebrow }}</span><h2>{{ character.title }}</h2></div>
        <small>单角色、单动作、独立生成；不从双角色素材裁切。</small>
      </header>
      <div class="state-grid character-grid">
        <article v-for="action in characterActions" :key="action.id" class="state-card">
          <div class="state-stage">
            <ComboFrameAnimation
              :character="character.id"
              :action="action.id"
              :size="196"
              :paused="paused"
              :fps="fps"
              :aria-label="`${character.title}${action.title}`"
            />
          </div>
          <footer><strong>{{ action.title }}</strong><small>{{ action.description }}</small></footer>
        </article>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NSlider } from 'naive-ui'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import ComboMascot from '@/components/brand/ComboMascot.vue'
import type {
  ComboCharacter,
  ComboCharacterAction,
  ComboMascotState,
} from '@/components/brand/comboMascotAssets'

const paused = ref(false)
const fps = ref(4)

const pairedStates: Array<{
  state: ComboMascotState
  title: string
  description: string
}> = [
  { state: 'idle', title: '待机 / Idle', description: '共同呼吸与眨眼' },
  { state: 'thinking', title: '思考 / Review', description: '收敛视线与轻微前倾' },
  { state: 'working', title: '工作 / Running', description: '两名角色独立跑动' },
  { state: 'waiting', title: '等待 / Approval', description: '期待用户确认' },
  { state: 'complete', title: '完成 / Complete', description: '无手的同步庆祝节拍' },
  { state: 'error', title: '异常 / Failed', description: '克制的失拍反馈' },
]

const characters: Array<{
  id: Exclude<ComboCharacter, 'paired'>
  eyebrow: string
  title: string
}> = [
  { id: 'lead', eyebrow: 'LEAD NOTE', title: '大音符' },
  { id: 'companion', eyebrow: 'COMPANION NOTE', title: '小音符' },
]

const characterActions: Array<{
  id: ComboCharacterAction
  title: string
  description: string
}> = [
  { id: 'idle', title: '待机 / Idle', description: '低干扰呼吸与眨眼' },
  { id: 'running', title: '跑动 / Running', description: '短腿交替步态，无新增肢体' },
  { id: 'jumping', title: '跳跃 / Jumping', description: '预备、腾空、落地与复位' },
]
</script>

<style scoped>
.mascot-preview {
  min-height: 100%;
  padding: clamp(28px, 4vw, 56px);
  color: var(--app-text);
  background: var(--app-surface);
}

.preview-header,
.preview-section {
  max-width: 1240px;
  margin-inline: auto;
}

.preview-header,
.section-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 32px;
}

.preview-header {
  margin-bottom: 42px;
}

.eyebrow {
  display: block;
  margin-bottom: 8px;
  color: var(--app-text-muted);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .16em;
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  font-size: clamp(34px, 5vw, 58px);
  line-height: .98;
  letter-spacing: -.055em;
}

h2 {
  font-size: 24px;
  letter-spacing: -.035em;
}

.preview-header p {
  margin-top: 14px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.preview-controls {
  display: flex;
  align-items: center;
  gap: 18px;
}

.preview-controls label {
  display: grid;
  width: 180px;
  gap: 7px;
  color: var(--app-text-secondary);
  font-size: 11px;
}

.preview-section + .preview-section {
  margin-top: 44px;
}

.section-header {
  margin-bottom: 14px;
}

.section-header small,
.state-card small {
  color: var(--app-text-muted);
  font-size: 10px;
}

.state-grid {
  display: grid;
  gap: 12px;
}

.paired-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.character-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.state-card {
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.state-stage {
  display: grid;
  min-height: 270px;
  place-items: center;
  background-color: var(--app-surface-muted);
  background-image:
    linear-gradient(45deg, var(--app-divider) 25%, transparent 25%),
    linear-gradient(-45deg, var(--app-divider) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, var(--app-divider) 75%),
    linear-gradient(-45deg, transparent 75%, var(--app-divider) 75%);
  background-position: 0 0, 0 8px, 8px -8px, -8px 0;
  background-size: 16px 16px;
}

.state-card footer {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
  border-top: 1px solid var(--app-divider);
}

.state-card strong {
  font-size: 13px;
}

@media (max-width: 900px) {
  .preview-header,
  .section-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .paired-grid,
  .character-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .preview-controls {
    width: 100%;
    flex-wrap: wrap;
  }

  .paired-grid,
  .character-grid {
    grid-template-columns: 1fr;
  }
}
</style>
